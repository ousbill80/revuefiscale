"""Fiche client consolidée — consolidation consultative de l'existant."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.fiche_client import (
    MENTION_NOTE,
    PLAFOND_ALERTES_FICHE,
    assembler_fiche,
    filtrer_alertes_client,
    normaliser_point,
    trier_missions,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

JOUR = date(2026, 7, 28)


def _mission(**surcharge) -> dict:
    base = {"mission_id": 7, "exercice": 2025, "statut": "en_cours"}
    base.update(surcharge)
    return base


def test_trier_missions_exercice_decroissant_puis_id():
    tri = trier_missions([
        _mission(mission_id=1, exercice=2023),
        _mission(mission_id=9, exercice=2025),
        _mission(mission_id=4, exercice=2024),
        _mission(mission_id=6, exercice=2024),
    ])
    assert [(m["exercice"], m["mission_id"]) for m in tri] == [
        (2025, 9), (2024, 6), (2024, 4), (2023, 1),
    ]


def test_normaliser_point_cles_stables_et_depassee():
    p = normaliser_point(
        {
            "point_id": 3,
            "mission_id": 7,
            "exercice": 2025,
            "libelle": "Rassembler les quittances",
            "date_cible": date(2026, 7, 1),
        },
        JOUR,
    )
    assert set(p) == {
        "point_id", "mission_id", "exercice", "libelle",
        "date_cible", "depassee",
    }
    assert p["date_cible"] == "2026-07-01"
    assert p["depassee"] is True
    # Le jour même n'est PAS dépassé (encore actionnable).
    ce_jour = normaliser_point({"point_id": 1, "date_cible": JOUR}, JOUR)
    assert ce_jour["depassee"] is False


def test_normaliser_point_defensif_sans_date_ou_illisible():
    sans = normaliser_point({"point_id": 1, "libelle": "x"}, JOUR)
    assert sans["date_cible"] is None
    assert sans["depassee"] is False
    assert sans["mission_id"] is None
    assert sans["exercice"] is None
    illisible = normaliser_point(
        {"point_id": 2, "date_cible": "pas-une-date"}, JOUR
    )
    assert illisible["date_cible"] is None
    assert illisible["depassee"] is False


def test_filtrer_alertes_client_par_mission_et_par_nom():
    alertes = [
        {"client": "SA FICTIVE", "mission_id": None, "libelle": "a"},
        {"client": "", "mission_id": 7, "libelle": "b"},
        {"client": "AUTRE PM", "mission_id": 99, "libelle": "c"},
        {"client": "", "mission_id": None, "libelle": "d"},
    ]
    retenues = filtrer_alertes_client(alertes, "SA FICTIVE", {7})
    assert [a["libelle"] for a in retenues] == ["a", "b"]
    # Sans dénomination, seul le filtre mission joue (tolérant).
    assert [
        a["libelle"] for a in filtrer_alertes_client(alertes, "", {99})
    ] == ["c"]


def test_filtrer_alertes_client_plafond_et_ordre_conserve():
    alertes = [
        {"client": "SA FICTIVE", "mission_id": 7, "libelle": str(i)}
        for i in range(PLAFOND_ALERTES_FICHE + 15)
    ]
    retenues = filtrer_alertes_client(alertes, "SA FICTIVE", {7})
    assert len(retenues) == PLAFOND_ALERTES_FICHE
    # L'ordre du centre (gravité puis échéance) est conservé tel quel.
    assert [a["libelle"] for a in retenues[:3]] == ["0", "1", "2"]


def _identite() -> dict:
    return {
        "contribuable_id": 5,
        "denomination": "SA FICTIVE",
        "forme": "pm",
    }


def test_assembler_fiche_vide_cles_stables_et_note():
    fiche = assembler_fiche(_identite(), [], [], None, [], [], JOUR)
    assert set(fiche) == {
        "aujourd_hui", "contribuable_id", "denomination", "forme",
        "missions", "points_ouverts", "evolution_charge_fiscale",
        "alertes", "synthese", "volets_en_echec", "note",
    }
    assert fiche["aujourd_hui"] == "2026-07-28"
    assert fiche["contribuable_id"] == 5
    assert fiche["forme"] == "pm"
    assert fiche["missions"] == []
    assert fiche["evolution_charge_fiscale"] is None
    assert fiche["synthese"] == {
        "nb_missions": 0,
        "nb_points_ouverts": 0,
        "nb_points_depasses": 0,
        "nb_alertes": 0,
    }
    assert fiche["note"] == MENTION_NOTE


def test_assembler_fiche_synthese_tri_et_volets_en_echec_tries():
    fiche = assembler_fiche(
        _identite(),
        [_mission(mission_id=1, exercice=2023),
         _mission(mission_id=2, exercice=2025)],
        [
            {"point_id": 1, "depassee": True},
            {"point_id": 2, "depassee": False},
        ],
        {"disponible": False},
        [{"libelle": "x"}],
        ["evolution_charge_fiscale", "alertes"],
        JOUR,
    )
    # Missions triées par exercice décroissant dans la fiche finale.
    assert [m["exercice"] for m in fiche["missions"]] == [2025, 2023]
    assert fiche["synthese"] == {
        "nb_missions": 2,
        "nb_points_ouverts": 2,
        "nb_points_depasses": 1,
        "nb_alertes": 1,
    }
    assert fiche["volets_en_echec"] == ["alertes", "evolution_charge_fiscale"]


def test_note_consultative_sans_recalcul_l_humain_decide():
    assert "consultative" in MENTION_NOTE
    assert "sans" in MENTION_NOTE and "recalcul" in MENTION_NOTE
    assert "décideur" in MENTION_NOTE  # le client reste seul décideur


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _url(contribuable_id: int) -> str:
    return f"/api/v1/contribuables/{contribuable_id}/fiche"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-fcli-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="fiche client")
    publier_version(session, lib, "fcli@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"fcli.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Fiche Client {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _client_avec_mission(
    session, tenant_id: int, nom: str
) -> tuple[int, int]:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": int(mid)},
        )
    return int(cid), int(mid)


def _point_ouvert(
    session, tenant_id: int, mission_id: int, date_cible: str | None
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, date_cible) "
                "VALUES (:t, :m, :lib, CAST(:dc AS DATE))"
            ),
            {"t": tenant_id, "m": mission_id,
             "lib": "Rassembler les quittances d'acomptes",
             "dc": date_cible},
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


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401


def test_api_404_contribuable_inexistant(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(999_999_999), headers=h)
    assert r.status_code == 404
    assert "introuvable" in r.json()["detail"]


def test_api_404_contribuable_hors_tenant(session):
    tid_a, email_a = _cabinet(session)
    tid_b, _ = _cabinet(session)
    cid_b, _mid = _client_avec_mission(
        session, tid_b, "PM Autre Tenant FICTIVE"
    )
    session.commit()

    client, h = _client_connecte(email_a)
    # Le contribuable du tenant B est invisible pour A : 404, pas de fuite.
    assert client.get(_url(cid_b), headers=h).status_code == 404


def test_api_structure_stable_missions_et_points(session):
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM Fiche FICTIVE")
    hier = (date.today() - timedelta(days=1)).isoformat()
    _point_ouvert(session, tid, mid, hier)
    _point_ouvert(session, tid, mid, None)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(cid), headers=h)
    assert r.status_code == 200, r.text
    fiche = r.json()
    assert set(fiche) == {
        "aujourd_hui", "contribuable_id", "denomination", "forme",
        "missions", "points_ouverts", "evolution_charge_fiscale",
        "alertes", "synthese", "volets_en_echec", "note",
    }
    assert fiche["contribuable_id"] == cid
    assert fiche["denomination"] == "PM Fiche FICTIVE"
    assert fiche["forme"] == "pm"
    # Mission du client, statut restitué tel quel.
    assert [
        (m["mission_id"], m["exercice"], m["statut"])
        for m in fiche["missions"]
    ] == [(mid, 2025, "en_cours")]
    # Points ouverts : le daté d'hier est dépassé, le sans-date non.
    assert len(fiche["points_ouverts"]) == 2
    for p in fiche["points_ouverts"]:
        assert set(p) == {
            "point_id", "mission_id", "exercice", "libelle",
            "date_cible", "depassee",
        }
    depasses = [p for p in fiche["points_ouverts"] if p["depassee"]]
    assert len(depasses) == 1
    assert depasses[0]["date_cible"] == hier
    assert fiche["synthese"]["nb_missions"] == 1
    assert fiche["synthese"]["nb_points_ouverts"] == 2
    assert fiche["synthese"]["nb_points_depasses"] == 1
    # Le point en retard remonte aussi comme signal du centre d'alertes.
    assert any(
        a["type"] == "point_convenu" and a["mission_id"] == mid
        for a in fiche["alertes"]
    )
    assert fiche["volets_en_echec"] == []
    assert "consultative" in fiche["note"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid, _mid = _client_avec_mission(session, tid, "PM Journal FICHE")
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(cid), headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'consultation_fiche_client'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    charge = lignes[0]["charge_utile"]
    assert charge["contribuable_id"] == cid
    assert charge["nb_missions"] == 1
    assert charge["volets_en_echec"] == []


def test_api_volet_en_echec_jamais_bloquant(session, monkeypatch):
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM Tolerance FICHE")
    session.commit()

    import backend.plateforme.centre_alertes as ca

    # La disparition de l'assemblée du centre fait échouer TOUT le
    # volet alertes — la fiche doit rester servie malgré tout.
    monkeypatch.delattr(ca, "centre_alertes_cabinet")

    client, h = _client_connecte(email)
    r = client.get(_url(cid), headers=h)
    assert r.status_code == 200, r.text
    fiche = r.json()
    assert fiche["volets_en_echec"] == ["alertes"]
    assert fiche["alertes"] == []
    # Les autres volets restent restitués : la mission est bien là.
    assert [m["mission_id"] for m in fiche["missions"]] == [mid]
    assert fiche["note"]
