"""Brief du cabinet — assemblage texte des trois rendus cabinet."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.brief_cabinet import (
    MENTION_SECTION_INDISPONIBLE,
    NOTE_BRIEF,
    rendre_brief_texte,
    rendre_portefeuille_texte,
)
from backend.plateforme.portefeuille_declaratif import (
    NOTE_PORTEFEUILLE_DECLARATIF,
    assembler_portefeuille,
)

# ── Corps de démonstration (mêmes clés que les vues cabinet) ───────


def _corps_alertes() -> dict:
    return {
        "aujourd_hui": "2026-07-28",
        "alertes": [
            {
                "gravite": "critique",
                "type": "echeance_fiscale",
                "client": "SA FICTIVE",
                "mission_id": 7,
                "libelle": "TVA — déclaration et paiement (juillet)",
                "echeance": "2026-08-10",
            }
        ],
        "synthese": {"total": 1, "par_type": {"echeance_fiscale": 1}},
        "sources_en_echec": [],
        "note": "note consultative du centre d'alertes",
    }


def _corps_calendrier() -> dict:
    return {
        "aujourd_hui": "2026-07-28",
        "horizon_mois": 3,
        "fin_horizon": "2026-09-30",
        "mois": [
            {
                "mois": "2026-08",
                "libelle_mois": "Août 2026",
                "elements": [
                    {
                        "date": "2026-08-10",
                        "type": "echeance_fiscale",
                        "client": "SA FICTIVE",
                        "mission_id": 7,
                        "libelle": "TVA — déclaration et paiement",
                        "depassee": False,
                    }
                ],
            }
        ],
        "compteurs": {"nb_total": 1, "nb_a_venir": 1, "nb_depassees": 0},
        "sources_en_echec": [],
        "note": "note consultative du calendrier",
    }


def _corps_portefeuille() -> dict:
    vue = {
        "client": "SA FICTIVE",
        "mission_id": 7,
        "exercice": 2026,
        "completude": {
            "disponible": True,
            "exercice": 2026,
            "impots": {
                "tva": {
                    "disponible": True,
                    "nb_saisies": 1,
                    "nb_attendues": 3,
                    "manquantes": ["2026-01", "2026-02"],
                },
                "salaires": {
                    "disponible": True,
                    "nb_saisies": 2,
                    "nb_attendues": 3,
                    "manquantes": ["2026-03"],
                },
            },
        },
    }
    return assembler_portefeuille([vue], date(2026, 7, 28))


def _brief() -> str:
    return rendre_brief_texte(
        _corps_alertes(),
        _corps_calendrier(),
        _corps_portefeuille(),
        aujourd_hui=date(2026, 7, 28),
    )


# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_page_de_garde_et_date_francaise():
    texte = _brief()
    assert "BRIEF DU CABINET" in texte
    assert "Date d'édition : 28/07/2026" in texte
    # La page de garde ouvre le document.
    assert texte.index("BRIEF DU CABINET") < texte.index("Sommaire :")


def test_sommaire_avec_compteurs_cles():
    texte = _brief()
    assert "Sommaire :" in texte
    assert "1. Centre d'alertes — 1 signal(aux)" in texte
    assert "2. Calendrier fiscal — 1 échéance(s) et point(s)" in texte
    assert (
        "3. Portefeuille déclaratif — 1 mission(s), "
        "collecte à organiser : 1"
    ) in texte


def test_trois_sections_rendues_par_les_fonctions_existantes():
    texte = _brief()
    # Les rendus EXISTANTS sont réutilisés tels quels (assemblage).
    assert "CENTRE D'ALERTES DU CABINET" in texte
    assert "CALENDRIER FISCAL DU CABINET" in texte
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in texte
    # Contenus caractéristiques de chaque rendu, ordre de lecture.
    assert "note consultative du centre d'alertes" in texte
    assert "Août 2026 (1)" in texte
    assert texte.index("1. CENTRE D'ALERTES") < texte.index(
        "2. CALENDRIER FISCAL"
    ) < texte.index("3. PORTEFEUILLE DÉCLARATIF")


def test_section_indisponible_si_source_none():
    texte = rendre_brief_texte(
        _corps_alertes(), None, _corps_portefeuille(),
        aujourd_hui=date(2026, 7, 28),
    )
    # Mention douce dans le sommaire ET dans la section — jamais
    # d'exception, les autres sections restent présentées.
    assert "2. Calendrier fiscal — section indisponible ce jour" in texte
    assert MENTION_SECTION_INDISPONIBLE in texte
    assert "CALENDRIER FISCAL DU CABINET" not in texte
    assert "CENTRE D'ALERTES DU CABINET" in texte
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in texte


def test_toutes_sources_indisponibles_document_valide():
    texte = rendre_brief_texte(None, None, None)
    assert "BRIEF DU CABINET" in texte
    assert texte.count(MENTION_SECTION_INDISPONIBLE) == 3
    assert texte.count("section indisponible ce jour") >= 3
    assert NOTE_BRIEF in texte


def test_note_consultative_finale_commune():
    texte = _brief()
    assert NOTE_BRIEF in texte
    # La note commune FERME le brief — l'équipe arbitre en réunion.
    assert texte.rstrip().endswith(NOTE_BRIEF)
    assert "l'équipe" in NOTE_BRIEF


def test_portefeuille_texte_synthese_et_periodes_compactes():
    texte = rendre_portefeuille_texte(_corps_portefeuille())
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in texte
    assert "Date d'édition : 28/07/2026" in texte
    assert (
        "Missions suivies : 1 (à jour : 0, collecte à organiser : 1, "
        "indisponibles : 0)"
    ) in texte
    # Périodes manquantes compactes, en MM/AAAA, mission identifiée.
    assert "SA FICTIVE (exercice 2026)" in texte
    assert "TVA à saisir : 01/2026, 02/2026" in texte
    assert "impôts sur salaires à saisir : 03/2026" in texte
    # Note consultative du portefeuille reprise en pied.
    assert NOTE_PORTEFEUILLE_DECLARATIF in texte


def test_portefeuille_texte_corps_vide_tolerant():
    texte = rendre_portefeuille_texte({})
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in texte
    assert "Aucune période à saisir sur le portefeuille." in texte
    # Corps assemblé sans mission : compteurs à zéro, note présente.
    texte2 = rendre_portefeuille_texte(
        assembler_portefeuille([], date(2026, 7, 28))
    )
    assert "Missions suivies : 0" in texte2
    assert NOTE_PORTEFEUILLE_DECLARATIF in texte2


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_TXT = "/api/v1/cabinet/brief.txt"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-brief-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="brief cabinet")
    publier_version(session, lib, "brief@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"brief.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Brief {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


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


def test_api_txt_200_entetes_et_journal(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="brief-cabinet-{jour}.txt"'
    )
    # Page de garde + les trois sections + note finale commune.
    assert "BRIEF DU CABINET" in r.text
    assert "CENTRE D'ALERTES DU CABINET" in r.text
    assert "CALENDRIER FISCAL DU CABINET" in r.text
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in r.text
    assert NOTE_BRIEF in r.text
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_brief'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    assert lignes[0]["charge_utile"]["format"] == "txt"
    assert lignes[0]["charge_utile"]["sections_indisponibles"] == []


def test_api_source_cassee_mention_douce(session, monkeypatch):
    tid, email = _cabinet(session)
    session.commit()

    # Le centre d'alertes tombe en panne : le brief sort quand même,
    # la section est remplacée par la mention douce.
    import backend.plateforme.centre_alertes as mod_alertes

    def _panne(*args, **kwargs):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(mod_alertes, "centre_alertes_cabinet", _panne)

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert MENTION_SECTION_INDISPONIBLE in r.text
    assert "1. Centre d'alertes — section indisponible ce jour" in r.text
    # Les autres sections restent présentées.
    assert "CALENDRIER FISCAL DU CABINET" in r.text
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in r.text
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_brief'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    assert lignes[0]["charge_utile"]["sections_indisponibles"] == [
        "alertes"
    ]


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_TXT).status_code == 401
