"""Traçabilité création contribuable + clés manquantes identité."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.abonne.contribuable_identite import completude_identite, normaliser_payload
from backend.main import app
from backend.plateforme.provisionnement import (
    derniere_version_publiee,
    provisionner_cabinet,
)

pytestmark = pytest.mark.db


def _colonnes_audit_ok(session) -> bool:
    n = session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'contribuable' "
            "AND column_name IN ('cree_le', 'cree_par')"
        )
    ).scalar_one()
    return int(n) >= 2


def test_completude_cles_manquantes():
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        regime_fiscal="reel",
        forme_juridique="SA",
        capital_social=1,
    )
    c = completude_identite(p)
    assert "cles_manquantes" in c
    assert "commune" in c["cles_manquantes"]
    assert "centre_impots" in c["cles_manquantes"]
    assert "Commune / ville" in c["manquants"]


def test_creation_contribuable_audit_api(session):
    if not _colonnes_audit_ok(session):
        pytest.skip("migration 025 non appliquée — lancez make migrate")

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import creer_version_brouillon, publier_version

        lib = f"v-audit-{uuid.uuid4().hex[:6]}"
        creer_version_brouillon(session, lib, note="audit")
        publier_version(session, lib, "audit@test.ci")

    email = f"audit.{uuid.uuid4().hex[:8]}@demo.local"
    mdp = "audit-audit1"
    r_prov = provisionner_cabinet(
        session,
        denomination=f"Cabinet Audit {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin=mdp,
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": mdp},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    suffix = uuid.uuid4().hex[:8]
    r = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"Audit Trail {suffix}",
            "ncc": f"CI-AUD-{suffix}",
            "forme": "pm",
            "rccm": f"RCCM-{suffix}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("cree_le"), body
    assert body.get("cree_par") is not None, body
    assert body.get("cree_par_email") == email, body

    det = client.get(f"/api/v1/contribuables/{body['id']}", headers=h)
    assert det.status_code == 200
    fiche = det.json()
    assert fiche["cree_le"] == body["cree_le"]
    assert fiche["cree_par_email"] == email
    assert not fiche.get("commune")
    assert not fiche.get("centre_impots")

    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, r_prov.tenant_id):
        n = session.execute(
            text(
                "SELECT COUNT(*) FROM journal_audit "
                "WHERE action = 'creation_contribuable' "
                "AND charge_utile->>'contribuable_id' = :cid"
            ),
            {"cid": str(body["id"])},
        ).scalar_one()
        assert int(n) >= 1


def _mission(session, tid: int, cid: int, statut: str = "en_cours") -> int:
    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, tid):
        return session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, "
                "statut) VALUES (:t, :c, 2024, :s) RETURNING id"
            ),
            {"t": tid, "c": cid, "s": statut},
        ).scalar_one()


def _suivi(
    session,
    tid: int,
    mid: int,
    cle: str,
    statut: str,
    date_relance: str | None = None,
) -> None:
    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance) VALUES (:t, :m, :c, :c, :s, :d)"
            ),
            {"t": tid, "m": mid, "c": cle, "s": statut, "d": date_relance},
        )


def test_fiche_contribuable_compteurs_suivi_renseignements(session):
    """Fiche client : items en attente / à relancer (missions non clôturées).

    Même définition que le tableau de bord cabinet : ``a_relancer`` =
    ``en_attente`` avec ``date_relance <= CURRENT_DATE`` ; les missions
    clôturées sont exclues de l'agrégat.
    """
    table = session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'suivi_demande_renseignements'"
        )
    ).scalar_one()
    if int(table) < 1:
        pytest.skip("migration suivi_demande_renseignements non appliquée")

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import creer_version_brouillon, publier_version

        lib = f"v-suivi-{uuid.uuid4().hex[:6]}"
        creer_version_brouillon(session, lib, note="suivi")
        publier_version(session, lib, "suivi@test.ci")

    email = f"suivi.{uuid.uuid4().hex[:8]}@demo.local"
    r_prov = provisionner_cabinet(
        session,
        denomination=f"Cabinet Suivi {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="suivi-suivi1",
        creer_demo=False,
    )
    session.commit()
    tid = r_prov.tenant_id

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "suivi-suivi1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    suffix = uuid.uuid4().hex[:8]
    r = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"Suivi Fiche {suffix}",
            "ncc": f"CI-SUIVI-{suffix}",
            "forme": "pm",
            "rccm": f"RCCM-SUIVI-{suffix}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
        },
    )
    assert r.status_code == 200, r.text
    cid = int(r.json()["id"])

    # Fiche sans mission : compteurs présents et à zéro.
    det0 = client.get(f"/api/v1/contribuables/{cid}", headers=h)
    assert det0.status_code == 200, det0.text
    assert det0.json()["items_en_attente"] == 0
    assert det0.json()["items_a_relancer"] == 0

    mid = _mission(session, tid, cid)
    # 2 en attente (1 relance échue, 1 relance future), 1 reçu.
    _suivi(session, tid, mid, "analytique:7011", "en_attente", "2020-01-15")
    _suivi(session, tid, mid, "analytique:6222", "en_attente", "2999-12-31")
    _suivi(session, tid, mid, "analytique:6011", "recu")
    # Mission clôturée : items EXCLUS de l'agrégat.
    mid_clot = _mission(session, tid, cid, statut="cloturee")
    _suivi(session, tid, mid_clot, "analytique:7012", "en_attente", "2020-01-15")
    session.commit()

    det = client.get(f"/api/v1/contribuables/{cid}", headers=h)
    assert det.status_code == 200, det.text
    fiche = det.json()
    assert fiche["items_en_attente"] == 2
    assert fiche["items_a_relancer"] == 1
