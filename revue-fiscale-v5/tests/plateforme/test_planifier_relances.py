"""Planification groupée des relances du suivi de demande de renseignements."""
from __future__ import annotations

import datetime
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

    lib = f"v-planrel-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="planifier-relances")
    publier_version(session, lib, "planrel@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"planrel.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PlanRel {email}",
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
                "VALUES (:t, 'PM PlanRel FICTIF', 'pm') RETURNING id"
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


def _preparer_items(client, h, mid: int) -> list[dict]:
    """Crée des items « en_attente » (passerelle civisme) et les renvoie."""
    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["crees"] > 0
    suivi = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    )
    assert suivi.status_code == 200, suivi.text
    return suivi.json()["items"]


def test_api_planification_items_sans_date(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    items = _preparer_items(client, h, mid)
    en_attente = [i for i in items if i["statut"] == "en_attente"]
    assert len(en_attente) >= 2

    # Un item est déjà planifié individuellement : il ne doit pas bouger.
    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    dans_8_jours = (
        datetime.date.today() + datetime.timedelta(days=8)
    ).isoformat()
    deja = en_attente[0]
    patch = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/{deja['cle_item']}",
        headers=h,
        json={"statut": "en_attente", "date_relance": demain},
    )
    assert patch.status_code == 200, patch.text

    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": dans_8_jours},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["planifiees"] == len(en_attente) - 1
    assert corps["deja_planifiees"] == 1

    apres = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()["items"]
    par_cle = {i["cle_item"]: i for i in apres}
    assert par_cle[deja["cle_item"]]["date_relance"] == demain
    autres = [
        i
        for i in apres
        if i["statut"] == "en_attente" and i["cle_item"] != deja["cle_item"]
    ]
    assert autres and all(i["date_relance"] == dans_8_jours for i in autres)


def test_api_remplacer_ecrase_les_dates(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    items = _preparer_items(client, h, mid)
    en_attente = [i for i in items if i["statut"] == "en_attente"]

    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    dans_15_jours = (
        datetime.date.today() + datetime.timedelta(days=15)
    ).isoformat()
    r1 = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": demain},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["planifiees"] == len(en_attente)

    # Sans remplacer : plus rien à planifier.
    r2 = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": dans_15_jours},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json() == {
        "planifiees": 0,
        "deja_planifiees": len(en_attente),
    }

    # remplacer=True : toutes les dates sont écrasées.
    r3 = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": dans_15_jours, "remplacer": True},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json() == {
        "planifiees": len(en_attente),
        "deja_planifiees": 0,
    }
    apres = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()["items"]
    assert all(
        i["date_relance"] == dans_15_jours
        for i in apres
        if i["statut"] == "en_attente"
    )


def test_api_422_date_passee(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    hier = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": hier},
    )
    assert r.status_code == 422, r.text
    assert "passée" in r.json()["detail"]


def test_api_409_mission_cloturee(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": demain},
    )
    assert r.status_code == 409, r.text
    assert "clôturée" in r.json()["detail"]


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"planrel.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab PlanRel B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = client.post(
        f"/api/v1/missions/{mid_a}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": demain},
    )
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.post(
        "/api/v1/missions/1/suivi-renseignements/planifier-relances",
        json={"date_relance": datetime.date.today().isoformat()},
    )
    assert r.status_code == 401, r.text
