"""Passerelle civisme fiscal → demande de renseignements (items manquants)."""
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

    lib = f"v-civdem-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="civisme-vers-demande")
    publier_version(session, lib, "civdem@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"civdem.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CivDem {email}",
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
                "VALUES (:t, 'PM CivDem FICTIF', 'pm') RETURNING id"
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


def test_api_creation_items_depuis_civisme(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    # Référence : échéances « manquantes » de l'analyse de civisme.
    civisme = client.get(f"/api/v1/missions/{mid}/civisme-fiscal", headers=h)
    assert civisme.status_code == 200, civisme.text
    manquantes = civisme.json()["synthese"]["manquantes"]
    assert manquantes > 0  # exercice 2025 revu en 2026 : échéances passées

    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["total_manquantes"] == manquantes
    assert corps["crees"] == manquantes
    assert corps["ignores_existants"] == 0

    # Les items apparaissent dans le suivi de la demande, statut par
    # défaut « en_attente », libellé clair avec l'échéance.
    suivi = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    )
    assert suivi.status_code == 200, suivi.text
    items = suivi.json()["items"]
    civisme_items = [
        i for i in items if str(i["cle_item"]).startswith("civisme:")
    ]
    assert len(civisme_items) == manquantes
    assert all(i["statut"] == "en_attente" for i in civisme_items)
    assert all("(échéance " in i["libelle"] for i in civisme_items)

    # Un item civisme est pilotable comme les autres (PATCH « recu »).
    cle = civisme_items[0]["cle_item"]
    patch = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/{cle}",
        headers=h,
        json={"statut": "recu"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["item"]["statut"] == "recu"


def test_api_idempotence_second_appel(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r1.status_code == 200, r1.text
    crees = r1.json()["crees"]
    assert crees > 0

    r2 = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r2.status_code == 200, r2.text
    corps = r2.json()
    assert corps["crees"] == 0
    assert corps["ignores_existants"] == crees
    assert corps["total_manquantes"] == r1.json()["total_manquantes"]

    # Aucun doublon dans le suivi.
    suivi = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    )
    libelles = [
        i["libelle"]
        for i in suivi.json()["items"]
        if str(i["cle_item"]).startswith("civisme:")
    ]
    assert len(libelles) == crees
    assert len(set(libelles)) == len(libelles)


def test_api_409_mission_cloturee(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        f"/api/v1/missions/{mid}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r.status_code == 409, r.text
    assert "clôturée" in r.json()["detail"]


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"civdem.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab CivDem B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.post(
        f"/api/v1/missions/{mid_a}/suivi-renseignements/depuis-civisme",
        headers=h,
    )
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.post("/api/v1/missions/1/suivi-renseignements/depuis-civisme")
    assert r.status_code == 401, r.text
