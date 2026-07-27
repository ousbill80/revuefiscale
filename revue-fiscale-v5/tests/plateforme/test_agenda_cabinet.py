"""Agenda fiscal du cabinet — échéances à venir des missions actives."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.agenda_cabinet import (
    construire_agenda,
    echeances_dans_fenetre,
    synthese_agenda,
)

# ── Tests purs (sans DB, dates figées) ─────────────────────────────


def _mission(
    mission_id: int,
    client: str,
    regime: str = "reel",
    exercice: int = 2025,
    pieces: list | None = None,
) -> dict:
    return {
        "mission_id": mission_id,
        "client": client,
        "exercice": exercice,
        "regime": regime,
        "dge": False,
        "pieces": pieces or [],
    }


def test_fenetre_bornes_incluses_passe_exclu():
    echeances = [
        {"date_limite": "2025-05-31"},  # Hier : hors agenda.
        {"date_limite": "2025-06-01"},  # Jour même : encore actionnable.
        {"date_limite": "2025-07-01"},  # Borne de fin incluse.
        {"date_limite": "2025-07-02"},  # Au-delà de la fenêtre.
    ]
    r = echeances_dans_fenetre(echeances, date(2025, 6, 1), 30)
    assert [e["date_limite"] for e in r] == ["2025-06-01", "2025-07-01"]


def test_fenetre_jours_bornee_1_a_90():
    echeances = [
        {"date_limite": "2025-06-02"},
        {"date_limite": "2025-08-30"},  # J+90.
        {"date_limite": "2025-08-31"},  # J+91 : hors borne max.
    ]
    # jours aberrants → bornés (défensif ; la route valide déjà).
    r_max = echeances_dans_fenetre(echeances, date(2025, 6, 1), 5000)
    assert [e["date_limite"] for e in r_max] == ["2025-06-02", "2025-08-30"]
    r_min = echeances_dans_fenetre(echeances, date(2025, 6, 1), 0)
    assert [e["date_limite"] for e in r_min] == ["2025-06-02"]


def test_agenda_statuts_couverte_et_a_preparer():
    # Fenêtre [01/06, 01/07] 2025, régime réel exercice 2025 :
    # TVA mai (15/06) + ITS mai (15/06) — rien d'autre.
    missions = [
        _mission(
            7,
            "SA Alpha FICTIVE",
            pieces=[
                {
                    "type_piece": "autre",
                    "nom_fichier": "declaration_tva_mai_2025.pdf",
                }
            ],
        )
    ]
    agenda = construire_agenda(missions, date(2025, 6, 1), 30)
    assert [(i["impot"], i["statut"]) for i in agenda] == [
        ("ITS", "a_preparer"),
        ("TVA", "couverte"),
    ]
    item = agenda[1]
    assert item["date_limite"] == "2025-06-15"
    assert item["periode"] == "mai 2025"
    assert item["mission_id"] == 7
    assert item["client"] == "SA Alpha FICTIVE"
    assert item["obligation"]


def test_agenda_trie_par_date_limite_croissante_multi_missions():
    # TEE : échéance du 10/06 ; réel : échéances du 15/06.
    missions = [
        _mission(1, "SA Beta FICTIVE", regime="reel"),
        _mission(2, "Entreprenant Gamma FICTIF", regime="tee"),
    ]
    agenda = construire_agenda(missions, date(2025, 6, 1), 30)
    dates = [i["date_limite"] for i in agenda]
    assert dates == sorted(dates)
    assert agenda[0]["date_limite"] == "2025-06-10"
    assert agenda[0]["mission_id"] == 2
    assert agenda[0]["impot"] == "Taxe de l'entreprenant"
    assert all(i["statut"] == "a_preparer" for i in agenda)


def test_agenda_mission_sans_echeance_dans_la_fenetre_ignoree():
    # Exercice 2020 : plus aucune échéance à venir en 2025.
    missions = [_mission(3, "SARL Ancienne FICTIVE", exercice=2020)]
    assert construire_agenda(missions, date(2025, 6, 1), 30) == []


def test_synthese_agenda():
    items = [
        {"date_limite": "2025-06-10", "statut": "couverte"},
        {"date_limite": "2025-06-15", "statut": "a_preparer"},
        {"date_limite": "2025-06-20", "statut": "a_preparer"},
    ]
    s = synthese_agenda(items)
    assert s == {
        "total": 3,
        "a_preparer": 2,
        "couvertes": 1,
        "prochaine_echeance": "2025-06-15",
    }
    assert synthese_agenda([]) == {
        "total": 0,
        "a_preparer": 0,
        "couvertes": 0,
        "prochaine_echeance": None,
    }


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

    lib = f"v-agenda-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="agenda-cabinet")
    publier_version(session, lib, "agenda@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Agenda {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission_en_cours(session, tenant_id: int, exercice: int) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Agenda FICTIF', 'pm') RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return int(mid)


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


def test_api_agenda_cabinet_missions_actives(session):
    tid, email = _cabinet(session, "agenda")
    # Exercice courant + fenêtre max : au moins une échéance garantie
    # (obligations mensuelles du régime réel), quel que soit le jour.
    mid = _mission_en_cours(session, tid, date.today().year)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/agenda-fiscal?jours=90", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["jours"] == 90
    assert corps["aujourd_hui"] == date.today().isoformat()
    assert corps["missions_actives"] == 1
    assert "note" in corps

    echeances = corps["echeances"]
    assert len(echeances) >= 1
    assert all(e["mission_id"] == mid for e in echeances)
    assert all(e["client"] == "PM Agenda FICTIF" for e in echeances)
    assert all(e["statut"] in {"couverte", "a_preparer"} for e in echeances)
    dates = [e["date_limite"] for e in echeances]
    assert dates == sorted(dates)
    assert all(d >= corps["aujourd_hui"] for d in dates)
    assert all(d <= corps["fenetre_fin"] for d in dates)

    s = corps["synthese"]
    assert s["total"] == len(echeances)
    assert s["couvertes"] + s["a_preparer"] == s["total"]

    # Fenêtre par défaut : 30 jours, réponse bien formée.
    r30 = client.get("/api/v1/cabinet/agenda-fiscal", headers=h)
    assert r30.status_code == 200, r30.text
    assert r30.json()["jours"] == 30


def test_api_jours_hors_bornes_422(session):
    tid, email = _cabinet(session, "agenda.bornes")
    session.commit()
    client, h = _client_connecte(email)
    assert client.get(
        "/api/v1/cabinet/agenda-fiscal?jours=0", headers=h
    ).status_code == 422
    assert client.get(
        "/api/v1/cabinet/agenda-fiscal?jours=91", headers=h
    ).status_code == 422


def test_api_isolation_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "agenda.a")
    mid_a = _mission_en_cours(session, tid_a, date.today().year)
    _tid_b, email_b = _cabinet(session, "agenda.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/agenda-fiscal?jours=90", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # Le cabinet B ne voit ni la mission ni les échéances du cabinet A.
    assert corps["missions_actives"] == 0
    assert corps["echeances"] == []
    assert all(
        e["mission_id"] != mid_a for e in corps["echeances"]
    )


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/agenda-fiscal")
    assert r.status_code == 401, r.text
