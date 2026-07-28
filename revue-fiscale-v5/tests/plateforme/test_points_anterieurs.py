"""Points en suspens des missions antérieures du même contribuable."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.points_anterieurs import (
    NOTE_POINTS_ANTERIEURS,
    PLAFOND_POINTS,
    marquer_en_retard,
    plafonner_points,
    synthese_anterieurs,
    trier_points,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_tri_exercice_croissant_puis_id():
    points = [
        {"point_id": 9, "exercice": 2024, "mission_id": 2},
        {"point_id": 3, "exercice": 2023, "mission_id": 1},
        {"point_id": 1, "exercice": 2024, "mission_id": 2},
        {"point_id": 7, "exercice": 2022, "mission_id": 5},
    ]
    tries = trier_points(points)
    assert [(p["exercice"], p["point_id"]) for p in tries] == [
        (2022, 7),
        (2023, 3),
        (2024, 1),
        (2024, 9),
    ]


def test_plafond_50_points():
    assert PLAFOND_POINTS == 50
    points = [
        {"point_id": i, "exercice": 2020, "mission_id": 1}
        for i in range(60)
    ]
    plafonnes = plafonner_points(points)
    assert len(plafonnes) == 50
    # Les premiers (plus anciens après tri) sont conservés.
    assert plafonnes[0]["point_id"] == 0
    assert plafonnes[-1]["point_id"] == 49
    assert plafonner_points([]) == []


def test_marquage_en_retard():
    aujourd_hui = date(2026, 7, 28)
    points = [
        {"point_id": 1, "mission_id": 1, "exercice": 2024,
         "date_cible": "2026-01-15"},
        {"point_id": 2, "mission_id": 1, "exercice": 2024,
         "date_cible": "2026-07-28"},  # jour même : pas en retard
        {"point_id": 3, "mission_id": 1, "exercice": 2024,
         "date_cible": None},
    ]
    marques = marquer_en_retard(points, aujourd_hui)
    assert [p["en_retard"] for p in marques] == [True, False, False]
    # Copies : l'entrée d'origine n'est pas mutée.
    assert "en_retard" not in points[0]


def test_synthese_total_retard_missions():
    points = [
        {"point_id": 1, "mission_id": 10, "en_retard": True},
        {"point_id": 2, "mission_id": 10, "en_retard": False},
        {"point_id": 3, "mission_id": 20, "en_retard": True},
    ]
    assert synthese_anterieurs(points) == {
        "total": 3,
        "en_retard": 2,
        "missions": 2,
    }
    assert synthese_anterieurs([]) == {
        "total": 0,
        "en_retard": 0,
        "missions": 0,
    }


def test_note_consultative_mission_origine():
    assert "consultatif" in NOTE_POINTS_ANTERIEURS
    assert "mission" in NOTE_POINTS_ANTERIEURS
    assert "origine" in NOTE_POINTS_ANTERIEURS


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

    lib = f"v-pant-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="points-anterieurs")
    publier_version(session, lib, "pant@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"pant.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PAnt {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _contribuable(session, tenant_id: int, nom: str) -> int:
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
    return int(cid)


def _mission(
    session,
    tenant_id: int,
    contribuable_id: int,
    exercice: int,
    statut: str = "cloturee",
) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return int(mid)


def _point(
    session,
    tenant_id: int,
    mission_id: int,
    libelle: str,
    statut: str = "a_faire",
    date_cible: str | None = None,
) -> int:
    with contexte_tenant(session, tenant_id):
        pid = session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, statut, date_cible) "
                "VALUES (:t, :m, :lib, :s, CAST(:dc AS DATE)) "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "lib": libelle,
                "s": statut,
                "dc": date_cible,
            },
        ).scalar_one()
    return int(pid)


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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/points-anterieurs"


def test_api_mission_2025_voit_points_a_faire_2024(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM PAnt FICTIF")
    mid_2024 = _mission(session, tid, cid, 2024)
    _point(session, tid, mid_2024, "Régulariser la TVA 2024")
    _point(
        session, tid, mid_2024, "Provision congés payés",
        date_cible="2025-01-31",  # passée → en retard
    )
    # Exclus : points traités dans la mission d'origine.
    _point(session, tid, mid_2024, "Point déjà fait", statut="fait")
    _point(
        session, tid, mid_2024, "Point abandonné", statut="abandonne"
    )
    mid_2025 = _mission(session, tid, cid, 2025, statut="en_cours")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid_2025), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid_2025
    assert corps["exercice"] == 2025
    assert [p["libelle"] for p in corps["points"]] == [
        "Régulariser la TVA 2024",
        "Provision congés payés",
    ]
    premier = corps["points"][0]
    assert premier["mission_id"] == mid_2024
    assert premier["exercice"] == 2024
    assert premier["date_cible"] is None
    assert premier["en_retard"] is False
    second = corps["points"][1]
    assert second["date_cible"] == "2025-01-31"
    assert second["en_retard"] is True
    assert corps["synthese"] == {
        "total": 2, "en_retard": 1, "missions": 1
    }
    assert "origine" in corps["note"]


def test_api_exercice_egal_ou_superieur_exclu(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM PAnt Bornes FICTIF")
    mid_2023 = _mission(session, tid, cid, 2023)
    _point(session, tid, mid_2023, "Point 2023")
    mid_2024_bis = _mission(session, tid, cid, 2024)
    _point(session, tid, mid_2024_bis, "Point même exercice")
    mid_2025 = _mission(session, tid, cid, 2025)
    _point(session, tid, mid_2025, "Point exercice supérieur")
    mid_2024 = _mission(session, tid, cid, 2024, statut="en_cours")
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(_url(mid_2024), headers=h).json()
    # Seul l'exercice STRICTEMENT inférieur (2023) apparaît.
    assert [p["libelle"] for p in corps["points"]] == ["Point 2023"]
    assert corps["synthese"]["total"] == 1


def test_api_autre_contribuable_exclu(session):
    tid, email = _cabinet(session)
    cid_a = _contribuable(session, tid, "PM PAnt A FICTIF")
    cid_b = _contribuable(session, tid, "PM PAnt B FICTIF")
    mid_b_2024 = _mission(session, tid, cid_b, 2024)
    _point(session, tid, mid_b_2024, "Point du contribuable B")
    mid_a_2025 = _mission(session, tid, cid_a, 2025, statut="en_cours")
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(_url(mid_a_2025), headers=h).json()
    assert corps["points"] == []
    assert corps["synthese"] == {
        "total": 0, "en_retard": 0, "missions": 0
    }


def test_api_mission_sans_antecedent_liste_vide(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM PAnt Neuf FICTIF")
    mid = _mission(session, tid, cid, 2025, statut="en_cours")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["points"] == []
    assert corps["synthese"]["total"] == 0
    assert "consultatif" in corps["note"]


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM PAnt Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a, 2025, statut="en_cours")
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
