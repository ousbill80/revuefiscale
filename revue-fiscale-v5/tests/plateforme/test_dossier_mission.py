"""Dossier de synthèse imprimable de la mission — agrégat lecture seule."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    MENTION_NOTE,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_assembler_dossier_blocs_complets():
    blocs = {cle: {"x": cle} for cle in BLOCS_DOSSIER}
    dossier = assembler_dossier(blocs, genere_le="2026-07-28T10:00:00+00:00")
    for cle in BLOCS_DOSSIER:
        assert dossier[cle] == {"x": cle}
    assert dossier["blocs_disponibles"] == len(BLOCS_DOSSIER)
    assert dossier["genere_le"] == "2026-07-28T10:00:00+00:00"
    assert dossier["note"] == MENTION_NOTE


def test_assembler_dossier_tolere_bloc_manquant_ou_invalide():
    # Seule l'identité est fournie ; un bloc non-dict est neutralisé.
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "risques": "n/a", "civisme": None}
    )
    assert dossier["identite"] == {"mission_id": 1}
    # Toutes les clés existent toujours — bloc absent → None.
    for cle in BLOCS_DOSSIER:
        assert cle in dossier
    assert dossier["risques"] is None
    assert dossier["civisme"] is None
    assert dossier["compte_rendu"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_note_et_horodatage_par_defaut():
    dossier = assembler_dossier({})
    assert dossier["blocs_disponibles"] == 0
    # Horodatage ISO généré par défaut (UTC).
    assert "T" in dossier["genere_le"]
    assert dossier["note"] == MENTION_NOTE
    assert "consultatif" in dossier["note"]
    assert "avis fiscal" in dossier["note"]


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-dossier-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-mission")
    publier_version(session, lib, "dossier@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Dossier FICTIF', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return r.tenant_id, int(mid), email


def _client_connecte(email: str):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}


def test_api_dossier_blocs_presents(session):
    from backend.plateforme.compte_rendu import enregistrer_compte_rendu
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, mid, email = _mission_en_cours(session)
    creer_point_convenu(
        session,
        tid,
        mid,
        "Régulariser la TVA de mars",
        "dossier@test.ci",
        date_cible="2025-06-30",
    )
    enregistrer_compte_rendu(
        session,
        tid,
        mid,
        date_reunion="2026-01-15",
        participants="M. Kouassi (DG)\nMme Traoré (cabinet)",
        points_convenus="Dépôt d'une déclaration rectificative TVA.",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Toutes les clés de blocs existent (tolérance : jamais absentes).
    for cle in BLOCS_DOSSIER:
        assert cle in corps

    ident = corps["identite"]
    assert ident["mission_id"] == mid
    assert ident["exercice"] == 2025
    assert ident["statut"] == "en_cours"
    assert ident["contribuable"] == "PM Dossier FICTIF"
    assert ident["regime"] == "reel"
    assert ident["cabinet"].startswith("Cab Dossier")

    # Points convenus : le point créé, avec statut et retard calculé.
    pc = corps["points_convenus"]
    assert pc["synthese"]["a_faire"] == 1
    assert pc["points"][0]["libelle"] == "Régulariser la TVA de mars"
    assert pc["points"][0]["statut"] == "a_faire"
    assert "en_retard" in pc["points"][0]

    # Compte-rendu consigné restitué tel quel.
    cr = corps["compte_rendu"]
    assert cr["date_reunion"] == "2026-01-15"
    assert "rectificative" in cr["points_convenus"]

    # Blocs analytiques présents (mission exploitable : profil complet).
    assert corps["risques"] is not None
    assert corps["risques"]["risques"] == []
    assert corps["civisme"] is not None
    assert corps["civisme"]["taux_civisme"] is not None
    assert corps["completude"] is not None
    assert corps["completude"]["synthese"]["taux_completude"] is not None
    assert corps["delais"] is not None
    assert len(corps["delais"]["jalons"]) == 6

    assert corps["blocs_disponibles"] >= 6
    assert corps["genere_le"]
    assert corps["note"] == MENTION_NOTE

    # Consultation journalisée (pattern historique_client).
    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m AND action = "
                "'consultation_dossier_mission'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) >= 1


def test_api_dossier_sans_compte_rendu_bloc_null(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # Aucun compte-rendu consigné → bloc null, dossier quand même remis.
    assert corps["compte_rendu"] is None
    assert corps["identite"]["mission_id"] == mid
    assert corps["points_convenus"]["points"] == []


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"dossier.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Dossier B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/dossier", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/dossier")
    assert r.status_code == 401, r.text
