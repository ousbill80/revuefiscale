"""Centre d'alertes in-app du cabinet — agrégat consultatif des signaux."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.centre_alertes import (
    GRAVITES,
    MENTION_NOTE,
    PLAFOND_ALERTES,
    TYPES_ALERTE,
    alertes_depuis_budget,
    alertes_depuis_echeances,
    alertes_depuis_lpf,
    alertes_depuis_points,
    assembler_centre,
    normaliser_alerte,
    plafonner_alertes,
    synthese_alertes,
    trier_alertes,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

JOUR = date(2026, 7, 28)


def test_normaliser_alerte_cles_stables_et_defensif():
    a = normaliser_alerte({})
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["gravite"] == "info"
    assert a["type"] == "info"
    assert a["mission_id"] is None
    assert a["echeance"] is None
    # Gravité et type hors référentiel → « info », jamais bloquant.
    b = normaliser_alerte(
        {"type": "ovni", "gravite": "apocalypse", "mission_id": "7",
         "echeance": "2026-08-01"}
    )
    assert b["gravite"] == "info"
    assert b["type"] == "info"
    assert b["mission_id"] == 7
    assert b["echeance"] == "2026-08-01"


def test_trier_alertes_gravite_puis_echeance():
    items = [
        {"gravite": "info", "echeance": "2026-08-01", "client": "A"},
        {"gravite": "critique", "echeance": None, "client": "B"},
        {"gravite": "critique", "echeance": "2026-07-30", "client": "C"},
        {"gravite": "vigilance", "echeance": "2026-07-29", "client": "D"},
        {"gravite": "critique", "echeance": "2026-07-01", "client": "E"},
    ]
    tri = trier_alertes(items)
    # Critiques d'abord (échéance la plus proche en tête, sans échéance
    # en queue des critiques), puis vigilance, puis info.
    assert [t["client"] for t in tri] == ["E", "C", "B", "D", "A"]


def test_plafonner_alertes():
    items = [{"gravite": "info", "libelle": str(i)} for i in range(150)]
    assert len(plafonner_alertes(items)) == PLAFOND_ALERTES


def test_synthese_alertes_compteurs():
    items = [
        {"type": "point_convenu", "gravite": "critique", "client": "A"},
        {"type": "budget_temps", "gravite": "vigilance", "client": "A"},
        {"type": "echeance_fiscale", "gravite": "info", "client": "B"},
    ]
    s = synthese_alertes(items)
    assert s["total"] == 3
    assert s["par_gravite"] == {"critique": 1, "vigilance": 1, "info": 1}
    assert s["par_type"]["point_convenu"] == 1
    assert s["par_type"]["delai_lpf"] == 0
    assert s["clients"] == 2
    # Toutes les clés du référentiel sont présentes même à zéro.
    assert set(s["par_gravite"]) == set(GRAVITES)
    assert set(s["par_type"]) == set(TYPES_ALERTE)


def test_assembler_centre_vide_cles_stables():
    vue = assembler_centre([], [], JOUR)
    assert set(vue) == {
        "aujourd_hui", "alertes", "synthese", "sources_en_echec", "note",
    }
    assert vue["aujourd_hui"] == "2026-07-28"
    assert vue["alertes"] == []
    assert vue["synthese"]["total"] == 0
    assert vue["sources_en_echec"] == []
    assert vue["note"] == MENTION_NOTE


def test_assembler_centre_sources_en_echec_triees():
    vue = assembler_centre([], ["delais_lpf", "budget_temps"], JOUR)
    assert vue["sources_en_echec"] == ["budget_temps", "delais_lpf"]


def test_alertes_depuis_points_retard_et_anciennete():
    items = [
        {"client": "A", "mission_id": 1, "libelle": "Régulariser ITS",
         "date_cible": "2026-07-01", "en_retard": True,
         "anciennete_jours": 5},
        {"client": "B", "mission_id": 2, "libelle": "Classer AMR",
         "date_cible": None, "en_retard": False, "anciennete_jours": 45},
        {"client": "C", "mission_id": 3, "libelle": "Récent",
         "date_cible": None, "en_retard": False, "anciennete_jours": 3},
    ]
    alertes = alertes_depuis_points(items)
    assert len(alertes) == 2
    assert alertes[0]["gravite"] == "critique"
    assert alertes[0]["type"] == "point_convenu"
    assert alertes[0]["echeance"] == "2026-07-01"
    assert "en retard" in alertes[0]["libelle"]
    assert "Régulariser ITS" in alertes[0]["libelle"]
    assert alertes[1]["gravite"] == "vigilance"
    assert "45 j" in alertes[1]["libelle"]


def test_alertes_depuis_echeances_seuil_semaine():
    items = [
        {"client": "A", "mission_id": 1, "impot": "TVA",
         "obligation": "Déclaration", "date_limite": "2026-07-30",
         "jours_restants": 2},
        {"client": "B", "mission_id": 2, "impot": "BIC",
         "obligation": "Acompte", "date_limite": "2026-08-20",
         "jours_restants": 23},
    ]
    alertes = alertes_depuis_echeances(items)
    assert [a["gravite"] for a in alertes] == ["vigilance", "info"]
    assert alertes[0]["type"] == "echeance_fiscale"
    assert "TVA" in alertes[0]["libelle"]
    assert alertes[0]["echeance"] == "2026-07-30"


def test_alertes_depuis_budget_seuils():
    items = [
        {"client": "A", "mission_id": 1, "seuil": "depassement",
         "pourcentage_consomme": "112.5"},
        {"client": "B", "mission_id": 2, "seuil": "vigilance",
         "pourcentage_consomme": "85.0"},
        {"client": "C", "mission_id": 3, "seuil": "ok",
         "pourcentage_consomme": "10.0"},
    ]
    alertes = alertes_depuis_budget(items)
    assert len(alertes) == 2
    assert alertes[0]["gravite"] == "critique"
    assert "112.5" in alertes[0]["libelle"]
    assert alertes[0]["echeance"] is None
    assert alertes[1]["gravite"] == "vigilance"
    assert alertes[1]["type"] == "budget_temps"


def test_alertes_depuis_lpf_proche_et_depassee():
    from backend.plateforme.controles_fiscaux import construire_chronologie

    chronologie = construire_chronologie(
        [
            # Notification 30 j : échéance 2026-06-30 → dépassée.
            {"id": 1, "type_evenement": "notification_redressement",
             "date_evenement": "2026-05-31"},
            # Mise en demeure 10 j : échéance 2026-08-02 → proche (5 j).
            {"id": 2, "type_evenement": "mise_en_demeure",
             "date_evenement": "2026-07-23"},
            # Avis de vérification : sans délai → aucune alerte.
            {"id": 3, "type_evenement": "avis_verification",
             "date_evenement": "2026-07-01"},
        ],
        JOUR,
    )
    alertes = alertes_depuis_lpf(
        [{"client": "SA FICTIVE", "mission_id": 9,
          "evenements": chronologie}]
    )
    assert len(alertes) == 2
    par_gravite = {a["gravite"]: a for a in alertes}
    assert "dépassé" in par_gravite["critique"]["libelle"]
    assert par_gravite["critique"]["echeance"] == "2026-06-30"
    assert par_gravite["vigilance"]["echeance"] == "2026-08-02"
    assert all(a["type"] == "delai_lpf" for a in alertes)
    assert all(a["lien"] == "controles_fiscaux" for a in alertes)


def test_note_consultative_sans_email():
    assert "consultatif" in MENTION_NOTE
    assert "décide" in MENTION_NOTE
    assert "email" in MENTION_NOTE  # rappel : rien ne part par email


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/alertes"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-alertes-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="centre alertes")
    publier_version(session, lib, "alertes@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alertes.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alertes {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission_en_cours(session, tenant_id: int, nom: str) -> int:
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
    return int(mid)


def _point_en_retard(session, tenant_id: int, mission_id: int) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, date_cible) "
                "VALUES (:t, :m, :lib, CAST(:dc AS DATE))"
            ),
            {"t": tenant_id, "m": mission_id,
             "lib": "Régulariser la TVA de mars", "dc": "2020-01-15"},
        )


def _evenement_lpf_depasse(
    session, tenant_id: int, mission_id: int
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO evenement_controle_fiscal (tenant_id, "
                "mission_id, type_evenement, date_evenement, commentaire) "
                "VALUES (:t, :m, 'notification_redressement', "
                "CAST(:d AS DATE), '')"
            ),
            {"t": tenant_id, "m": mission_id, "d": "2020-02-01"},
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
    assert client.get(URL).status_code == 401


def test_api_structure_stable_et_alertes(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alertes FICTIVE")
    _point_en_retard(session, tid, mid)
    _evenement_lpf_depasse(session, tid, mid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert set(corps) == {
        "aujourd_hui", "alertes", "synthese", "sources_en_echec", "note",
    }
    assert corps["sources_en_echec"] == []
    assert "consultatif" in corps["note"]
    types = {a["type"] for a in corps["alertes"]}
    assert "point_convenu" in types
    assert "delai_lpf" in types
    # Chaque alerte porte le contrat stable.
    for a in corps["alertes"]:
        assert set(a) == {
            "type", "gravite", "client", "mission_id", "libelle",
            "echeance", "lien",
        }
        assert a["gravite"] in ("critique", "vigilance", "info")
    # Tri : les critiques (point en retard, délai LPF dépassé) d'abord.
    gravites = [a["gravite"] for a in corps["alertes"]]
    assert gravites == sorted(
        gravites, key=lambda g: {"critique": 0, "vigilance": 1,
                                 "info": 2}[g]
    )
    assert corps["synthese"]["par_gravite"]["critique"] >= 2
    assert corps["synthese"]["total"] == len(corps["alertes"])


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(URL, headers=h).status_code == 200
    with contexte_tenant(session, tid):
        actions = session.execute(
            text(
                "SELECT action FROM journal_audit "
                "WHERE action = 'consultation_centre_alertes_cabinet'"
            ),
        ).mappings().all()
    assert len(actions) == 1


def test_api_source_en_echec_jamais_bloquante(session, monkeypatch):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Tolerance FICTIVE")
    _point_en_retard(session, tid, mid)
    session.commit()

    import backend.plateforme.echeances_cabinet as ec

    def _boom(*args, **kwargs):
        raise RuntimeError("source échéances indisponible")

    monkeypatch.setattr(ec, "echeances_cabinet", _boom)

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée, les autres alertes restent là.
    assert corps["sources_en_echec"] == ["echeances_fiscales"]
    assert any(
        a["type"] == "point_convenu" for a in corps["alertes"]
    )
    assert corps["note"]
