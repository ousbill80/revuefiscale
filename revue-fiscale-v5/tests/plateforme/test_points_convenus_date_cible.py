"""Date cible optionnelle sur les points convenus + signalement retard."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.points_convenus import (
    ErreurPointConvenuInvalide,
    point_en_retard,
    valider_date_cible,
)
from backend.plateforme.points_convenus_cabinet import (
    ENTETE_POINTS_CSV,
    generer_csv,
    synthese_points_cabinet,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_date_cible_optionnelle():
    assert valider_date_cible(None) is None
    assert valider_date_cible("") is None
    assert valider_date_cible("   ") is None


def test_valider_date_cible_iso_normalisee():
    assert valider_date_cible("2026-08-15") == "2026-08-15"
    assert valider_date_cible("  2026-08-15  ") == "2026-08-15"
    assert valider_date_cible(date(2026, 8, 15)) == "2026-08-15"


def test_valider_date_cible_passee_acceptee():
    # Pas d'exigence de futur : le retard sera signalé, pas bloqué.
    assert valider_date_cible("2020-01-01") == "2020-01-01"


def test_valider_date_cible_invalide_422():
    for mauvaise in (
        "15/08/2026",
        "2026-13-01",
        "2026-02-30",
        "demain",
        "20260815",
        "2026-8-15",
    ):
        with pytest.raises(ErreurPointConvenuInvalide):
            valider_date_cible(mauvaise)


def test_point_en_retard_vrai():
    jour = date(2026, 7, 28)
    assert point_en_retard("a_faire", "2026-07-27", jour) is True
    assert point_en_retard("a_faire", date(2026, 1, 1), jour) is True


def test_point_en_retard_faux():
    jour = date(2026, 7, 28)
    # Date cible du jour même : pas encore en retard.
    assert point_en_retard("a_faire", "2026-07-28", jour) is False
    assert point_en_retard("a_faire", "2026-08-15", jour) is False
    # Sans date cible : jamais en retard.
    assert point_en_retard("a_faire", None, jour) is False
    assert point_en_retard("a_faire", "", jour) is False
    # Statut ≠ a_faire : plus de retard à signaler.
    assert point_en_retard("fait", "2020-01-01", jour) is False
    assert point_en_retard("abandonne", "2020-01-01", jour) is False
    # Défensif : illisible → False, jamais bloquant.
    assert point_en_retard("a_faire", "pas-une-date", jour) is False


def test_synthese_cabinet_compteur_en_retard():
    base = {
        "client": "SA Alpha FICTIVE",
        "anciennete_jours": 0,
    }
    # Compteur toujours présent — 0 sans retard (forme stable).
    assert synthese_points_cabinet([{**base, "en_retard": False}]) == {
        "total": 1,
        "anciens_30j": 0,
        "clients": 1,
        "en_retard": 0,
    }
    s = synthese_points_cabinet(
        [{**base, "en_retard": True}, {**base, "en_retard": False}]
    )
    assert s["en_retard"] == 1
    assert s["total"] == 2


def _item_cab(date_cible: str | None, en_retard: bool = False) -> dict:
    return {
        "client": "SA Alpha FICTIVE",
        "mission_id": 1,
        "exercice": 2025,
        "statut_mission": "en_cours",
        "point_id": 1,
        "libelle": "Régulariser la TVA",
        "date_cible": date_cible,
        "en_retard": en_retard,
        "anciennete_jours": 3,
        "cree_le": "2025-06-01T00:00:00+00:00",
    }


def test_generer_csv_colonne_date_cible_apres_libelle():
    lignes = generer_csv(
        {"items": [_item_cab("2026-08-15")]}
    ).splitlines()
    assert lignes[0] == (
        "anciennete_jours;client;exercice;libelle;date_cible;"
        "statut_mission;cree_le"
    )
    assert lignes[1] == (
        "3;SA Alpha FICTIVE;2025;Régulariser la TVA;2026-08-15;"
        "en_cours;2025-06-01T00:00:00+00:00"
    )


def test_generer_csv_sans_date_cible_cellule_vide():
    # Colonne toujours présente — cellule vide si le point n'a pas de date.
    lignes = generer_csv({"items": [_item_cab(None)]}).splitlines()
    assert lignes[0] == ";".join(ENTETE_POINTS_CSV)
    assert "date_cible" in lignes[0]
    assert lignes[1] == (
        "3;SA Alpha FICTIVE;2025;Régulariser la TVA;;"
        "en_cours;2025-06-01T00:00:00+00:00"
    )


def test_generer_csv_mixte_cellule_vide():
    lignes = generer_csv(
        {"items": [_item_cab("2026-08-15"), _item_cab(None)]}
    ).splitlines()
    assert "date_cible" in lignes[0]
    # Item sans date : cellule vide à la position date_cible.
    assert lignes[2] == (
        "3;SA Alpha FICTIVE;2025;Régulariser la TVA;;"
        "en_cours;2025-06-01T00:00:00+00:00"
    )


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

    lib = f"v-pconvdc-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="points-convenus-date-cible")
    publier_version(session, lib, "pconvdc@test.ci")


def _mission(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"pconvdc.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PConvDC {email}",
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
                "VALUES (:t, 'PM PConvDC FICTIF', 'pm') RETURNING id"
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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/points-convenus"


def test_api_creation_avec_date_cible(session):
    _tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    futur = (date.today() + timedelta(days=15)).isoformat()
    r = client.post(
        _url(mid),
        headers=h,
        json={"libelle": "Régulariser avant le 15", "date_cible": futur},
    )
    assert r.status_code == 200, r.text
    assert r.json()["point"]["date_cible"] == futur

    # Sans date cible : rétro-compatible, date_cible exposée à None.
    r2 = client.post(_url(mid), headers=h, json={"libelle": "Sans date"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["point"]["date_cible"] is None

    g = client.get(_url(mid), headers=h).json()
    par_libelle = {p["libelle"]: p for p in g["points"]}
    assert par_libelle["Régulariser avant le 15"]["date_cible"] == futur
    assert par_libelle["Régulariser avant le 15"]["en_retard"] is False
    assert par_libelle["Sans date"]["en_retard"] is False
    assert g["synthese"]["en_retard"] == 0


def test_api_422_date_cible_invalide(session):
    _tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid),
        headers=h,
        json={"libelle": "Date illisible", "date_cible": "15/08/2026"},
    )
    assert r.status_code == 422, r.text
    assert "date cible" in r.json()["detail"]


def test_api_liste_signale_le_retard(session):
    tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    pid = client.post(
        _url(mid),
        headers=h,
        json={
            "libelle": "Point en retard",
            "date_cible": date.today().isoformat(),
        },
    ).json()["point"]["id"]
    client.post(_url(mid), headers=h, json={"libelle": "Point sans date"})
    # Vieillit la date cible : échéance dépassée depuis 10 jours.
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "UPDATE point_convenu SET date_cible = "
                "CURRENT_DATE - 10 WHERE id = :p"
            ),
            {"p": int(pid)},
        )
    session.commit()

    g = client.get(_url(mid), headers=h).json()
    par_libelle = {p["libelle"]: p for p in g["points"]}
    assert par_libelle["Point en retard"]["en_retard"] is True
    assert par_libelle["Point sans date"]["en_retard"] is False
    assert g["synthese"]["en_retard"] == 1
    assert g["synthese"]["a_faire"] == 2

    # Point marqué « fait » : plus de retard à signaler.
    client.post(
        f"/api/v1/points-convenus/{pid}/statut",
        headers=h,
        json={"statut": "fait"},
    )
    g2 = client.get(_url(mid), headers=h).json()
    assert g2["points"] and all(
        p["en_retard"] is False for p in g2["points"]
    )
    assert g2["synthese"]["en_retard"] == 0


def test_api_cabinet_en_retard_et_csv(session):
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, mid, email = _mission(session)
    r = creer_point_convenu(
        session,
        tid,
        mid,
        "Relance en retard",
        "t@test.ci",
        date_cible=date.today().isoformat(),
    )
    creer_point_convenu(session, tid, mid, "Point sans échéance", "t@test.ci")
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "UPDATE point_convenu SET date_cible = "
                "CURRENT_DATE - 5 WHERE id = :p"
            ),
            {"p": int(r["point"]["id"])},
        )
    session.commit()

    client, h = _client_connecte(email)
    out = client.get("/api/v1/cabinet/points-convenus", headers=h)
    assert out.status_code == 200, out.text
    corps = out.json()
    par_libelle = {i["libelle"]: i for i in corps["items"]}
    retard = par_libelle["Relance en retard"]
    assert retard["en_retard"] is True
    assert retard["date_cible"] == (
        (date.today() - timedelta(days=5)).isoformat()
    )
    assert par_libelle["Point sans échéance"]["en_retard"] is False
    assert par_libelle["Point sans échéance"]["date_cible"] is None
    assert corps["synthese"]["en_retard"] == 1

    csv_r = client.get("/api/v1/cabinet/points-convenus.csv", headers=h)
    assert csv_r.status_code == 200, csv_r.text
    lignes = csv_r.text.lstrip("\ufeff").splitlines()
    assert lignes[0] == (
        "anciennete_jours;client;exercice;libelle;date_cible;"
        "statut_mission;cree_le"
    )
    assert any(
        (date.today() - timedelta(days=5)).isoformat() in ligne
        for ligne in lignes[1:]
    )
