"""Journal d'activité du cabinet — consultation paginée du journal d'audit."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.journal_cabinet import (
    LIBELLES_ACTION,
    LONGUEUR_DETAIL_MAX,
    MENTION_NOTE,
    NB_DETAILS_MAX,
    TAILLE_DEFAUT,
    TAILLE_MAX,
    borner_page,
    borner_taille,
    condenser_details,
    libelle_action,
    serialiser_entree,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_borner_page_et_taille_defensifs():
    assert borner_page(3) == 3
    assert borner_page(0) == 1
    assert borner_page(-5) == 1
    assert borner_page("abc") == 1
    assert borner_taille(50) == 50
    assert borner_taille(0) == 1
    assert borner_taille(999) == TAILLE_MAX
    assert borner_taille(None) == TAILLE_DEFAUT


def test_libelle_action_connues_en_francais():
    assert libelle_action("creation_mission") == "Création d'une mission"
    assert (
        libelle_action("consultation_dossier_mission")
        == "Consultation du dossier de mission"
    )
    assert libelle_action("export_calendrier") == "Export du calendrier fiscal"
    # Toutes les entrées du mapping sont non vides (libellés utiles).
    assert all(v.strip() for v in LIBELLES_ACTION.values())


def test_libelle_action_inconnue_libelle_brut():
    # Action inconnue → libellé brut, jamais bloquant (le code évolue).
    assert libelle_action("action_future_inconnue") == "action_future_inconnue"
    assert libelle_action("") == ""


def test_condenser_details_scalaires_et_troncature():
    long_texte = "x" * (LONGUEUR_DETAIL_MAX + 40)
    d = condenser_details({
        "nb_total": 12,
        "format": "csv",
        "ok": True,
        "vide": None,
        "long": long_texte,
    })
    assert d["nb_total"] == 12
    assert d["format"] == "csv"
    assert d["ok"] is True
    assert d["vide"] is None
    assert len(d["long"]) == LONGUEUR_DETAIL_MAX
    assert d["long"].endswith("…")


def test_condenser_details_listes_dicts_et_plafond():
    d = condenser_details({
        "sources_en_echec": ["a", "b"],
        "imbrique": {"cle": "valeur"},
    })
    # Liste résumée par son cardinal ; dict imbriqué écarté (lisibilité).
    assert d == {"sources_en_echec": "2 élément(s)"}
    # Charge illisible → détails vides, jamais bloquant.
    assert condenser_details(None) == {}
    assert condenser_details("brut") == {}
    # Plafond de clés (tri déterministe).
    trop = {f"cle_{i:02d}": i for i in range(NB_DETAILS_MAX + 5)}
    assert len(condenser_details(trop)) == NB_DETAILS_MAX


def test_serialiser_entree_cles_stables():
    e = serialiser_entree({
        "horodatage": "2026-07-28T10:30:00+00:00",
        "acteur": "admin@cab.ci",
        "action": "creation_mission",
        "mission_id": 7,
        "charge_utile": {"exercice": 2025},
    })
    assert set(e) == {
        "horodatage", "acteur", "action", "libelle_action",
        "mission_id", "details",
    }
    assert e["libelle_action"] == "Création d'une mission"
    assert e["mission_id"] == 7
    assert e["details"] == {"exercice": 2025}
    # Entrée cabinet (hors mission) et action inconnue : tolérées.
    hors_mission = serialiser_entree({
        "horodatage": None, "acteur": None,
        "action": "ovni", "mission_id": None, "charge_utile": None,
    })
    assert hors_mission["mission_id"] is None
    assert hors_mission["libelle_action"] == "ovni"
    assert hors_mission["details"] == {}


def test_note_neutre_et_consultative():
    # Le journal DÉCRIT l'activité — formulation non accusatoire.
    assert "traçabilité" in MENTION_NOTE
    assert "surveillance" in MENTION_NOTE  # « ni un dispositif de… »
    assert "Lecture seule" in MENTION_NOTE
    assert "email" in MENTION_NOTE


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/journal"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-jrncab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="journal cabinet")
    publier_version(session, lib, "jrncab@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"jrncab.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Journal {email}",
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


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL).status_code == 401


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
    r = client.get(URL, headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 403
    assert "admin" in r.json()["detail"]


def test_api_structure_tri_decroissant_et_pagination(session):
    tid, email = _cabinet(session)
    action = f"action_test_{uuid.uuid4().hex[:8]}"
    _journaliser(session, tid, acteur=email, action=action, n=5)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(
        URL, params={"taille": 2, "action": action}, headers=h
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert set(corps) == {
        "total", "page", "taille", "entrees", "filtres", "note",
    }
    assert corps["total"] == 5
    assert corps["page"] == 1
    assert corps["taille"] == 2
    assert len(corps["entrees"]) == 2
    # Tri décroissant : la plus récente (rang 4) d'abord.
    assert corps["entrees"][0]["details"]["rang"] == 4
    assert corps["entrees"][1]["details"]["rang"] == 3
    for e in corps["entrees"]:
        assert set(e) == {
            "horodatage", "acteur", "action", "libelle_action",
            "mission_id", "details",
        }
        assert e["acteur"] == email
        # Action inconnue du mapping → libellé brut (tolérant).
        assert e["libelle_action"] == action
        assert e["horodatage"]  # ISO non vide

    # Dernière page : un seul élément (le plus ancien).
    r3 = client.get(
        URL, params={"taille": 2, "action": action, "page": 3}, headers=h
    )
    assert r3.status_code == 200
    corps3 = r3.json()
    assert corps3["page"] == 3
    assert len(corps3["entrees"]) == 1
    assert corps3["entrees"][0]["details"]["rang"] == 0

    # Page au-delà : vide, jamais bloquant.
    r9 = client.get(
        URL, params={"taille": 2, "action": action, "page": 9}, headers=h
    )
    assert r9.status_code == 200
    assert r9.json()["entrees"] == []


def test_api_filtres_action_et_acteur(session):
    tid, email = _cabinet(session)
    autre_acteur = f"collab.{uuid.uuid4().hex[:6]}@demo.local"
    action_a = f"action_a_{uuid.uuid4().hex[:6]}"
    action_b = f"action_b_{uuid.uuid4().hex[:6]}"
    _journaliser(session, tid, acteur=email, action=action_a, n=2)
    _journaliser(session, tid, acteur=autre_acteur, action=action_b, n=3)
    session.commit()

    client, h = _client_connecte(email)
    # Filtre par action.
    ra = client.get(URL, params={"action": action_a}, headers=h)
    assert ra.status_code == 200
    assert ra.json()["total"] == 2
    assert all(e["action"] == action_a for e in ra.json()["entrees"])
    assert ra.json()["filtres"] == {"action": action_a, "acteur": None}
    # Filtre par acteur (email).
    rb = client.get(URL, params={"acteur": autre_acteur}, headers=h)
    assert rb.status_code == 200
    assert rb.json()["total"] == 3
    assert all(
        e["acteur"] == autre_acteur for e in rb.json()["entrees"]
    )
    # Filtres combinés sans correspondance → vide, total 0.
    rc = client.get(
        URL,
        params={"action": action_a, "acteur": autre_acteur},
        headers=h,
    )
    assert rc.status_code == 200
    assert rc.json()["total"] == 0
    assert rc.json()["entrees"] == []


def test_api_isolation_tenant(session):
    tid1, email1 = _cabinet(session)
    action = f"action_isolee_{uuid.uuid4().hex[:8]}"
    _journaliser(session, tid1, acteur=email1, action=action, n=2)
    tid2, email2 = _cabinet(session)
    session.commit()

    # L'autre cabinet ne voit RIEN du journal du premier.
    client2, h2 = _client_connecte(email2)
    r2 = client2.get(URL, params={"action": action}, headers=h2)
    assert r2.status_code == 200
    assert r2.json()["total"] == 0
    r2b = client2.get(URL, params={"acteur": email1}, headers=h2)
    assert r2b.json()["total"] == 0

    # Le premier cabinet voit ses propres entrées.
    client1, h1 = _client_connecte(email1)
    r1 = client1.get(URL, params={"action": action}, headers=h1)
    assert r1.json()["total"] == 2


def test_api_consultation_non_journalisee_et_note(session):
    """CHOIX DOCUMENTÉ : consulter le journal n'écrit pas dans le journal."""
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    avant = client.get(URL, headers=h)
    assert avant.status_code == 200, avant.text
    total_avant = avant.json()["total"]
    # Plusieurs consultations successives : le total ne bouge pas
    # (aucun bruit auto-référentiel dans le journal).
    for _ in range(3):
        assert client.get(URL, headers=h).status_code == 200
    apres = client.get(URL, headers=h)
    assert apres.json()["total"] == total_avant
    assert "traçabilité" in apres.json()["note"]


def test_api_taille_hors_bornes_422(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(
        URL, params={"taille": 0}, headers=h
    ).status_code == 422
    assert client.get(
        URL, params={"taille": 101}, headers=h
    ).status_code == 422
    assert client.get(
        URL, params={"page": 0}, headers=h
    ).status_code == 422
