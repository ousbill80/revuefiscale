"""Export du centre d'alertes cabinet — texte français + CSV."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from backend.plateforme.centre_alertes import (
    MENTION_NOTE,
    assembler_centre,
)
from backend.plateforme.export_alertes import (
    COLONNES_CSV,
    LIBELLES_TYPE,
    rendre_alertes_csv,
    rendre_alertes_texte,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _alerte(**surcharge) -> dict:
    base = {
        "type": "echeance_fiscale",
        "gravite": "critique",
        "client": "SA FICTIVE",
        "mission_id": 7,
        "libelle": "TVA mensuelle à déposer",
        "echeance": "2026-08-10",
        "lien": "echeances",
    }
    base.update(surcharge)
    return base


def _corps(alertes: list[dict], en_echec: list[str] | None = None) -> dict:
    return assembler_centre(alertes, en_echec or [], date(2026, 7, 28))


def test_texte_groupes_de_gravite_et_libelles_francais():
    corps = _corps([
        _alerte(),
        _alerte(type="budget_temps", gravite="vigilance", echeance=None,
                client="SARL EXEMPLE", libelle="budget temps sous tension"),
        _alerte(type="qualite_balance", gravite="info", echeance=None,
                libelle="sens inhabituel à examiner"),
    ])
    texte = rendre_alertes_texte(corps)
    # En-tête cabinet + date du jour au format français.
    assert "CENTRE D'ALERTES DU CABINET" in texte
    assert "28/07/2026" in texte
    # Les trois groupes de gravité, dans l'ordre critique → info.
    assert texte.index("Critique (1)") < texte.index("Vigilance (1)")
    assert texte.index("Vigilance (1)") < texte.index("Information (1)")
    # Libellés FRANÇAIS des types — jamais les codes techniques bruts.
    assert "[Échéance fiscale]" in texte
    assert "[Budget temps]" in texte
    assert "[Qualité de balance]" in texte
    # Client, libellé et échéance présents.
    assert "SA FICTIVE" in texte
    assert "SARL EXEMPLE" in texte
    assert "(échéance 10/08/2026)" in texte
    # Synthèse par type avec libellés français.
    assert "Synthèse par type :" in texte
    assert "Échéance fiscale : 1" in texte


def test_texte_note_consultative_en_pied():
    texte = rendre_alertes_texte(_corps([_alerte()]))
    assert MENTION_NOTE in texte
    # La note ferme le document — rien après elle.
    assert texte.rstrip().endswith(MENTION_NOTE)


def test_texte_sources_en_echec_signalees():
    texte = rendre_alertes_texte(
        _corps([_alerte()], en_echec=["budget", "lpf"])
    )
    assert "Sources momentanément indisponibles : budget, lpf" in texte
    assert "les autres signaux restent présentés" in texte
    # Sans échec : aucune mention.
    sans = rendre_alertes_texte(_corps([_alerte()]))
    assert "momentanément indisponibles" not in sans


def test_texte_corps_vide_tolerant():
    # Corps entièrement vide (défensif) : document valide quand même.
    texte = rendre_alertes_texte({})
    assert "CENTRE D'ALERTES DU CABINET" in texte
    assert "Signaux à l'attention du cabinet : 0" in texte
    assert "Aucun signal." in texte
    # Corps assemblé sans alerte : les trois groupes vides, la note.
    texte2 = rendre_alertes_texte(_corps([]))
    assert "Critique (0)" in texte2
    assert "Vigilance (0)" in texte2
    assert "Information (0)" in texte2
    assert MENTION_NOTE in texte2


def test_csv_en_tete_bom_et_point_virgule():
    contenu = rendre_alertes_csv(_corps([_alerte()]))
    # BOM UTF-8 en tête — Excel FR reconnaît l'encodage.
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(COLONNES_CSV)
    assert lignes[0] == "gravite;type;client;mission;libelle;echeance"
    # Ligne de données : point-virgule, libellé français du type.
    assert lignes[1] == (
        "critique;Échéance fiscale;SA FICTIVE;7;"
        "TVA mensuelle à déposer;2026-08-10"
    )


def test_csv_echappement_point_virgule_et_guillemets():
    piege = 'écart "notable" ; à examiner'
    contenu = rendre_alertes_csv(
        _corps([_alerte(libelle=piege, echeance=None)])
    )
    # Relecture stdlib : la valeur revient INTACTE malgré « ; » et « " ».
    lecteur = csv.reader(
        io.StringIO(contenu.lstrip("\ufeff")), delimiter=";"
    )
    lignes = list(lecteur)
    assert lignes[0] == list(COLONNES_CSV)
    assert lignes[1][4] == piege
    assert lignes[1][5] == ""  # échéance absente → cellule vide


def test_csv_corps_vide_en_tete_seule():
    contenu = rendre_alertes_csv({})
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes == [";".join(COLONNES_CSV)]


def test_libelles_types_couvrent_le_referentiel():
    from backend.plateforme.centre_alertes import TYPES_ALERTE

    # Chaque type émis par le centre d'alertes a son libellé français.
    assert set(LIBELLES_TYPE) == set(TYPES_ALERTE)


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_JSON = "/api/v1/cabinet/alertes"
URL_TXT = "/api/v1/cabinet/alertes.txt"
URL_CSV = "/api/v1/cabinet/alertes.csv"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-expal-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="export alertes")
    publier_version(session, lib, "expal@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"expal.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Expal {email}",
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
    assert dispo == f'attachment; filename="alertes-cabinet-{jour}.txt"'
    assert "CENTRE D'ALERTES DU CABINET" in r.text
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
        f'attachment; filename="alertes-cabinet-{jour}.csv"'
    )
    assert r.text.startswith("\ufeff")
    premiere = r.text.lstrip("\ufeff").splitlines()[0]
    assert premiere == "gravite;type;client;mission;libelle;echeance"


def test_api_exports_journalises(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(URL_TXT, headers=h).status_code == 200
    assert client.get(URL_CSV, headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_alertes'"
            ),
        ).mappings().all()
    assert len(lignes) == 2
    formats = {ligne["charge_utile"]["format"] for ligne in lignes}
    assert formats == {"txt", "csv"}


def test_api_coherence_avec_centre_alertes_json(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(URL_JSON, headers=h).json()
    csv_texte = client.get(URL_CSV, headers=h).text
    lignes = csv_texte.lstrip("\ufeff").splitlines()
    # Même assemblage : autant de lignes CSV que d'alertes JSON.
    assert len(lignes) - 1 == len(corps["alertes"])
    texte = client.get(URL_TXT, headers=h).text
    # Même note consultative que la vue JSON.
    assert corps["note"] in texte


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_TXT).status_code == 401
    assert client.get(URL_CSV).status_code == 401
