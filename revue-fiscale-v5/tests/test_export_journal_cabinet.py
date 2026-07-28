"""Export du journal d'activité du cabinet — texte français + CSV."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from backend.plateforme.export_journal_cabinet import (
    COLONNES_CSV,
    PLAFOND_EXPORT,
    rendre_journal_csv,
    rendre_journal_texte,
)
from backend.plateforme.journal_cabinet import MENTION_NOTE

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _entree(**surcharge) -> dict:
    base = {
        "horodatage": "2026-07-28T10:30:00+00:00",
        "acteur": "admin@cab.ci",
        "action": "creation_mission",
        "libelle_action": "Création d'une mission",
        "mission_id": 7,
        "details": {"exercice": 2025},
    }
    base.update(surcharge)
    return base


def _corps(entrees: list[dict], total: int | None = None) -> dict:
    return {
        "total": total if total is not None else len(entrees),
        "entrees": entrees,
        "filtres": {"action": None, "acteur": None},
        "note": MENTION_NOTE,
    }


def test_texte_en_tete_date_et_entrees_francaises():
    texte = rendre_journal_texte(
        _corps([
            _entree(),
            _entree(
                horodatage="2026-07-27T09:05:00+00:00",
                acteur="collab@cab.ci",
                action="export_calendrier",
                libelle_action="Export du calendrier fiscal",
                mission_id=None,
                details={},
            ),
        ]),
        aujourd_hui="2026-07-28",
    )
    assert "JOURNAL D'ACTIVITÉ DU CABINET" in texte
    assert "Date d'édition : 28/07/2026" in texte
    assert "Entrées exportées : 2 (total : 2)" in texte
    # Entrée datée JJ/MM/AAAA HH:MM, acteur, libellé français, mission.
    assert (
        "  - 28/07/2026 10:30 — admin@cab.ci — Création d'une mission "
        "(mission n°7) — exercice : 2025" in texte
    )
    # Entrée hors mission, sans détails : pas de mention parasite.
    assert (
        "  - 27/07/2026 09:05 — collab@cab.ci — "
        "Export du calendrier fiscal" in texte
    )
    assert "(mission n°7)" in texte
    # Jamais le code technique brut dans la ligne (libellé français).
    assert "creation_mission" not in texte


def test_texte_note_consultative_en_pied():
    texte = rendre_journal_texte(_corps([_entree()]))
    assert MENTION_NOTE in texte
    # La note ferme le document — l'humain décide, le document décrit.
    assert texte.rstrip().endswith(MENTION_NOTE)


def test_texte_filtres_rappeles_et_plafond_mentionne():
    corps = _corps([_entree()], total=1200)
    corps["filtres"] = {"action": "creation_mission", "acteur": "a@b.ci"}
    texte = rendre_journal_texte(corps)
    assert "Filtre action : creation_mission" in texte
    assert "Filtre acteur : a@b.ci" in texte
    assert "Entrées exportées : 1 (total : 1200)" in texte
    assert "Export plafonné aux entrées les plus récentes" in texte
    # Sans dépassement ni filtre : aucune mention parasite.
    sans = rendre_journal_texte(_corps([_entree()]))
    assert "plafonné" not in sans
    assert "Filtre action" not in sans


def test_texte_corps_vide_tolerant():
    texte = rendre_journal_texte({})
    assert "JOURNAL D'ACTIVITÉ DU CABINET" in texte
    assert "Entrées exportées : 0 (total : 0)" in texte
    assert "Aucune entrée pour ces critères." in texte
    # Corps assemblé sans entrée : note consultative présente.
    texte2 = rendre_journal_texte(_corps([]))
    assert MENTION_NOTE in texte2


def test_csv_en_tete_bom_et_point_virgule():
    contenu = rendre_journal_csv(_corps([_entree()]))
    # BOM UTF-8 en tête — Excel FR reconnaît l'encodage.
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(COLONNES_CSV)
    assert lignes[0] == (
        "horodatage;date;acteur;action;libelle;mission;details"
    )
    assert lignes[1] == (
        "2026-07-28T10:30:00+00:00;28/07/2026 10:30;admin@cab.ci;"
        "creation_mission;Création d'une mission;7;exercice : 2025"
    )


def test_csv_echappement_point_virgule_et_guillemets():
    piege = 'écart "notable" ; à examiner'
    contenu = rendre_journal_csv(
        _corps([_entree(details={"motif": piege}, mission_id=None)])
    )
    # Relecture stdlib : la valeur revient INTACTE malgré « ; » et « " ».
    lecteur = csv.reader(
        io.StringIO(contenu.lstrip("\ufeff")), delimiter=";"
    )
    lignes = list(lecteur)
    assert lignes[0] == list(COLONNES_CSV)
    assert lignes[1][6] == f"motif : {piege}"
    assert lignes[1][5] == ""  # hors mission → cellule vide


def test_csv_corps_vide_en_tete_seule():
    contenu = rendre_journal_csv({})
    assert contenu.startswith("\ufeff")
    lignes = contenu.lstrip("\ufeff").splitlines()
    assert lignes == [";".join(COLONNES_CSV)]


def test_plafond_export_raisonnable():
    assert PLAFOND_EXPORT == 500


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_JSON = "/api/v1/cabinet/journal"
URL_TXT = "/api/v1/cabinet/journal.txt"
URL_CSV = "/api/v1/cabinet/journal.csv"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-expjrn-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="export journal")
    publier_version(session, lib, "expjrn@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"expjrn.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab ExpJrn {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _journaliser(
    session, tenant_id: int, *, acteur: str, action: str, n: int = 1
) -> None:
    from backend.moteur.journal import append_journal

    with contexte_tenant(session, tenant_id):
        for i in range(n):
            append_journal(
                session,
                tenant_id=tenant_id,
                mission_id=None,
                acteur=acteur,
                action=action,
                charge_utile={"rang": i},
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


def test_api_txt_200_entetes_et_contenu(session):
    tid, email = _cabinet(session)
    action = f"action_exp_{uuid.uuid4().hex[:8]}"
    _journaliser(session, tid, acteur=email, action=action, n=2)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="journal-cabinet-{jour}.txt"'
    )
    assert "JOURNAL D'ACTIVITÉ DU CABINET" in r.text
    assert MENTION_NOTE in r.text
    # Les entrées journalisées apparaissent (action inconnue → brut).
    assert action in r.text
    assert email in r.text


def test_api_csv_200_entetes_bom_et_colonnes(session):
    tid, email = _cabinet(session)
    _journaliser(
        session, tid, acteur=email,
        action=f"action_exp_{uuid.uuid4().hex[:8]}",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_CSV, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="journal-cabinet-{jour}.csv"'
    )
    assert r.text.startswith("\ufeff")
    premiere = r.text.lstrip("\ufeff").splitlines()[0]
    assert premiere == (
        "horodatage;date;acteur;action;libelle;mission;details"
    )


def test_api_filtres_action_et_acteur(session):
    tid, email = _cabinet(session)
    autre_acteur = f"collab.{uuid.uuid4().hex[:6]}@demo.local"
    action_a = f"action_a_{uuid.uuid4().hex[:6]}"
    action_b = f"action_b_{uuid.uuid4().hex[:6]}"
    _journaliser(session, tid, acteur=email, action=action_a, n=2)
    _journaliser(session, tid, acteur=autre_acteur, action=action_b, n=3)
    session.commit()

    client, h = _client_connecte(email)
    # Filtre par action : seules ces lignes dans le CSV.
    ra = client.get(URL_CSV, params={"action": action_a}, headers=h)
    assert ra.status_code == 200
    lignes = ra.text.lstrip("\ufeff").splitlines()
    assert len(lignes) - 1 == 2
    assert all(action_a in ligne for ligne in lignes[1:])
    # Filtre par acteur (email) sur le texte.
    rb = client.get(URL_TXT, params={"acteur": autre_acteur}, headers=h)
    assert rb.status_code == 200
    assert "Filtre acteur : " + autre_acteur in rb.text
    assert action_b in rb.text
    assert action_a not in rb.text
    # Filtres combinés sans correspondance → document vide valide.
    rc = client.get(
        URL_TXT,
        params={"action": action_a, "acteur": autre_acteur},
        headers=h,
    )
    assert rc.status_code == 200
    assert "Aucune entrée pour ces critères." in rc.text


def test_api_coherence_avec_journal_json(session):
    tid, email = _cabinet(session)
    action = f"action_coh_{uuid.uuid4().hex[:8]}"
    _journaliser(session, tid, acteur=email, action=action, n=3)
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(
        URL_JSON, params={"action": action}, headers=h
    ).json()
    csv_texte = client.get(
        URL_CSV, params={"action": action}, headers=h
    ).text
    lignes = csv_texte.lstrip("\ufeff").splitlines()
    # Même lecture : autant de lignes CSV que d'entrées JSON.
    assert len(lignes) - 1 == corps["total"] == 3
    texte = client.get(
        URL_TXT, params={"action": action}, headers=h
    ).text
    # Même note consultative que la vue JSON.
    assert corps["note"] in texte


def test_api_export_non_journalise(session):
    """COHÉRENT avec GET /cabinet/journal : l'export n'écrit rien."""
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    total_avant = client.get(URL_JSON, headers=h).json()["total"]
    assert client.get(URL_TXT, headers=h).status_code == 200
    assert client.get(URL_CSV, headers=h).status_code == 200
    total_apres = client.get(URL_JSON, headers=h).json()["total"]
    assert total_apres == total_avant


def test_api_403_role_non_admin(session):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.plateforme.auth import emettre_jeton, hasher_mot_de_passe
    from backend.plateforme.contexte import effacer_contexte_tenant

    tid, email = _cabinet(session)
    with contexte_tenant(session, tid):
        rev_id = session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'reviseur', :h, TRUE) RETURNING id"
            ),
            {
                "t": tid,
                "e": f"rev.{uuid.uuid4().hex[:8]}@demo.local",
                "h": hasher_mot_de_passe("x"),
            },
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.commit()

    jeton = emettre_jeton(
        utilisateur_id=int(rev_id),
        tenant_id=tid,
        role="reviseur",
        email="rev@t.ci",
    )
    client = TestClient(app)
    h = {"Authorization": f"Bearer {jeton}"}
    for url in (URL_TXT, URL_CSV):
        r = client.get(url, headers=h)
        assert r.status_code == 403
        assert "admin" in r.json()["detail"]


def test_api_isolation_tenant(session):
    tid1, email1 = _cabinet(session)
    action = f"action_iso_{uuid.uuid4().hex[:8]}"
    _journaliser(session, tid1, acteur=email1, action=action, n=2)
    tid2, email2 = _cabinet(session)
    session.commit()

    # L'autre cabinet n'exporte RIEN du journal du premier.
    client2, h2 = _client_connecte(email2)
    r2 = client2.get(URL_CSV, params={"action": action}, headers=h2)
    assert r2.status_code == 200
    assert len(r2.text.lstrip("\ufeff").splitlines()) == 1
    # Le premier cabinet exporte ses propres entrées.
    client1, h1 = _client_connecte(email1)
    r1 = client1.get(URL_CSV, params={"action": action}, headers=h1)
    assert len(r1.text.lstrip("\ufeff").splitlines()) == 3


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_TXT).status_code == 401
    assert client.get(URL_CSV).status_code == 401
