"""Relance effectuée / report de relance sur un item du suivi de demande."""
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

    lib = f"v-relitem-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="relance-item")
    publier_version(session, lib, "relitem@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"relitem.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RelItem {email}",
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
                "VALUES (:t, 'PM RelItem FICTIF', 'pm') RETURNING id"
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


def _preparer_item_planifie(client, h, mid: int) -> dict:
    """Crée des items « en_attente » et planifie une relance ; renvoie
    le premier item en attente (avec date_relance)."""
    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["crees"] > 0
    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    p = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/planifier-relances",
        headers=h,
        json={"date_relance": demain},
    )
    assert p.status_code == 200, p.text
    items = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()["items"]
    en_attente = [
        i for i in items if i["statut"] == "en_attente" and i["date_relance"]
    ]
    assert en_attente
    return en_attente[0]


def _url(mid: int, cle: str, action: str) -> str:
    from urllib.parse import quote

    return (
        f"/api/v1/missions/{mid}/suivi-renseignements/"
        f"{quote(cle, safe='')}/{action}"
    )


def test_api_relance_effectuee_trace_et_efface_la_date(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    item = _preparer_item_planifie(client, h, mid)

    r = client.post(_url(mid, item["cle_item"], "relance-effectuee"), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()["item"]
    assert corps["statut"] == "en_attente"
    assert corps["date_relance"] is None
    assert corps["derniere_relance_le"] == datetime.date.today().isoformat()
    assert corps["nb_relances"] == 1

    # Seconde relance : le compteur s'incrémente.
    r2 = client.post(
        _url(mid, item["cle_item"], "relance-effectuee"), headers=h
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["item"]["nb_relances"] == 2

    # La liste fusionnée expose la trace.
    apres = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()["items"]
    par_cle = {i["cle_item"]: i for i in apres}
    assert par_cle[item["cle_item"]]["nb_relances"] == 2
    assert par_cle[item["cle_item"]]["date_relance"] is None


def test_api_reporter_relance_ok(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    item = _preparer_item_planifie(client, h, mid)

    dans_10_jours = (
        datetime.date.today() + datetime.timedelta(days=10)
    ).isoformat()
    r = client.post(
        _url(mid, item["cle_item"], "reporter"),
        headers=h,
        json={"date_relance": dans_10_jours},
    )
    assert r.status_code == 200, r.text
    corps = r.json()["item"]
    assert corps["statut"] == "en_attente"
    assert corps["date_relance"] == dans_10_jours


def test_api_reporter_422_date_passee(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    item = _preparer_item_planifie(client, h, mid)

    hier = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    r = client.post(
        _url(mid, item["cle_item"], "reporter"),
        headers=h,
        json={"date_relance": hier},
    )
    assert r.status_code == 422, r.text
    assert "passée" in r.json()["detail"]


def test_api_409_mission_cloturee(session):
    tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    item = _preparer_item_planifie(client, h, mid)

    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r1 = client.post(
        _url(mid, item["cle_item"], "relance-effectuee"), headers=h
    )
    assert r1.status_code == 409, r1.text
    assert "clôturée" in r1.json()["detail"]
    r2 = client.post(
        _url(mid, item["cle_item"], "reporter"),
        headers=h,
        json={"date_relance": demain},
    )
    assert r2.status_code == 409, r2.text
    assert "clôturée" in r2.json()["detail"]


def test_api_409_item_deja_recu(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    item = _preparer_item_planifie(client, h, mid)

    patch = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/{item['cle_item']}",
        headers=h,
        json={"statut": "recu"},
    )
    assert patch.status_code == 200, patch.text

    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r1 = client.post(
        _url(mid, item["cle_item"], "relance-effectuee"), headers=h
    )
    assert r1.status_code == 409, r1.text
    assert "recu" in r1.json()["detail"]
    r2 = client.post(
        _url(mid, item["cle_item"], "reporter"),
        headers=h,
        json={"date_relance": demain},
    )
    assert r2.status_code == 409, r2.text


def test_api_404_item_inconnu(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid, "civisme:inexistant|x|2025-01-01", "relance-effectuee"),
        headers=h,
    )
    assert r.status_code == 404, r.text
    assert "inconnu" in r.json()["detail"]


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, email_a = _mission_en_cours(session)
    session.commit()
    client_a, h_a = _client_connecte(email_a)
    item = _preparer_item_planifie(client_a, h_a, mid_a)

    _assurer_version(session)
    email_b = f"relitem.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab RelItem B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r1 = client_b.post(
        _url(mid_a, item["cle_item"], "relance-effectuee"), headers=h_b
    )
    assert r1.status_code == 404, r1.text
    r2 = client_b.post(
        _url(mid_a, item["cle_item"], "reporter"),
        headers=h_b,
        json={"date_relance": demain},
    )
    assert r2.status_code == 404, r2.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r1 = client.post(_url(1, "analytique:achats", "relance-effectuee"))
    assert r1.status_code == 401, r1.text
    r2 = client.post(
        _url(1, "analytique:achats", "reporter"),
        json={"date_relance": datetime.date.today().isoformat()},
    )
    assert r2.status_code == 401, r2.text
