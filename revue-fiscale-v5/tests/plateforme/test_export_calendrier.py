"""Export du calendrier fiscal du cabinet — texte français + CSV."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from backend.plateforme.calendrier_cabinet import (
    MENTION_NOTE,
    TYPES_ELEMENT,
    assembler_calendrier,
)
from backend.plateforme.export_calendrier import (
    COLONNES_CSV,
    LIBELLES_TYPE,
    MENTION_DEPASSEE,
    rendre_calendrier_csv,
    rendre_calendrier_texte,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _element(**surcharge) -> dict:
    base = {
        "date": "2026-08-10",
        "type": "echeance_fiscale",
        "client": "SA FICTIVE",
        "mission_id": 7,
        "libelle": "TVA — déclaration et paiement (juillet)",
    }
    base.update(surcharge)
    return base


def _corps(elements: list[dict], **extra) -> dict:
    corps = assembler_calendrier(elements, date(2026, 7, 28))
    corps.update(
        {
            "horizon_mois": 3,
            "fin_horizon": "2026-09-30",
            "sources_en_echec": [],
        }
    )
    corps.update(extra)
    return corps


def test_texte_sections_mensuelles_et_dates_francaises():
    corps = _corps([
        _element(),
        _element(date="2026-09-15", type="point_convenu",
                 client="SARL EXEMPLE", mission_id=9,
                 libelle="point convenu — relancer le client"),
    ])
    texte = rendre_calendrier_texte(corps)
    # En-tête cabinet + date d'édition au format français + horizon.
    assert "CALENDRIER FISCAL DU CABINET" in texte
    assert "Date d'édition : 28/07/2026" in texte
    assert "Horizon : 3 mois (jusqu'au 30/09/2026)" in texte
    # Sections mensuelles en français, ordre chronologique.
    assert texte.index("Août 2026 (1)") < texte.index("Septembre 2026 (1)")
    # Lignes : date FR — [type français] client — libellé.
    assert (
        "10/08/2026 — [Échéance fiscale] SA FICTIVE — "
        "TVA — déclaration et paiement (juillet)"
    ) in texte
    assert (
        "15/09/2026 — [Point convenu] SARL EXEMPLE — "
        "point convenu — relancer le client"
    ) in texte


def test_texte_mention_douce_date_passee():
    corps = _corps([
        _element(date="2026-07-10"),          # antérieure au 28/07
        _element(date="2026-08-10"),          # à venir
    ])
    texte = rendre_calendrier_texte(corps)
    # Formulation douce — constat de calendrier, jamais un reproche.
    assert MENTION_DEPASSEE in texte
    assert texte.count(f"({MENTION_DEPASSEE})") == 1
    ligne_passee = next(
        li for li in texte.splitlines() if "10/07/2026" in li
    )
    assert ligne_passee.endswith(f"({MENTION_DEPASSEE})")


def test_texte_compteurs():
    corps = _corps([_element(date="2026-07-10"), _element(), _element(
        date="2026-09-15", type="point_convenu", mission_id=9,
        libelle="point convenu",
    )])
    texte = rendre_calendrier_texte(corps)
    assert (
        "Échéances et points sur l'horizon : 3 "
        "(à venir : 2, dates déjà passées : 1)"
    ) in texte


def test_texte_note_consultative_en_pied():
    texte = rendre_calendrier_texte(_corps([_element()]))
    assert MENTION_NOTE in texte
    # La note ferme le document — rien après elle.
    assert texte.rstrip().endswith(MENTION_NOTE)


def test_texte_sources_en_echec_signalees():
    texte = rendre_calendrier_texte(
        _corps([_element()], sources_en_echec=["echeances_fiscales"])
    )
    assert (
        "Sources momentanément indisponibles : echeances_fiscales"
    ) in texte
    assert "le reste du calendrier reste présenté" in texte
    # Sans échec : aucune mention.
    sans = rendre_calendrier_texte(_corps([_element()]))
    assert "momentanément indisponibles" not in sans


def test_texte_corps_vide_tolerant():
    # Corps entièrement vide (défensif) : document valide quand même.
    texte = rendre_calendrier_texte({})
    assert "CALENDRIER FISCAL DU CABINET" in texte
    assert "Échéances et points sur l'horizon : 0" in texte
    assert "Aucune échéance sur l'horizon choisi." in texte
    # Corps assemblé sans élément : compteurs à zéro, note présente.
    texte2 = rendre_calendrier_texte(_corps([]))
    assert "(à venir : 0, dates déjà passées : 0)" in texte2
    assert MENTION_NOTE in texte2


def test_csv_en_tete_bom_et_point_virgule():
    contenu = rendre_calendrier_csv(_corps([_element()]))
    # BOM UTF-8 en tête — Excel FR reconnaît l'encodage.
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(COLONNES_CSV)
    assert lignes[0] == "mois;date;type;client;mission;libelle;depassee"
    # Ligne de données : mois AAAA-MM, libellé français du type.
    assert lignes[1] == (
        "2026-08;2026-08-10;Échéance fiscale;SA FICTIVE;7;"
        "TVA — déclaration et paiement (juillet);non"
    )


def test_csv_depassee_oui_non():
    contenu = rendre_calendrier_csv(
        _corps([_element(date="2026-07-10"), _element(date="2026-08-10")])
    )
    lecteur = csv.reader(
        io.StringIO(contenu.lstrip("\ufeff")), delimiter=";"
    )
    lignes = list(lecteur)
    par_date = {li[1]: li[6] for li in lignes[1:]}
    assert par_date == {"2026-07-10": "oui", "2026-08-10": "non"}


def test_csv_echappement_point_virgule_et_guillemets():
    piege = 'écart "notable" ; à examiner'
    contenu = rendre_calendrier_csv(_corps([_element(libelle=piege)]))
    # Relecture stdlib : la valeur revient INTACTE malgré « ; » et « " ».
    lecteur = csv.reader(
        io.StringIO(contenu.lstrip("\ufeff")), delimiter=";"
    )
    lignes = list(lecteur)
    assert lignes[0] == list(COLONNES_CSV)
    assert lignes[1][5] == piege


def test_csv_corps_vide_en_tete_seule():
    contenu = rendre_calendrier_csv({})
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes == [";".join(COLONNES_CSV)]


def test_libelles_types_couvrent_le_referentiel():
    # Chaque type émis par le calendrier a son libellé français.
    assert set(LIBELLES_TYPE) == set(TYPES_ELEMENT)


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_JSON = "/api/v1/cabinet/calendrier"
URL_TXT = "/api/v1/cabinet/calendrier.txt"
URL_CSV = "/api/v1/cabinet/calendrier.csv"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-expcal-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="export calendrier")
    publier_version(session, lib, "expcal@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"expcal.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Expcal {email}",
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


def test_api_txt_200_entetes_et_contenu(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    dispo = r.headers["content-disposition"]
    # Nom de fichier daté (date ISO du jour côté serveur).
    jour = date.today().isoformat()
    assert dispo == (
        f'attachment; filename="calendrier-cabinet-{jour}.txt"'
    )
    assert "CALENDRIER FISCAL DU CABINET" in r.text
    assert MENTION_NOTE in r.text


def test_api_csv_200_entetes_bom_et_colonnes(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_CSV, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="calendrier-cabinet-{jour}.csv"'
    )
    assert r.text.startswith("\ufeff")
    premiere = r.text.lstrip("\ufeff").splitlines()[0]
    assert premiere == "mois;date;type;client;mission;libelle;depassee"


def test_api_horizon_transmis_et_journalise(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, params={"horizon_mois": 6}, headers=h)
    assert r.status_code == 200, r.text
    # L'horizon demandé se lit dans le document texte lui-même.
    assert "Horizon : 6 mois" in r.text
    assert client.get(
        URL_CSV, params={"horizon_mois": 6}, headers=h
    ).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_calendrier'"
            ),
        ).mappings().all()
    assert len(lignes) == 2
    formats = {ligne["charge_utile"]["format"] for ligne in lignes}
    assert formats == {"txt", "csv"}
    assert all(
        ligne["charge_utile"]["horizon_mois"] == 6 for ligne in lignes
    )


def test_api_coherence_avec_calendrier_json(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(URL_JSON, headers=h).json()
    csv_texte = client.get(URL_CSV, headers=h).text
    lignes = csv_texte.lstrip("\ufeff").splitlines()
    # Même assemblage : autant de lignes CSV que d'éléments JSON.
    nb_elements = sum(len(m["elements"]) for m in corps["mois"])
    assert len(lignes) - 1 == nb_elements
    texte = client.get(URL_TXT, headers=h).text
    # Même note consultative que la vue JSON.
    assert corps["note"] in texte


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_TXT).status_code == 401
    assert client.get(URL_CSV).status_code == 401
