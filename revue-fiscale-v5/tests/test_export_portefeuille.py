"""Export du portefeuille déclaratif — texte français + CSV."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from backend.plateforme import brief_cabinet
from backend.plateforme.export_portefeuille import (
    COLONNES_CSV,
    LIBELLES_STATUT,
    rendre_portefeuille_csv,
    rendre_portefeuille_texte,
)
from backend.plateforme.portefeuille_declaratif import (
    NOTE_PORTEFEUILLE_DECLARATIF,
    assembler_portefeuille,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

JOUR = date(2026, 7, 28)


def _completude(**surcharge) -> dict:
    """Vue mission minimale au format completude_declarative."""
    base = {
        "disponible": True,
        "exercice": 2025,
        "impots": {
            "tva": {
                "disponible": True,
                "nb_saisies": 2,
                "nb_attendues": 12,
                "manquantes": [f"2025-{m:02d}" for m in range(3, 13)],
            },
            "salaires": {
                "disponible": True,
                "nb_saisies": 12,
                "nb_attendues": 12,
                "manquantes": [],
            },
        },
    }
    base.update(surcharge)
    return base


def _vue(**surcharge) -> dict:
    base = {
        "client": "SA FICTIVE",
        "mission_id": 7,
        "exercice": 2025,
        "completude": _completude(),
    }
    base.update(surcharge)
    return base


def _corps(vues: list[dict]) -> dict:
    return assembler_portefeuille(vues, aujourd_hui=JOUR)


def _lignes_csv(contenu: str) -> list[list[str]]:
    lecteur = csv.reader(
        io.StringIO(contenu.lstrip("\ufeff")), delimiter=";"
    )
    return list(lecteur)


def test_texte_reutilise_le_rendu_du_brief_sans_duplication():
    # L'export .txt est LA MÊME fonction que celle du brief du cabinet.
    assert rendre_portefeuille_texte is brief_cabinet.rendre_portefeuille_texte


def test_texte_contenu_francais_et_note():
    texte = rendre_portefeuille_texte(_corps([_vue()]))
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in texte
    assert "Date d'édition : 28/07/2026" in texte
    assert "SA FICTIVE" in texte
    assert NOTE_PORTEFEUILLE_DECLARATIF in texte


def test_csv_bom_point_virgule_et_colonnes():
    contenu = rendre_portefeuille_csv(_corps([_vue()]))
    # BOM UTF-8 en tête — Excel FR reconnaît l'encodage.
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(COLONNES_CSV)
    assert lignes[0] == (
        "client;exercice;mission;statut;"
        "tva_saisies;tva_attendues;tva_manquantes;"
        "salaires_saisies;salaires_attendues;salaires_manquantes"
    )


def test_csv_ligne_a_completer_valeurs_et_manquantes():
    lignes = _lignes_csv(rendre_portefeuille_csv(_corps([_vue()])))
    assert lignes[1] == [
        "SA FICTIVE", "2025", "7", "périodes à saisir",
        "2", "12", ", ".join(f"2025-{m:02d}" for m in range(3, 13)),
        "12", "12", "",
    ]


def test_csv_ligne_a_jour_sans_manquante():
    completude = _completude()
    completude["impots"]["tva"].update(nb_saisies=12, manquantes=[])
    lignes = _lignes_csv(
        rendre_portefeuille_csv(_corps([_vue(completude=completude)]))
    )
    assert lignes[1][3] == "à jour"
    assert lignes[1][6] == ""  # aucune période TVA manquante
    assert lignes[1][9] == ""


def test_csv_ligne_indisponible_compteurs_a_zero():
    # Vue mission en échec (None) → ligne « indisponible », cellules
    # numériques à zéro, jamais bloquant.
    lignes = _lignes_csv(
        rendre_portefeuille_csv(_corps([_vue(completude=None)]))
    )
    assert lignes[1] == [
        "SA FICTIVE", "2025", "7", "indisponible",
        "0", "0", "", "0", "0", "",
    ]


def test_csv_echappement_point_virgule_et_guillemets():
    piege = 'SARL "PIÈGE" ; ET FILS'
    contenu = rendre_portefeuille_csv(_corps([_vue(client=piege)]))
    lignes = _lignes_csv(contenu)
    # Relecture stdlib : la valeur revient INTACTE malgré « ; » et « " ».
    assert lignes[0] == list(COLONNES_CSV)
    assert lignes[1][0] == piege


def test_csv_corps_vide_en_tete_seule():
    contenu = rendre_portefeuille_csv({})
    assert contenu.startswith("\ufeff")
    assert contenu.lstrip("\ufeff").splitlines() == [
        ";".join(COLONNES_CSV)
    ]


def test_csv_tri_collecte_a_organiser_d_abord():
    completude_ok = _completude()
    completude_ok["impots"]["tva"].update(nb_saisies=12, manquantes=[])
    lignes = _lignes_csv(rendre_portefeuille_csv(_corps([
        _vue(client="Alpha SA", mission_id=1, completude=completude_ok),
        _vue(client="Zeta SARL", mission_id=2),
    ])))
    # Même ordre que la vue : périodes à saisir d'abord.
    assert [ligne[0] for ligne in lignes[1:]] == ["Zeta SARL", "Alpha SA"]


def test_libelles_statut_couvrent_le_referentiel():
    from backend.plateforme.portefeuille_declaratif import (
        STATUT_A_COMPLETER,
        STATUT_A_JOUR,
        STATUT_INDISPONIBLE,
    )

    assert set(LIBELLES_STATUT) == {
        STATUT_A_COMPLETER, STATUT_A_JOUR, STATUT_INDISPONIBLE,
    }
    # Formulations factuelles — jamais un reproche.
    assert all(v.strip() for v in LIBELLES_STATUT.values())


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_JSON = "/api/v1/cabinet/portefeuille-declaratif"
URL_TXT = "/api/v1/cabinet/portefeuille-declaratif.txt"
URL_CSV = "/api/v1/cabinet/portefeuille-declaratif.csv"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-expfd-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="export portefeuille")
    publier_version(session, lib, "expfd@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"expfd.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab ExpPortefeuille {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission_en_cours(session, tenant_id: int, nom: str,
                      exercice: int = 2025) -> int:
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
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": int(mid)},
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


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_TXT).status_code == 401
    assert client.get(URL_CSV).status_code == 401


def test_api_txt_200_entetes_et_contenu(session):
    tid, email = _cabinet(session)
    _mission_en_cours(session, tid, "PM ExpPortefeuille FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="portefeuille-declaratif-{jour}.txt"'
    )
    assert "PORTEFEUILLE DÉCLARATIF DU CABINET" in r.text
    assert "PM ExpPortefeuille FICTIVE" in r.text
    assert NOTE_PORTEFEUILLE_DECLARATIF in r.text


def test_api_csv_200_entetes_bom_et_colonnes(session):
    tid, email = _cabinet(session)
    _mission_en_cours(session, tid, "PM ExpPortefeuille CSV")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_CSV, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="portefeuille-declaratif-{jour}.csv"'
    )
    assert r.text.startswith("\ufeff")
    lignes = r.text.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(COLONNES_CSV)
    assert any("PM ExpPortefeuille CSV" in ligne for ligne in lignes[1:])


def test_api_coherence_avec_vue_json(session):
    tid, email = _cabinet(session)
    _mission_en_cours(session, tid, "PM ExpPortefeuille JSON")
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(URL_JSON, headers=h).json()
    lignes = client.get(URL_CSV, headers=h).text.lstrip(
        "\ufeff"
    ).splitlines()
    # Même assemblage : autant de lignes CSV que de missions JSON.
    assert len(lignes) - 1 == len(corps["missions"])
    # Même note consultative que la vue JSON dans le texte.
    texte = client.get(URL_TXT, headers=h).text
    assert corps["note"] in texte


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
                "WHERE action = 'export_portefeuille_declaratif'"
            ),
        ).mappings().all()
    assert len(lignes) == 2
    formats = {ligne["charge_utile"]["format"] for ligne in lignes}
    assert formats == {"txt", "csv"}
    assert all(
        {"nb_missions", "nb_a_completer", "nb_indisponibles"}
        <= set(ligne["charge_utile"])
        for ligne in lignes
    )


def test_api_isolation_tenant(session):
    # La mission du cabinet A n'apparaît JAMAIS dans l'export du
    # cabinet B — RLS par tenant.
    tid_a, email_a = _cabinet(session)
    _mission_en_cours(session, tid_a, "PM Isolation Tenant A")
    tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    csv_b = client_b.get(URL_CSV, headers=h_b)
    txt_b = client_b.get(URL_TXT, headers=h_b)
    assert csv_b.status_code == 200
    assert txt_b.status_code == 200
    assert "PM Isolation Tenant A" not in csv_b.text
    assert "PM Isolation Tenant A" not in txt_b.text

    client_a, h_a = _client_connecte(email_a)
    assert "PM Isolation Tenant A" in client_a.get(
        URL_CSV, headers=h_a
    ).text
