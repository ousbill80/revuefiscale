"""Objectifs multi-mission — domaine abonné (RLS + gel cadrage)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

pytestmark = pytest.mark.db


def _skip_si_migration_absente(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'mission_objectif'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 018 non appliquée — lancez make migrate")


def _creer_contribuable(client: TestClient, h: dict, *, ncc: str) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "dfe": f"DFE-{ncc}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


@pytest.fixture
def client_cabinet(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    _skip_si_migration_absente(session)

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-obj-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="objectifs")
        publier_version(session, lib, "obj@test.ci")

    email = f"obj.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Obj {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    h = {"Authorization": f"Bearer {body['jeton']}"}
    return client, h, int(body["tenant_id"])


def test_objectifs_crud_et_gel_cadrage(session, client_cabinet):
    client, h, _tid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OBJ-0001")

    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "preventive",
            "objectifs": [
                {"libelle": "Revue TVA T4"},
                {"libelle": "Contrôle RAS salaires"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])
    assert len(created.json()["objectifs"]) == 2
    assert created.json()["objectifs"][0]["libelle"] == "Revue TVA T4"

    liste = client.get(f"/api/v1/missions/{mid}/objectifs", headers=h)
    assert liste.status_code == 200
    assert [o["libelle"] for o in liste.json()] == [
        "Revue TVA T4",
        "Contrôle RAS salaires",
    ]

    put = client.put(
        f"/api/v1/missions/{mid}/objectifs",
        headers=h,
        json={
            "objectifs": [
                {"libelle": "Seul objectif restant"},
            ]
        },
    )
    assert put.status_code == 200, put.text
    assert len(put.json()) == 1

    patch = client.patch(
        f"/api/v1/missions/{mid}/cadrage",
        headers=h,
        json={
            "objectifs": [
                {"libelle": "A via cadrage"},
                {"libelle": "B via cadrage"},
            ]
        },
    )
    assert patch.status_code == 200, patch.text
    assert [o["libelle"] for o in patch.json()["objectifs"]] == [
        "A via cadrage",
        "B via cadrage",
    ]

    # Passage en cours → gel
    statut = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "en_cours"},
    )
    assert statut.status_code == 200, statut.text

    refuse = client.put(
        f"/api/v1/missions/{mid}/objectifs",
        headers=h,
        json={"objectifs": [{"libelle": "trop tard"}]},
    )
    assert refuse.status_code == 409, refuse.text


def test_suggestions_objectifs_cabinet(session, client_cabinet):
    """GET /objectifs-mission/suggestions — historique distinct du tenant."""
    client, h, _tid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OBJ-SUGG")
    cid2 = _creer_contribuable(client, h, ncc="CI-OBJ-SUGG-2")

    for lib, contribuable_id, exercice in (
        ("Revue TVA T4", cid, 2025),
        ("Revue TVA T4", cid2, 2025),
        ("Contrôle RAS salaires", cid, 2024),
    ):
        created = client.post(
            "/api/v1/missions",
            headers=h,
            json={
                "contribuable_id": contribuable_id,
                "exercice": exercice,
                "profil": {"regime": "reel", "forme_juridique": "SA"},
                "type_engagement": "preventive",
                "objectifs": [{"libelle": lib}],
            },
        )
        assert created.status_code == 200, created.text

    sugg = client.get(
        "/api/v1/objectifs-mission/suggestions",
        headers=h,
    )
    assert sugg.status_code == 200, sugg.text
    libelles = [r["libelle"] for r in sugg.json()]
    assert "Revue TVA T4" in libelles
    assert "Contrôle RAS salaires" in libelles
    tva = next(r for r in sugg.json() if r["libelle"] == "Revue TVA T4")
    assert int(tva["usage"]) >= 2

    filtre = client.get(
        "/api/v1/objectifs-mission/suggestions",
        headers=h,
        params={"q": "RAS"},
    )
    assert filtre.status_code == 200
    assert all("RAS" in r["libelle"] for r in filtre.json())


def test_objectifs_lecteur_403_ecriture(session, client_cabinet):
    """RBAC : lecteur lit, ne remplace pas."""
    from backend.plateforme.auth import hasher_mot_de_passe

    client, h_admin, tid = client_cabinet
    cid = _creer_contribuable(client, h_admin, ncc="CI-OBJ-LECT")

    created = client.post(
        "/api/v1/missions",
        headers=h_admin,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "objectifs": [{"libelle": "Visible lecteur"}],
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])
    email_lect = f"lect.{uuid.uuid4().hex[:8]}@demo.local"

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'lecteur', :h, true)"
            ),
            {
                "t": tid,
                "e": email_lect,
                "h": hasher_mot_de_passe("lecteur-lect1"),
            },
        )
    session.commit()

    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email_lect, "mot_de_passe": "lecteur-lect1"},
    )
    assert login.status_code == 200, login.text
    h_lect = {"Authorization": f"Bearer {login.json()['jeton']}"}

    ok = client.get(f"/api/v1/missions/{mid}/objectifs", headers=h_lect)
    assert ok.status_code == 200
    assert len(ok.json()) == 1

    forbid = client.put(
        f"/api/v1/missions/{mid}/objectifs",
        headers=h_lect,
        json={"objectifs": [{"libelle": "interdit"}]},
    )
    assert forbid.status_code == 403, forbid.text


def test_objectifs_rls_inter_cabinets(session):
    _skip_si_migration_absente(session)

    a = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab A Obj', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    b = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab B Obj', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()

    # Version référentiel minimale pour FK mission
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )
    from backend.plateforme.provisionnement import derniere_version_publiee

    if derniere_version_publiee(session) is None:
        lib = f"v-obj-rls-{uuid.uuid4().hex[:6]}"
        creer_version_brouillon(session, lib, note="rls")
        publier_version(session, lib, "rls@test.ci")
    vid = derniere_version_publiee(session)
    assert vid is not None

    with contexte_tenant(session, a):
        ca = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client A') RETURNING id"
            ),
            {"t": a},
        ).scalar_one()
        mid = session.execute(
            text(
                "INSERT INTO mission "
                "(tenant_id, contribuable_id, exercice, profil, "
                "version_referentiel_id, statut) "
                "VALUES (:t, :c, 2025, '{}', :v, 'cadrage') RETURNING id"
            ),
            {"t": a, "c": ca, "v": vid},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO mission_objectif "
                "(tenant_id, mission_id, ordre, libelle) "
                "VALUES (:t, :m, 0, 'secret A')"
            ),
            {"t": a, "m": mid},
        )

    with contexte_tenant(session, b):
        n = session.execute(
            text("SELECT count(*) FROM mission_objectif")
        ).scalar_one()
        assert n == 0

    effacer_contexte_tenant(session)
    n0 = session.execute(
        text("SELECT count(*) FROM mission_objectif")
    ).scalar_one()
    assert n0 == 0
