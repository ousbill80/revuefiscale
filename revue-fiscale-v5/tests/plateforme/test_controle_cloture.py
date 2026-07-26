"""Contrôle qualité de pré-clôture — déterministe, consultatif, RLS."""
from __future__ import annotations

import uuid

import pytest

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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-ctrlclot-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="controle-cloture")
    publier_version(session, lib, "ctrlclot@test.ci")


def _mission_en_cours(session) -> tuple[int, int, int]:
    """Provisionne un cabinet + contribuable + mission en cours."""
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"ctrlclot.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CtrlClot {email}",
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
                "VALUES (:t, 'PM CtrlClot FICTIF', 'pm') RETURNING id"
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
    return r.tenant_id, int(mid), int(cid)


def _regle_version_id(session) -> int:
    rv = session.execute(
        text("SELECT id FROM regle_version ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if rv is not None:
        return int(rv)
    vr = session.execute(
        text("SELECT id FROM version_referentiel ORDER BY id DESC LIMIT 1")
    ).scalar_one()
    ident = f"TEST_CTRLCLOT_{uuid.uuid4().hex[:8].upper()}"
    session.execute(
        text(
            "INSERT INTO regle (identifiant, impot, libelle) "
            "VALUES (:i, 'BIC', 'Règle test contrôle clôture')"
        ),
        {"i": ident},
    )
    return int(
        session.execute(
            text(
                "INSERT INTO regle_version (regle_id, version_referentiel_id, "
                "reference_article, reference_source, millesime, date_effet, "
                "nature, condition_declenchement, expression_resultat, "
                "niveau_risque) "
                "VALUES (:r, :v, 'art. test', 'test', 2025, '2025-01-01', "
                "'reintegration', 'true', '0', 'moyen') RETURNING id"
            ),
            {"r": ident, "v": vr},
        ).scalar_one()
    )


def _creer_conclusion(
    session, tenant_id: int, mission_id: int, *, statut: str = "anomalie"
) -> int:
    rv = _regle_version_id(session)
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@ctrlclot') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        return int(
            session.execute(
                text(
                    "INSERT INTO conclusion (tenant_id, execution_id, "
                    "regle_version_id, niveau_risque, statut) "
                    "VALUES (:t, :e, :rv, 'moyen', :st) RETURNING id"
                ),
                {"t": tenant_id, "e": eid, "rv": rv, "st": statut},
            ).scalar_one()
        )


def _creer_risque(
    session,
    tenant_id: int,
    contribuable_id: int,
    *,
    montant: int | None,
    statut: str = "ouvert",
) -> int:
    with contexte_tenant(session, tenant_id):
        if statut == "accepte":
            sql = (
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, exercice_origine, "
                "motif_acceptation, accepte_le, accepte_par) "
                "VALUES (:t, :c, 'TVA', 'Risque test contrôle clôture', "
                ":mt, :st, 2025, 'Accepté pour test', now(), "
                "'assoc@test.ci') RETURNING id"
            )
        else:
            sql = (
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, exercice_origine) "
                "VALUES (:t, :c, 'TVA', 'Risque test contrôle clôture', "
                ":mt, :st, 2025) RETURNING id"
            )
        return int(
            session.execute(
                text(sql),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "mt": montant,
                    "st": statut,
                },
            ).scalar_one()
        )


def _note_disponible(session, tenant_id: int, mission_id: int) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO note_synthese_mission "
                "(tenant_id, mission_id, version, statut, contenu) "
                "VALUES (:t, :m, 1, 'disponible', '{}'::jsonb)"
            ),
            {"t": tenant_id, "m": mission_id},
        )


def _points_par_code(resultat: dict) -> dict[str, dict]:
    return {p["code"]: p for p in resultat["points"]}


def test_risque_ouvert_avec_montant_bloquant(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, cid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="conforme")
    _creer_risque(session, tid, cid, montant=5_000_000, statut="ouvert")

    r = evaluer_cloture(session, tid, mid)
    points = _points_par_code(r)
    assert points["risques_traites"]["statut"] == "bloquant"
    assert "5000000" in points["risques_traites"]["detail"]
    assert r["synthese"]["bloquant"] >= 1
    assert r["cloture_recommandee"] is False


def test_risque_ouvert_sans_montant_attention(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, cid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="conforme")
    _creer_risque(session, tid, cid, montant=None, statut="ouvert")

    r = evaluer_cloture(session, tid, mid)
    points = _points_par_code(r)
    assert points["risques_traites"]["statut"] == "attention"
    # Attention seulement — la clôture reste recommandable sans bloquant.
    assert r["synthese"]["bloquant"] == 0
    assert r["cloture_recommandee"] is True


def test_tout_traite_tous_les_points_ok(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, cid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="conforme")
    _creer_risque(session, tid, cid, montant=1_000_000, statut="accepte")
    _note_disponible(session, tid, mid)

    r = evaluer_cloture(session, tid, mid)
    assert [p["statut"] for p in r["points"]] == ["ok"] * 5
    assert r["synthese"] == {"ok": 5, "attention": 0, "bloquant": 0}
    assert r["cloture_recommandee"] is True


def test_anomalie_sans_suite_attention(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, _ = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="anomalie")

    r = evaluer_cloture(session, tid, mid)
    points = _points_par_code(r)
    assert points["conclusions_instruites"]["statut"] == "attention"
    assert "1 conclusion" in points["conclusions_instruites"]["detail"]


def test_non_verifiable_attention_reponses_client(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, _ = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="non_verifiable")

    r = evaluer_cloture(session, tid, mid)
    points = _points_par_code(r)
    assert points["reponses_client"]["statut"] == "attention"
    assert "1 conclusion" in points["reponses_client"]["detail"]
    assert "demande de renseignements" in points["reponses_client"]["detail"]
    # Aucun bloquant : consultatif, la clôture reste recommandée.
    assert r["cloture_recommandee"] is True


def test_risque_resolu_sans_preuve_attention(session):
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, cid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="conforme")
    _creer_risque(session, tid, cid, montant=100_000, statut="resolu")

    r = evaluer_cloture(session, tid, mid)
    points = _points_par_code(r)
    assert points["pieces_justificatives"]["statut"] == "attention"
    assert "sans preuve" in points["pieces_justificatives"]["detail"]


def test_mission_introuvable(session):
    from backend.plateforme.controle_cloture import (
        ErreurControleCloture,
        evaluer_cloture,
    )

    tid, _, _ = _mission_en_cours(session)
    with pytest.raises(ErreurControleCloture, match="introuvable"):
        evaluer_cloture(session, tid, 99_999_999)


def test_api_cloture_enrichie_du_controle(session):
    """PATCH statut → cloturee joint le résumé consultatif du contrôle."""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"ctrlclot.c.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CtrlClot C {email}",
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
                "VALUES (:t, 'PM CtrlClot C FICTIF', 'pm') RETURNING id"
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
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    # Le contrôle est consultatif via GET, puis joint à la clôture.
    ctrl = client.get(f"/api/v1/missions/{mid}/controle-cloture", headers=h)
    assert ctrl.status_code == 200, ctrl.text
    assert {p["code"] for p in ctrl.json()["points"]} == {
        "conclusions_instruites",
        "risques_traites",
        "note_synthese_presente",
        "reponses_client",
        "pieces_justificatives",
    }

    clot = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert clot.status_code == 200, clot.text
    corps = clot.json()
    assert corps["statut"] == "cloturee"
    resume = corps.get("controle_cloture")
    assert resume is not None
    assert resume["synthese"]["bloquant"] == 0
    assert resume["cloture_recommandee"] is True


def test_api_404_cross_tenant(session):
    """La mission d'un tenant est invisible (404) depuis un autre tenant."""
    from fastapi.testclient import TestClient

    from backend.main import app

    tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"ctrlclot.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab CtrlClot B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email_b, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    r = client.get(f"/api/v1/missions/{mid_a}/controle-cloture", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]
