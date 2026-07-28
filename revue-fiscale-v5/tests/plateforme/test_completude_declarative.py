"""Complétude déclarative mensuelle — périodes échues sans déclaration."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.completude_declarative import (
    NOTE_COMPLETUDE_DECLARATIVE,
    STATUT_AUCUNE_SAISIE,
    STATUT_COMPLET,
    STATUT_LACUNAIRE,
    STATUT_SANS_PERIODE_ECHUE,
    comparer,
    construire_completude,
    generer_periodes,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_generer_periodes_exercice_passe_12_mois():
    periodes = generer_periodes(2025, date(2026, 7, 28))
    assert len(periodes) == 12
    assert periodes[0] == "2025-01"
    assert periodes[-1] == "2025-12"


def test_generer_periodes_exercice_en_cours_seulement_echues():
    # Au 28/07/2026, seules janvier → juin 2026 sont échues (période
    # strictement antérieure au mois courant).
    periodes = generer_periodes(2026, date(2026, 7, 28))
    assert periodes == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
    ]


def test_generer_periodes_janvier_aucune_echue():
    assert generer_periodes(2026, date(2026, 1, 15)) == []


def test_generer_periodes_exercice_futur_vide():
    assert generer_periodes(2027, date(2026, 7, 28)) == []


def test_comparer_complet():
    attendues = ["2025-01", "2025-02", "2025-03"]
    vue = comparer(attendues, ["2025-03", "2025-01", "2025-02"])
    assert vue["statut"] == STATUT_COMPLET
    assert vue["manquantes"] == []
    assert vue["taux_couverture"] == "100.0"
    assert vue["nb_attendues"] == 3
    assert vue["nb_manquantes"] == 0


def test_comparer_lacunaire_et_taux_point_machine():
    attendues = ["2025-01", "2025-02", "2025-03"]
    vue = comparer(attendues, ["2025-02"])
    assert vue["statut"] == STATUT_LACUNAIRE
    assert vue["manquantes"] == ["2025-01", "2025-03"]
    # 1/3 couvert → 33.3, format machine à point, 1 décimale.
    assert vue["taux_couverture"] == "33.3"
    assert "," not in vue["taux_couverture"]


def test_comparer_aucune_saisie():
    vue = comparer(["2025-01", "2025-02"], [])
    assert vue["statut"] == STATUT_AUCUNE_SAISIE
    assert vue["taux_couverture"] == "0.0"
    assert vue["manquantes"] == ["2025-01", "2025-02"]


def test_comparer_sans_periode_echue():
    vue = comparer([], ["2025-01"])
    assert vue["statut"] == STATUT_SANS_PERIODE_ECHUE
    assert vue["attendues"] == []
    assert vue["manquantes"] == []
    assert vue["taux_couverture"] == "0.0"


def test_comparer_saisie_hors_perimetre_non_comptee():
    # Une saisie hors des périodes attendues ne couvre rien.
    vue = comparer(["2025-01", "2025-02"], ["2024-12", "2025-01"])
    assert vue["statut"] == STATUT_LACUNAIRE
    assert vue["manquantes"] == ["2025-02"]
    assert vue["taux_couverture"] == "50.0"
    assert vue["saisies"] == ["2024-12", "2025-01"]


def test_comparer_dedoublonne():
    vue = comparer(["2025-01"], ["2025-01", "2025-01"])
    assert vue["nb_saisies"] == 1
    assert vue["statut"] == STATUT_COMPLET


def test_construire_completude_cles_stables_et_statut_global():
    aujourd_hui = date(2026, 7, 28)
    vue = construire_completude(
        2025, aujourd_hui,
        periodes_tva=[f"2025-{m:02d}" for m in range(1, 13)],
        periodes_salaires=["2025-01"],
    )
    cles = {
        "disponible", "exercice", "aujourd_hui", "impots",
        "synthese", "note", "references",
    }
    assert cles <= set(vue)
    assert vue["disponible"] is True
    assert vue["exercice"] == 2025
    assert vue["aujourd_hui"] == "2026-07-28"
    assert set(vue["impots"]) == {"tva", "salaires"}
    assert vue["impots"]["tva"]["statut"] == STATUT_COMPLET
    assert vue["impots"]["salaires"]["statut"] == STATUT_LACUNAIRE
    assert vue["synthese"]["statut_global"] == STATUT_LACUNAIRE
    assert vue["synthese"]["nb_manquantes_total"] == 11
    assert vue["note"] == NOTE_COMPLETUDE_DECLARATIVE
    assert vue["references"]


def test_construire_completude_aucune_saisie_globale():
    vue = construire_completude(
        2025, date(2026, 7, 28), periodes_tva=[], periodes_salaires=[]
    )
    assert vue["synthese"]["statut_global"] == STATUT_AUCUNE_SAISIE
    assert vue["synthese"]["nb_manquantes_total"] == 24


def test_construire_completude_exercice_futur():
    vue = construire_completude(
        2027, date(2026, 7, 28), periodes_tva=[], periodes_salaires=[]
    )
    assert vue["synthese"]["statut_global"] == STATUT_SANS_PERIODE_ECHUE
    assert vue["synthese"]["nb_manquantes_total"] == 0
    assert vue["impots"]["tva"]["statut"] == STATUT_SANS_PERIODE_ECHUE


def test_construire_completude_tolerance_par_bloc():
    # Bloc TVA illisible (None) : le bloc est indisponible mais la vue
    # tient debout et le bloc salaires reste exploité.
    vue = construire_completude(
        2025, date(2026, 7, 28),
        periodes_tva=None,
        periodes_salaires=[f"2025-{m:02d}" for m in range(1, 13)],
    )
    assert vue["disponible"] is True
    assert vue["impots"]["tva"]["disponible"] is False
    assert vue["impots"]["salaires"]["disponible"] is True
    assert vue["synthese"]["statut_global"] == STATUT_COMPLET
    assert vue["synthese"]["nb_manquantes_total"] == 0
    # Les deux blocs illisibles : vue indisponible mais clés stables.
    vue2 = construire_completude(
        2025, date(2026, 7, 28), periodes_tva=None, periodes_salaires=None
    )
    assert vue2["disponible"] is False
    assert vue2["synthese"]["statut_global"] == STATUT_AUCUNE_SAISIE
    assert vue2["note"] == NOTE_COMPLETUDE_DECLARATIVE


def test_note_consultative_quittances():
    assert "consultatif" in NOTE_COMPLETUDE_DECLARATIVE
    assert "quittances" in NOTE_COMPLETUDE_DECLARATIVE
    assert "DGI" in NOTE_COMPLETUDE_DECLARATIVE


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
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-cdec-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="completude-declarative")
    publier_version(session, lib, "cdec@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"cdec.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CDec {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _contribuable(session, tenant_id: int, nom: str) -> int:
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
    return int(cid)


def _mission(session, tenant_id: int, contribuable_id: int,
             exercice: int = 2025) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/completude-declarative"


def test_api_structure_et_periodes_manquantes(session):
    # L'exercice 2025 est passé (date système ≥ 2026) : 12 périodes
    # attendues par impôt ; on saisit 2 périodes TVA et 1 salaires.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CDec FICTIF")
    mid = _mission(session, tid, cid, exercice=2025)
    session.commit()

    client, h = _client_connecte(email)
    for periode in ("2025-01", "2025-02"):
        r = client.post(
            f"/api/v1/missions/{mid}/declarations-tva", headers=h,
            json={"periode": periode, "tva_collectee": "1000",
                  "tva_deductible": "0"},
        )
        assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/missions/{mid}/declarations-salaires", headers=h,
        json={"periode": "2025-01", "masse_salariale_brute": "500000",
              "its_retenu": "10000"},
    )
    assert r.status_code == 200, r.text

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["aujourd_hui"]
    tva = corps["impots"]["tva"]
    assert tva["nb_attendues"] == 12
    assert tva["saisies"] == ["2025-01", "2025-02"]
    assert tva["nb_manquantes"] == 10
    assert tva["manquantes"][0] == "2025-03"
    assert tva["statut"] == "lacunaire"
    assert tva["taux_couverture"] == "16.7"
    salaires = corps["impots"]["salaires"]
    assert salaires["nb_manquantes"] == 11
    assert salaires["statut"] == "lacunaire"
    assert corps["synthese"]["statut_global"] == "lacunaire"
    assert corps["synthese"]["nb_manquantes_total"] == 21
    assert "quittances" in corps["note"]
    assert corps["references"]


def test_api_sans_saisie_stable_et_tolerant(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CDec Vide FICTIF")
    mid = _mission(session, tid, cid, exercice=2025)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    cles = {
        "mission_id", "disponible", "exercice", "aujourd_hui",
        "impots", "synthese", "note", "references",
    }
    assert cles <= set(corps)
    assert corps["synthese"]["statut_global"] == "aucune_saisie"
    assert corps["impots"]["tva"]["statut"] == "aucune_saisie"
    assert corps["impots"]["salaires"]["saisies"] == []
    assert corps["note"] == NOTE_COMPLETUDE_DECLARATIVE


def test_api_exercice_futur_sans_periode_echue(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CDec Futur FICTIF")
    # creer_mission refuse un exercice non clos : on force l'exercice
    # futur en SQL pour éprouver la branche « sans_periode_echue ».
    mid = _mission(session, tid, cid, exercice=date.today().year - 1)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET exercice = :e WHERE id = :m"),
            {"e": date.today().year + 1, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    corps = client.get(_url(mid), headers=h).json()
    assert corps["synthese"]["statut_global"] == "sans_periode_echue"
    assert corps["synthese"]["nb_manquantes_total"] == 0
    assert corps["impots"]["tva"]["attendues"] == []


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM CDec Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
