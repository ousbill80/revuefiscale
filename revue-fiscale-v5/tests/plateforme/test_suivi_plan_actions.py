"""Suivi du plan d'actions — décision humaine (retenue/écartée/faite)."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.plan_actions import (
    DECISIONS,
    deriver_plan,
    fusionner_decisions,
    synthese_decisions,
    synthese_plan,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

_JOUR = date(2026, 7, 1)


def _risque(rid: int, **kw) -> dict:
    base = {
        "id": rid,
        "libelle": f"Risque {rid}",
        "impot": "TVA",
        "exercice_origine": 2025,
        "statut": "ouvert",
        "probabilite": "possible",
        "montant_estime": None,
        "penalites_estimees": None,
    }
    base.update(kw)
    return base


def test_cle_action_stable_et_decision_nulle_par_defaut():
    plan = deriver_plan([_risque(7)], _JOUR)
    assert plan[0]["cle_action"] == "risque:7"
    assert plan[0]["decision"] is None
    assert plan[0]["decision_note"] is None
    assert plan[0]["decision_maj_le"] is None


def test_fusionner_decisions_recopie_et_ignore_cles_orphelines():
    plan = deriver_plan([_risque(1), _risque(2)], _JOUR)
    fusion = fusionner_decisions(
        plan,
        {
            "risque:1": {"decision": "retenue", "note": "à faire", "maj_le": None},
            "risque:999": {"decision": "faite", "note": None, "maj_le": None},
        },
    )
    par_cle = {i["cle_action"]: i for i in fusion}
    assert par_cle["risque:1"]["decision"] == "retenue"
    assert par_cle["risque:1"]["decision_note"] == "à faire"
    assert par_cle["risque:2"]["decision"] is None
    # La clé orpheline (risque clos depuis) n'ajoute aucun item.
    assert set(par_cle) == {"risque:1", "risque:2"}


def test_synthese_decisions_compteurs():
    plan = deriver_plan([_risque(i) for i in (1, 2, 3, 4)], _JOUR)
    fusionner_decisions(
        plan,
        {
            "risque:1": {"decision": "retenue", "note": None, "maj_le": None},
            "risque:2": {"decision": "ecartee", "note": None, "maj_le": None},
            "risque:3": {"decision": "faite", "note": None, "maj_le": None},
        },
    )
    s = synthese_decisions(plan)
    assert s == {
        "retenues": 1,
        "ecartees": 1,
        "faites": 1,
        "sans_decision": 1,
    }
    # La synthèse du plan expose les mêmes compteurs.
    assert synthese_plan(plan)["decisions"] == s


def test_decisions_connues():
    assert DECISIONS == ("retenue", "ecartee", "faite")


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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-suivi-plan-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="suivi-plan-actions")
    publier_version(session, lib, "suivi.plan@test.ci")


def _mission_en_cours(session) -> tuple[int, int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"suivi.plan.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Suivi Plan {email}",
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
                "VALUES (:t, 'PM Suivi Plan FICTIF', 'pm') RETURNING id"
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
    return r.tenant_id, int(mid), int(cid), email


def _creer_risque(
    session, tenant_id: int, contribuable_id: int, *, montant: str | None = None
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                    "libelle, montant_estime, probabilite, statut, "
                    "exercice_origine) VALUES (:t, :c, 'TVA', :lib, :mt, "
                    "'possible', 'ouvert', 2025) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "lib": f"Risque suivi {uuid.uuid4().hex[:6]}",
                    "mt": montant,
                },
            ).scalar_one()
        )


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


def _url_decision(mid: int, cle: str) -> str:
    return f"/api/v1/missions/{mid}/plan-actions/{cle}/decision"


def test_api_decision_ok_puis_upsert(session):
    tid, mid, cid, email = _mission_en_cours(session)
    rid = _creer_risque(session, tid, cid, montant="150000")
    session.commit()

    client, h = _client_connecte(email)
    cle = f"risque:{rid}"

    r = client.post(
        _url_decision(mid, cle),
        headers=h,
        json={"decision": "retenue", "note": "à régulariser avant clôture"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["action"]["cle_action"] == cle
    assert corps["action"]["decision"] == "retenue"
    assert corps["action"]["decision_note"] == "à régulariser avant clôture"
    assert corps["action"]["decision_maj_le"] is not None
    assert corps["synthese"]["decisions"] == {
        "retenues": 1,
        "ecartees": 0,
        "faites": 0,
        "sans_decision": 0,
    }

    # UPSERT : une nouvelle décision remplace la précédente.
    r2 = client.post(
        _url_decision(mid, cle), headers=h, json={"decision": "faite"}
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["action"]["decision"] == "faite"
    assert r2.json()["action"]["decision_note"] is None
    assert r2.json()["synthese"]["decisions"]["faites"] == 1
    assert r2.json()["synthese"]["decisions"]["retenues"] == 0

    # Le GET plan-actions expose la décision fusionnée + la synthèse.
    g = client.get(f"/api/v1/missions/{mid}/plan-actions", headers=h)
    assert g.status_code == 200, g.text
    plan = g.json()["plan"]
    par_cle = {i["cle_action"]: i for i in plan}
    assert par_cle[cle]["decision"] == "faite"
    assert g.json()["synthese"]["decisions"]["faites"] == 1


def test_api_422_decision_invalide(session):
    tid, mid, cid, email = _mission_en_cours(session)
    rid = _creer_risque(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url_decision(mid, f"risque:{rid}"),
        headers=h,
        json={"decision": "peut_etre"},
    )
    assert r.status_code == 422, r.text
    assert "invalide" in r.json()["detail"]


def test_api_404_cle_action_inconnue(session):
    _tid, mid, _cid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url_decision(mid, "risque:999999"),
        headers=h,
        json={"decision": "retenue"},
    )
    assert r.status_code == 404, r.text
    assert "inconnue" in r.json()["detail"]


def test_api_409_mission_cloturee(session):
    tid, mid, cid, email = _mission_en_cours(session)
    rid = _creer_risque(session, tid, cid)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url_decision(mid, f"risque:{rid}"),
        headers=h,
        json={"decision": "retenue"},
    )
    assert r.status_code == 409, r.text
    assert "clôturée" in r.json()["detail"]


def test_api_404_cross_tenant(session):
    tid_a, mid_a, cid_a, _email_a = _mission_en_cours(session)
    rid_a = _creer_risque(session, tid_a, cid_a)

    _assurer_version(session)
    email_b = f"suivi.plan.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Suivi Plan B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    r = client_b.post(
        _url_decision(mid_a, f"risque:{rid_a}"),
        headers=h_b,
        json={"decision": "retenue"},
    )
    assert r.status_code == 404, r.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.post(
        _url_decision(1, "risque:1"), json={"decision": "retenue"}
    )
    assert r.status_code == 401, r.text
