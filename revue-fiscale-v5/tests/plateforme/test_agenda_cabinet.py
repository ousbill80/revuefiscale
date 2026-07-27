"""Agenda fiscal du cabinet — échéances à venir des missions actives."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.agenda_cabinet import (
    construire_agenda,
    echeances_dans_fenetre,
    generer_ics,
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


# ── Tests purs — export iCalendar ──────────────────────────────────


def _echeance_ics(**surcharges) -> dict:
    base = {
        "date_limite": "2025-06-15",
        "impot": "TVA",
        "obligation": "Déclaration mensuelle de TVA",
        "periode": "mai 2025",
        "mission_id": 7,
        "client": "SA Alpha FICTIVE",
        "statut": "a_preparer",
    }
    base.update(surcharges)
    return base


def test_ics_structure_vcalendar_et_un_vevent_par_echeance():
    echeances = [
        _echeance_ics(),
        _echeance_ics(impot="ITS", obligation="Déclaration ITS"),
    ]
    ics = generer_ics(echeances, date(2025, 6, 1))
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in ics
    assert "PRODID:" in ics
    assert ics.count("BEGIN:VEVENT") == 2
    assert ics.count("END:VEVENT") == 2
    assert "DTSTART;VALUE=DATE:20250615" in ics
    assert "DTSTAMP:20250601T000000Z" in ics
    assert "CATEGORIES:a_preparer" in ics
    # Fins de ligne CRLF exclusivement (RFC 5545).
    assert "\n" not in ics.replace("\r\n", "")


def test_ics_vide_reste_valide():
    ics = generer_ics([], date(2025, 6, 1))
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VEVENT" not in ics


def test_ics_echappement_virgules_et_points_virgules():
    ics = generer_ics(
        [
            _echeance_ics(
                client="SARL Un, Deux; Trois FICTIVE",
                obligation="Déclaration, dépôt; paiement",
            )
        ],
        date(2025, 6, 1),
    )
    deplie = ics.replace("\r\n ", "")
    assert "Un\\, Deux\\; Trois" in deplie
    assert "Déclaration\\, dépôt\\; paiement" in deplie
    # DESCRIPTION multi-ligne : retours encodés en « \n » littéral.
    assert "\\n" in deplie


def test_ics_uid_deterministe_et_stable():
    e = _echeance_ics()
    ics_1 = generer_ics([e], date(2025, 6, 1))
    ics_2 = generer_ics([e], date(2025, 6, 1))
    assert ics_1 == ics_2
    deplie = ics_1.replace("\r\n ", "")
    uid = next(
        l for l in deplie.split("\r\n") if l.startswith("UID:")
    )
    assert uid == "UID:7-tva-2025-06-15-declaration-mensuelle-de-tva@revuefiscale"
    # Deux obligations du même impôt à la même date → UID distincts.
    autres = generer_ics(
        [e, _echeance_ics(obligation="Paiement de la TVA")],
        date(2025, 6, 1),
    )
    uids = [
        l
        for l in autres.replace("\r\n ", "").split("\r\n")
        if l.startswith("UID:")
    ]
    assert len(uids) == len(set(uids)) == 2


def test_ics_lignes_pliees_75_octets_max():
    ics = generer_ics(
        [
            _echeance_ics(
                client="Société à dénomination particulièrement longue "
                "pour éprouver le pliage des lignes FICTIVE",
            )
        ],
        date(2025, 6, 1),
    )
    for ligne in ics.split("\r\n"):
        assert len(ligne.encode("utf-8")) <= 75, ligne
    # Le dépliage restitue le résumé complet (aucun octet perdu).
    assert "particulièrement longue" in ics.replace("\r\n ", "")


def test_ics_summary_format():
    ics = generer_ics([_echeance_ics()], date(2025, 6, 1))
    deplie = ics.replace("\r\n ", "")
    assert (
        "SUMMARY:[TVA] Déclaration mensuelle de TVA — SA Alpha FICTIVE"
        in deplie
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


def test_api_agenda_ics_export(session):
    tid, email = _cabinet(session, "agenda.ics")
    mid = _mission_en_cours(session, tid, date.today().year)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/agenda-fiscal.ics?jours=90", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/calendar")
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="agenda-fiscal.ics"'
    )
    corps = r.text
    assert corps.startswith("BEGIN:VCALENDAR")
    assert corps.rstrip("\r\n").endswith("END:VCALENDAR")
    # Au moins un événement (obligations mensuelles du régime réel sur
    # 90 jours) et l'UID référence bien la mission créée.
    assert corps.count("BEGIN:VEVENT") >= 1
    assert f"UID:{mid}-" in corps.replace("\r\n ", "")

    # Cohérence avec l'agenda JSON : autant de VEVENT que d'échéances.
    rj = client.get("/api/v1/cabinet/agenda-fiscal?jours=90", headers=h)
    assert rj.status_code == 200
    assert corps.count("BEGIN:VEVENT") == len(rj.json()["echeances"])


def test_api_agenda_ics_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/agenda-fiscal.ics")
    assert r.status_code == 401, r.text
