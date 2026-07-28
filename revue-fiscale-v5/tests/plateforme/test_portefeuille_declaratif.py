"""Suivi déclaratif du portefeuille — complétude consolidée du cabinet."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.portefeuille_declaratif import (
    NOTE_PORTEFEUILLE_DECLARATIF,
    STATUT_A_COMPLETER,
    STATUT_A_JOUR,
    STATUT_INDISPONIBLE,
    assembler_portefeuille,
    resumer_mission,
    synthese_portefeuille,
    trier_missions,
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


def test_resumer_mission_cles_stables_et_blocs():
    e = resumer_mission(_vue())
    assert set(e) == {
        "client", "mission_id", "exercice", "tva", "salaires", "statut",
    }
    assert e["client"] == "SA FICTIVE"
    assert e["mission_id"] == 7
    assert e["exercice"] == 2025
    assert e["tva"] == {
        "disponible": True,
        "saisies": 2,
        "attendues": 12,
        "manquantes": [f"2025-{m:02d}" for m in range(3, 13)],
    }
    assert e["salaires"]["manquantes"] == []
    assert e["statut"] == STATUT_A_COMPLETER


def test_resumer_mission_a_jour_sans_manquante():
    completude = _completude()
    completude["impots"]["tva"]["manquantes"] = []
    completude["impots"]["tva"]["nb_saisies"] = 12
    e = resumer_mission(_vue(completude=completude))
    assert e["statut"] == STATUT_A_JOUR


def test_resumer_mission_sans_periode_echue_est_a_jour():
    # Exercice futur : rien à collecter → à jour (rien d'accusatoire).
    completude = _completude()
    for bloc in completude["impots"].values():
        bloc.update(nb_saisies=0, nb_attendues=0, manquantes=[])
    e = resumer_mission(_vue(completude=completude))
    assert e["statut"] == STATUT_A_JOUR
    assert e["tva"]["attendues"] == 0


def test_resumer_mission_echec_devient_indisponible():
    # Vue mission en échec (None) → entrée indisponible, clés stables.
    e = resumer_mission(_vue(completude=None))
    assert e["statut"] == STATUT_INDISPONIBLE
    assert e["client"] == "SA FICTIVE"
    assert e["mission_id"] == 7
    assert e["tva"] == {
        "disponible": False, "saisies": 0, "attendues": 0, "manquantes": [],
    }
    assert e["salaires"]["disponible"] is False


def test_resumer_mission_vue_indisponible_globale():
    # completude.disponible=False (les deux blocs illisibles).
    completude = _completude(disponible=False)
    for bloc in completude["impots"].values():
        bloc["disponible"] = False
    e = resumer_mission(_vue(completude=completude))
    assert e["statut"] == STATUT_INDISPONIBLE


def test_resumer_mission_defensif_valeurs_absentes():
    e = resumer_mission({})
    assert e["client"] == ""
    assert e["mission_id"] is None
    assert e["exercice"] is None
    assert e["statut"] == STATUT_INDISPONIBLE


def test_trier_missions_a_completer_d_abord_puis_alphabetique():
    tri = trier_missions([
        {"statut": STATUT_A_JOUR, "client": "Alpha", "mission_id": 1},
        {"statut": STATUT_A_COMPLETER, "client": "zeta", "mission_id": 2},
        {"statut": STATUT_INDISPONIBLE, "client": "Beta", "mission_id": 3},
        {"statut": STATUT_A_COMPLETER, "client": "Beta", "mission_id": 4},
    ])
    assert [(t["statut"], t["client"]) for t in tri] == [
        (STATUT_A_COMPLETER, "Beta"),
        (STATUT_A_COMPLETER, "zeta"),  # casse ignorée (casefold)
        (STATUT_A_JOUR, "Alpha"),
        (STATUT_INDISPONIBLE, "Beta"),
    ]


def test_synthese_portefeuille_compteurs():
    s = synthese_portefeuille([
        {"statut": STATUT_A_COMPLETER},
        {"statut": STATUT_A_COMPLETER},
        {"statut": STATUT_A_JOUR},
        {"statut": STATUT_INDISPONIBLE},
    ])
    assert s == {
        "nb_missions": 4,
        "nb_a_jour": 1,
        "nb_a_completer": 2,
        "nb_indisponibles": 1,
    }


def test_assembler_portefeuille_vide_tolerant_cles_stables():
    vue = assembler_portefeuille([], aujourd_hui=JOUR)
    assert set(vue) == {"aujourd_hui", "missions", "synthese", "note"}
    assert vue["aujourd_hui"] == "2026-07-28"
    assert vue["missions"] == []
    assert vue["synthese"] == {
        "nb_missions": 0,
        "nb_a_jour": 0,
        "nb_a_completer": 0,
        "nb_indisponibles": 0,
    }
    assert vue["note"] == NOTE_PORTEFEUILLE_DECLARATIF


def test_assembler_portefeuille_tri_et_synthese_coherents():
    completude_ok = _completude()
    completude_ok["impots"]["tva"].update(nb_saisies=12, manquantes=[])
    vue = assembler_portefeuille(
        [
            _vue(client="Zeta SARL", mission_id=1,
                 completude=completude_ok),
            _vue(client="Alpha SA", mission_id=2),
            _vue(client="Mika CI", mission_id=3, completude=None),
        ],
        aujourd_hui=JOUR,
    )
    assert [(m["client"], m["statut"]) for m in vue["missions"]] == [
        ("Alpha SA", STATUT_A_COMPLETER),
        ("Mika CI", STATUT_INDISPONIBLE),
        ("Zeta SARL", STATUT_A_JOUR),
    ]
    assert vue["synthese"]["nb_missions"] == 3
    assert vue["synthese"]["nb_a_completer"] == 1
    assert vue["synthese"]["nb_indisponibles"] == 1


def test_note_consultative_collecte_l_humain_decide():
    assert "consultatif" in NOTE_PORTEFEUILLE_DECLARATIF
    assert "collecte" in NOTE_PORTEFEUILLE_DECLARATIF
    assert "décide" in NOTE_PORTEFEUILLE_DECLARATIF
    # Formulation factuelle, jamais accusatoire.
    assert "manquement" not in NOTE_PORTEFEUILLE_DECLARATIF.lower()


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/portefeuille-declaratif"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-pdecl-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="portefeuille declaratif")
    publier_version(session, lib, "pdecl@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"pdecl.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Portefeuille {email}",
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


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL).status_code == 401


def test_api_structure_stable_et_coherence_vue_mission(session):
    # Exercice 2025 passé : 12 périodes attendues par impôt ; 2 TVA
    # saisies → le portefeuille reflète EXACTEMENT la vue mission.
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Portefeuille FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    for periode in ("2025-01", "2025-02"):
        r = client.post(
            f"/api/v1/missions/{mid}/declarations-tva", headers=h,
            json={"periode": periode, "tva_collectee": "1000",
                  "tva_deductible": "0"},
        )
        assert r.status_code == 200, r.text

    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert set(corps) == {"aujourd_hui", "missions", "synthese", "note"}
    assert set(corps["synthese"]) == {
        "nb_missions", "nb_a_jour", "nb_a_completer", "nb_indisponibles",
    }
    assert corps["note"]
    entrees = [m for m in corps["missions"] if m["mission_id"] == mid]
    assert len(entrees) == 1
    e = entrees[0]
    assert set(e) == {
        "client", "mission_id", "exercice", "tva", "salaires", "statut",
    }
    assert e["client"] == "PM Portefeuille FICTIVE"
    assert e["exercice"] == 2025
    assert e["statut"] == "a_completer"
    # Cohérence stricte avec la vue mission (AUCUN recalcul divergent).
    vm = client.get(
        f"/api/v1/missions/{mid}/completude-declarative", headers=h
    ).json()
    assert e["tva"]["saisies"] == vm["impots"]["tva"]["nb_saisies"]
    assert e["tva"]["attendues"] == vm["impots"]["tva"]["nb_attendues"]
    assert e["tva"]["manquantes"] == vm["impots"]["tva"]["manquantes"]
    assert e["salaires"]["manquantes"] == (
        vm["impots"]["salaires"]["manquantes"]
    )
    assert corps["synthese"]["nb_missions"] == len(corps["missions"])
    assert corps["synthese"]["nb_a_completer"] >= 1


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(URL, headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'consultation_portefeuille_declaratif'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    charge = lignes[0]["charge_utile"]
    assert {"nb_missions", "nb_a_completer", "nb_indisponibles"} <= set(
        charge
    )
