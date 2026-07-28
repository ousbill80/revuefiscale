"""Échéances fiscales à venir au niveau cabinet — vue transverse."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.echeances_cabinet import (
    FENETRE_JOURS,
    PLAFOND_ITEMS,
    PLAFOND_MISSIONS,
    SEUIL_SEMAINE_JOURS,
    echeances_cabinet,
    filtrer_fenetre,
    fusionner_echeances,
    synthese_echeances,
    trier_echeances,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _echeance(date_limite: str, impot: str = "TVA") -> dict:
    return {
        "impot": impot,
        "obligation": f"Obligation {impot}",
        "periode": "mai 2025",
        "date_limite": date_limite,
    }


def test_filtrer_fenetre_bornes_incluses_et_jours_restants():
    aujourd_hui = date(2025, 6, 10)
    echeances = [
        _echeance("2025-06-09"),  # Hier — exclue.
        _echeance("2025-06-10"),  # Aujourd'hui — incluse (borne).
        _echeance("2025-06-15"),
        _echeance("2025-07-10"),  # J+30 — incluse (borne).
        _echeance("2025-07-11"),  # J+31 — exclue.
    ]
    out = filtrer_fenetre(echeances, aujourd_hui)
    assert [e["date_limite"] for e in out] == [
        "2025-06-10",
        "2025-06-15",
        "2025-07-10",
    ]
    assert [e["jours_restants"] for e in out] == [0, 5, 30]
    assert FENETRE_JOURS == 30


def test_filtrer_fenetre_date_illisible_ignoree():
    out = filtrer_fenetre(
        [_echeance("pas-une-date"), _echeance("2025-06-12")],
        date(2025, 6, 10),
    )
    assert len(out) == 1
    assert out[0]["date_limite"] == "2025-06-12"


def _item(
    date_limite: str,
    client: str = "SA Alpha FICTIVE",
    mission_id: int = 1,
    jours_restants: int = 0,
    impot: str = "TVA",
) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "exercice": 2025,
        "impot": impot,
        "obligation": f"Obligation {impot}",
        "periode": "mai 2025",
        "date_limite": date_limite,
        "jours_restants": jours_restants,
    }


def test_tri_par_date_puis_client_puis_impot():
    items = [
        _item("2025-06-20", client="SARL Zêta FICTIVE", mission_id=5),
        _item("2025-06-15", client="SARL Zêta FICTIVE", mission_id=5),
        _item("2025-06-15", client="SA Alpha FICTIVE", impot="TVA"),
        _item("2025-06-15", client="SA Alpha FICTIVE", impot="ITS"),
    ]
    tries = trier_echeances(items)
    assert [(i["date_limite"], i["client"], i["impot"]) for i in tries] == [
        ("2025-06-15", "SA Alpha FICTIVE", "ITS"),
        ("2025-06-15", "SA Alpha FICTIVE", "TVA"),
        ("2025-06-15", "SARL Zêta FICTIVE", "TVA"),
        ("2025-06-20", "SARL Zêta FICTIVE", "TVA"),
    ]


def test_fusionner_echeances_aplati_et_trie():
    par_mission = [
        {
            "client": "SARL Zêta FICTIVE",
            "mission_id": 9,
            "exercice": 2025,
            "echeances": [
                {**_echeance("2025-06-20"), "jours_restants": 10},
            ],
        },
        {
            "client": "SA Alpha FICTIVE",
            "mission_id": 3,
            "exercice": 2024,
            "echeances": [
                {**_echeance("2025-06-15"), "jours_restants": 5},
                {**_echeance("2025-06-25", impot="ITS"), "jours_restants": 15},
            ],
        },
    ]
    out = fusionner_echeances(par_mission)
    assert [(i["client"], i["date_limite"]) for i in out] == [
        ("SA Alpha FICTIVE", "2025-06-15"),
        ("SARL Zêta FICTIVE", "2025-06-20"),
        ("SA Alpha FICTIVE", "2025-06-25"),
    ]
    # Champs homogènes : mission_id/exercice portés sur chaque item.
    assert out[0]["mission_id"] == 3
    assert out[0]["exercice"] == 2024
    assert out[1]["mission_id"] == 9
    assert out[0]["jours_restants"] == 5


def test_fusionner_echeances_plafond():
    par_mission = [
        {
            "client": "SA Alpha FICTIVE",
            "mission_id": 1,
            "exercice": 2025,
            "echeances": [
                {**_echeance(f"2025-{6 + i // 28:02d}-{i % 28 + 1:02d}"),
                 "jours_restants": i}
                for i in range(PLAFOND_ITEMS + 20)
            ],
        }
    ]
    out = fusionner_echeances(par_mission)
    # Le plafond coupe les plus lointaines (tri par date d'abord).
    assert len(out) == PLAFOND_ITEMS
    assert PLAFOND_ITEMS == 100
    assert out[0]["date_limite"] <= out[-1]["date_limite"]


def test_synthese_echeances_compteurs():
    items = [
        _item("2025-06-10", jours_restants=0),
        _item("2025-06-17", jours_restants=7),  # Borne : cette semaine.
        _item("2025-06-18", jours_restants=8, client="SARL Zêta FICTIVE"),
        _item("2025-07-01", jours_restants=21, client="SARL Zêta FICTIVE"),
    ]
    assert synthese_echeances(items) == {
        "total": 4,
        "cette_semaine": 2,
        "clients": 2,
    }
    assert synthese_echeances([]) == {
        "total": 0,
        "cette_semaine": 0,
        "clients": 0,
    }
    assert SEUIL_SEMAINE_JOURS == 7


def test_plafond_missions_constant():
    # Vue de pilotage bornée — un échéancier complet par mission.
    assert PLAFOND_MISSIONS == 50


# ── Tests DB / API ─────────────────────────────────────────────────

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

    lib = f"v-echcab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="echeances-cabinet")
    publier_version(session, lib, "echcab@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Échéances {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission(
    session,
    tenant_id: int,
    denomination: str,
    statut: str = "en_cours",
    exercice: int = 2025,
    regime: str = "reel",
) -> tuple[int, int]:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": denomination},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=exercice,
            profil={"regime": regime, "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return int(mid), int(cid)


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


def test_echeances_fenetre_regime_reel_date_figee(session):
    """Au 10/06/2025, exercice 2025 au réel : TVA + ITS de mai au 15/06."""
    tid, _email = _cabinet(session, "echcab.reel")
    mid, _cid = _mission(session, tid, "SA Fenêtre FICTIVE")
    _mission(session, tid, "SA Cadrage FICTIVE", statut="cadrage")
    _mission(session, tid, "SA Clôturée FICTIVE", statut="cloturee")
    session.commit()

    out = echeances_cabinet(session, tid, date(2025, 6, 10))
    assert out["aujourd_hui"] == "2025-06-10"
    # Seules les échéances de la mission en cours, dans la fenêtre —
    # calendrier COURANT (exercices 2024 et 2025) : solde IS/BIC de
    # l'exercice 2024 puis TVA et ITS de mai 2025, dus le 15/06/2025.
    assert [(i["impot"], i["date_limite"]) for i in out["items"]] == [
        ("IS/BIC", "2025-06-15"),
        ("ITS", "2025-06-15"),
        ("TVA", "2025-06-15"),
    ]
    assert out["items"][0]["periode"] == "exercice 2024"
    item = out["items"][1]
    assert item["mission_id"] == mid
    assert item["client"] == "SA Fenêtre FICTIVE"
    assert item["exercice"] == 2025
    assert item["periode"] == "mai 2025"
    assert item["jours_restants"] == 5
    assert item["obligation"]
    assert out["synthese"] == {
        "total": 3,
        "cette_semaine": 3,
        "clients": 1,
    }
    assert "note" in out


def test_echeances_fusion_multi_clients_et_tri(session):
    """Deux clients (réel + TEE) : fusion triée par date puis client."""
    tid, _email = _cabinet(session, "echcab.multi")
    mid_tee, _cid = _mission(
        session, tid, "Ent. Bêta FICTIVE", regime="tee"
    )
    mid_reel, _cid2 = _mission(session, tid, "SA Alpha FICTIVE")
    session.commit()

    out = echeances_cabinet(session, tid, date(2025, 6, 10))
    # TEE : déclaration de mai due le 10/06 (J0) et de juin le 10/07
    # (J+30, borne incluse) ; réel : solde IS/BIC 2024 + TVA + ITS de
    # mai, dus le 15/06.
    assert [(i["date_limite"], i["client"], i["impot"]) for i in out["items"]] == [
        ("2025-06-10", "Ent. Bêta FICTIVE", "Taxe de l'entreprenant"),
        ("2025-06-15", "SA Alpha FICTIVE", "IS/BIC"),
        ("2025-06-15", "SA Alpha FICTIVE", "ITS"),
        ("2025-06-15", "SA Alpha FICTIVE", "TVA"),
        ("2025-07-10", "Ent. Bêta FICTIVE", "Taxe de l'entreprenant"),
    ]
    assert out["items"][0]["mission_id"] == mid_tee
    assert out["items"][1]["mission_id"] == mid_reel
    assert out["items"][0]["jours_restants"] == 0
    assert out["items"][4]["jours_restants"] == 30
    assert out["synthese"] == {
        "total": 5,
        "cette_semaine": 4,
        "clients": 2,
    }


def test_echeances_tenant_vide(session):
    tid, _email = _cabinet(session, "echcab.vide")
    session.commit()
    out = echeances_cabinet(session, tid, date(2025, 6, 10))
    assert out["items"] == []
    assert out["synthese"] == {
        "total": 0,
        "cette_semaine": 0,
        "clients": 0,
    }
    assert "note" in out


def test_api_echeances_structure_et_coherence(session):
    """La route utilise date.today() : on vérifie structure + cohérence."""
    tid, email = _cabinet(session, "echcab.api")
    _mission(session, tid, "PM API Échéances FICTIF")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/echeances", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["aujourd_hui"] == date.today().isoformat()
    assert "note" in corps
    # Cohérence items/synthese (la fenêtre dépend du jour d'exécution).
    assert corps["synthese"]["total"] == len(corps["items"])
    assert 0 <= corps["synthese"]["cette_semaine"] <= corps["synthese"]["total"]
    assert 0 <= corps["synthese"]["clients"] <= corps["synthese"]["total"]
    for it in corps["items"]:
        assert it["client"] == "PM API Échéances FICTIF"
        assert it["exercice"] == 2025
        assert 0 <= it["jours_restants"] <= 30
        assert it["impot"] and it["obligation"] and it["periode"]
        date.fromisoformat(it["date_limite"])  # ISO valide.
    # Tri par date limite croissante.
    dates = [it["date_limite"] for it in corps["items"]]
    assert dates == sorted(dates)


def test_api_isolation_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "echcab.a")
    _mission(session, tid_a, "PM Isolée Échéances FICTIF")
    _tid_b, email_b = _cabinet(session, "echcab.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/echeances", headers=h)
    assert r.status_code == 200, r.text
    # Le cabinet B ne voit pas les missions du cabinet A.
    assert r.json()["items"] == []
    assert r.json()["synthese"]["total"] == 0


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/echeances")
    assert r.status_code == 401, r.text
