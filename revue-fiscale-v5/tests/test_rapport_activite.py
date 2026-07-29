"""Rapport d'activité mensuel du cabinet — synthèse de réunion."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.rapport_activite import (
    FAMILLES,
    LIBELLES_FAMILLE,
    MENTION_INSTANTANE_ALERTES,
    MENTION_SECTION_INDISPONIBLE,
    NOTE_RAPPORT,
    PLAFOND_ACTIONS_DISTINCTES,
    bornes_mois,
    famille_action,
    libelle_mois_fr,
    rendre_rapport_texte,
    valider_mois,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _corps(**surcharge) -> dict:
    base = {
        "mois": "2026-07",
        "mois_libelle": "juillet 2026",
        "missions": {"creees": "2", "cloturees": "1"},
        "points_convenus": {"crees": "3", "soldes": "1"},
        "alertes_actuelles": {
            "disponible": True,
            "au": "2026-07-28",
            "total": "4",
            "par_gravite": {
                "critique": "1", "vigilance": "2", "info": "1",
            },
            "mention": MENTION_INSTANTANE_ALERTES,
        },
        "journal": {
            "total": "12",
            "par_famille": {
                "imports": "2",
                "exports": "3",
                "consultations": "5",
                "modifications": "2",
            },
            "plafond_atteint": False,
        },
        "note": NOTE_RAPPORT,
    }
    base.update(surcharge)
    return base


def test_valider_mois_et_bornes():
    assert valider_mois("2026-07") == (2026, 7)
    assert valider_mois(" 2026-01 ") == (2026, 1)
    assert bornes_mois(2026, 7) == (date(2026, 7, 1), date(2026, 8, 1))
    # Décembre : la borne haute bascule sur janvier de l'année suivante.
    assert bornes_mois(2026, 12) == (date(2026, 12, 1), date(2027, 1, 1))
    assert libelle_mois_fr(2026, 7) == "juillet 2026"
    assert libelle_mois_fr(2025, 12) == "décembre 2025"


def test_valider_mois_invalide():
    for brut in (
        "", None, "2026", "2026/07", "2026-13", "2026-00", "26-01",
        "2026-7", "abcd-ef", "1999-05", "2101-01",
    ):
        with pytest.raises(ValueError):
            valider_mois(brut)


def test_famille_action_mapping():
    assert famille_action("import_balance") == "imports"
    assert famille_action("depot_piece_contribuable") == "imports"
    assert famille_action("export_alertes") == "exports"
    assert famille_action("telechargement_ordre_du_jour") == "exports"
    assert famille_action("generation_note_synthese") == "exports"
    assert famille_action("consultation_fiche_client") == "consultations"
    assert famille_action("creation_mission") == "modifications"
    assert famille_action("changement_statut") == "modifications"
    # Action inconnue ou illisible → famille par défaut, jamais bloquant.
    assert famille_action("action_future_inconnue") == "modifications"
    assert famille_action(None) == "modifications"
    assert set(LIBELLES_FAMILLE) == set(FAMILLES)
    assert PLAFOND_ACTIONS_DISTINCTES == 200


def test_texte_en_tete_mois_francais():
    texte = rendre_rapport_texte(_corps())
    assert texte.startswith(
        "RAPPORT D'ACTIVITÉ DU CABINET — juillet 2026"
    )


def test_texte_sections_et_compteurs():
    texte = rendre_rapport_texte(_corps())
    assert "Missions créées dans le mois : 2" in texte
    assert "Missions clôturées dans le mois : 1" in texte
    assert "Points convenus créés dans le mois : 3" in texte
    assert "Points convenus soldés dans le mois : 1" in texte
    assert "Critique : 1" in texte
    assert "Vigilance : 2" in texte
    assert "Information : 1" in texte
    assert "Entrées de journal dans le mois : 12" in texte
    assert "Imports et dépôts : 2" in texte
    assert "Exports et documents produits : 3" in texte
    assert "Consultations : 5" in texte
    assert "Modifications et décisions : 2" in texte
    # Sans plafond atteint : aucune mention parasite.
    assert "plafonné" not in texte
    avec_plafond = rendre_rapport_texte(
        _corps(journal={"total": "9999", "plafond_atteint": True})
    )
    assert "plafonné" in avec_plafond


def test_texte_alertes_instantane_et_indisponible():
    texte = rendre_rapport_texte(_corps())
    # Les alertes sont un INSTANTANÉ — la mention figure au document.
    assert MENTION_INSTANTANE_ALERTES in texte
    assert "pas un historique du mois" in texte
    # Source en échec → mention douce, jamais une exception.
    indispo = rendre_rapport_texte(
        _corps(alertes_actuelles={"disponible": False})
    )
    assert MENTION_SECTION_INDISPONIBLE in indispo
    assert "Critique :" not in indispo


def test_texte_note_consultative_en_pied():
    texte = rendre_rapport_texte(_corps())
    assert NOTE_RAPPORT in texte
    # La note ferme le document — l'humain décide, le document décrit.
    assert texte.rstrip().endswith(NOTE_RAPPORT)
    assert "aucun indicateur de performance individuelle" in texte


def test_texte_agregats_sans_noms_propres():
    """Les compteurs sont AGRÉGÉS : aucun email ni nom de personne."""
    texte = rendre_rapport_texte(_corps())
    assert "@" not in texte
    # Aucune section « par collaborateur » : pilotage collectif.
    assert "collaborateur" not in texte.lower()
    assert "classement" not in texte.split("Note :")[0].lower()


def test_texte_corps_vide_tolerant():
    texte = rendre_rapport_texte({})
    assert texte.startswith("RAPPORT D'ACTIVITÉ DU CABINET")
    assert "Missions créées dans le mois : 0" in texte
    assert "Points convenus soldés dans le mois : 0" in texte
    assert "Entrées de journal dans le mois : 0" in texte


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL_JSON = "/api/v1/cabinet/rapport-activite"
URL_TXT = "/api/v1/cabinet/rapport-activite.txt"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-rapact-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="rapport activite")
    publier_version(session, lib, "rapact@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rapact.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RapAct {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission(session, tenant_id: int, denomination: str) -> int:
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
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
    return int(mid)


def _point_convenu(
    session, tenant_id: int, mission_id: int, statut: str = "a_faire"
) -> None:
    with contexte_tenant(session, tenant_id):
        pid = session.execute(
            text(
                "INSERT INTO point_convenu "
                "(tenant_id, mission_id, libelle) "
                "VALUES (:t, :m, 'Régulariser la TVA') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        if statut != "a_faire":
            session.execute(
                text(
                    "UPDATE point_convenu "
                    "SET statut = :s, mis_a_jour_le = now() "
                    "WHERE id = :p"
                ),
                {"s": statut, "p": pid},
            )


def _journaliser(
    session,
    tenant_id: int,
    *,
    acteur: str,
    action: str,
    mission_id: int | None = None,
    charge_utile: dict | None = None,
) -> None:
    from backend.moteur.journal import append_journal

    with contexte_tenant(session, tenant_id):
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=action,
            charge_utile=charge_utile or {},
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


def _mois_courant() -> str:
    jour = date.today()
    return f"{jour.year:04d}-{jour.month:02d}"


def test_api_json_200_structure_et_compteurs(session):
    tid, email = _cabinet(session)
    mid = _mission(session, tid, "SA RapAct FICTIVE")
    _point_convenu(session, tid, mid)
    _point_convenu(session, tid, mid, statut="fait")
    # Clôture tracée au journal (changement_statut → cloturee).
    _journaliser(
        session, tid, acteur=email, action="changement_statut",
        mission_id=mid,
        charge_utile={"statut_precedent": "en_cours", "statut": "cloturee"},
    )
    _journaliser(session, tid, acteur=email, action="import_balance",
                 mission_id=mid)
    _journaliser(session, tid, acteur=email, action="export_alertes")
    _journaliser(
        session, tid, acteur=email, action="consultation_fiche_client"
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL_JSON, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mois"] == _mois_courant()
    # Compteurs AGRÉGÉS en str — cabinet neuf : valeurs exactes.
    assert corps["missions"] == {"creees": "1", "cloturees": "1"}
    assert corps["points_convenus"] == {"crees": "2", "soldes": "1"}
    journal = corps["journal"]
    assert int(journal["par_famille"]["imports"]) >= 1
    assert int(journal["par_famille"]["exports"]) >= 1
    assert int(journal["par_famille"]["consultations"]) >= 1
    assert int(journal["par_famille"]["modifications"]) >= 1
    assert int(journal["total"]) >= 4
    alertes = corps["alertes_actuelles"]
    assert set(alertes["par_gravite"]) == {"critique", "vigilance", "info"}
    assert all(isinstance(v, str) for v in alertes["par_gravite"].values())
    assert alertes["mention"] == MENTION_INSTANTANE_ALERTES
    assert corps["note"] == NOTE_RAPPORT


def test_api_mois_par_defaut_et_libelle_francais(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    # Sans paramètre : mois courant.
    corps = client.get(URL_JSON, headers=h).json()
    assert corps["mois"] == _mois_courant()
    jour = date.today()
    assert corps["mois_libelle"] == libelle_mois_fr(jour.year, jour.month)
    # Mois explicite SANS activité : compteurs à zéro (période bornée).
    vide = client.get(URL_JSON, params={"mois": "2020-01"}, headers=h)
    assert vide.status_code == 200
    corps_vide = vide.json()
    assert corps_vide["mois"] == "2020-01"
    assert corps_vide["mois_libelle"] == "janvier 2020"
    assert corps_vide["missions"] == {"creees": "0", "cloturees": "0"}
    assert corps_vide["points_convenus"] == {"crees": "0", "soldes": "0"}
    assert corps_vide["journal"]["total"] == "0"


def test_api_422_mois_invalide(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    for brut in ("2026-13", "2026/07", "abcdefg", "2026-9"):
        for url in (URL_JSON, URL_TXT):
            r = client.get(url, params={"mois": brut}, headers=h)
            assert r.status_code == 422, (brut, url, r.text)


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
    for url in (URL_JSON, URL_TXT):
        r = client.get(url, headers=h)
        assert r.status_code == 403
        assert "admin" in r.json()["detail"]


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL_JSON).status_code == 401
    assert client.get(URL_TXT).status_code == 401


def test_api_txt_entetes_contenu_et_journalisation(session):
    tid, email = _cabinet(session)
    _mission(session, tid, "SA RapActTxt FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    mois = _mois_courant()
    r = client.get(URL_TXT, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"] == (
        f'attachment; filename="rapport-activite-{mois}.txt"'
    )
    assert "RAPPORT D'ACTIVITÉ DU CABINET — " in r.text
    assert NOTE_RAPPORT in r.text
    # L'export (document emporté) EST journalisé — avec le mois visé.
    journal = client.get(
        "/api/v1/cabinet/journal",
        params={"action": "export_rapport_activite"},
        headers=h,
    ).json()
    assert journal["total"] == 1
    entree = journal["entrees"][0]
    assert entree["acteur"] == email
    assert entree["details"]["mois"] == mois
    assert entree["libelle_action"] == (
        "Export du rapport d'activité du cabinet"
    )


def test_api_isolation_tenant(session):
    tid1, email1 = _cabinet(session)
    mid = _mission(session, tid1, "SA RapActIso FICTIVE")
    _point_convenu(session, tid1, mid)
    tid2, email2 = _cabinet(session)
    session.commit()

    # L'autre cabinet ne voit RIEN de l'activité du premier.
    client2, h2 = _client_connecte(email2)
    corps2 = client2.get(URL_JSON, headers=h2).json()
    assert corps2["missions"]["creees"] == "0"
    assert corps2["points_convenus"]["crees"] == "0"
    # Le premier cabinet voit sa propre activité.
    client1, h1 = _client_connecte(email1)
    corps1 = client1.get(URL_JSON, headers=h1).json()
    assert corps1["missions"]["creees"] == "1"
    assert corps1["points_convenus"]["crees"] == "1"
