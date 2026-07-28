"""Retenue à la source sur honoraires — vue consultative (balance)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.retenue_honoraires import (
    MOTIF_REGIME_PRESTATAIRE_NON_CALCULABLE,
    NOTE_RETENUE_HONORAIRES,
    STATUT_A_QUALIFIER,
    STATUT_INDISPONIBLE,
    TAUX_RETENUE_HONORAIRES,
    calculer_retenue_theorique_max,
    evaluer_retenue_honoraires,
    extraire_honoraires,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_constantes():
    assert str(TAUX_RETENUE_HONORAIRES) == "0.075"


def test_extraction_comptes_632_seulement():
    soldes = [
        {"compte": "6324", "libelle": "Honoraires",
         "debit": "8000000", "credit": "0"},
        {"compte": "632200", "libelle": "Commissions et courtages",
         "debit": "3000000", "credit": "500000"},
        {"compte": "633", "libelle": "Frais de formation",
         "debit": "999999", "credit": "0"},
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "50000000"},
    ]
    honoraires = extraire_honoraires(soldes)
    assert honoraires["honoraires_bruts"] == Decimal("10500000")
    assert honoraires["nb_comptes_honoraires"] == 2
    assert honoraires["disponible"] is True
    assert [c["compte"] for c in honoraires["comptes"]] == [
        "6324", "632200",
    ]


def test_extraction_vide_indisponible():
    honoraires = extraire_honoraires(
        [{"compte": "601", "libelle": "Achats", "debit": "1",
          "credit": "0"}]
    )
    assert honoraires["honoraires_bruts"] == Decimal("0")
    assert honoraires["disponible"] is False


def test_retenue_theorique_max_sept_virgule_cinq_pct():
    # 12 000 000 × 7,5 % = 900 000 — arrondi au franc.
    assert calculer_retenue_theorique_max(
        Decimal("12000000")
    ) == Decimal("900000")
    # Arrondi : 1 000 001 × 0,075 = 75 000,075 → 75 000.
    assert calculer_retenue_theorique_max(
        Decimal("1000001")
    ) == Decimal("75000")


def test_retenue_theorique_assiette_negative_ramenee_a_zero():
    # Solde 632x créditeur net (avoirs) : aucune retenue négative.
    assert calculer_retenue_theorique_max(
        Decimal("-500000")
    ) == Decimal("0")


def test_vue_disponible_statut_a_qualifier():
    vue = evaluer_retenue_honoraires(
        [{"compte": "6324", "libelle": "Honoraires conseil",
          "debit": "12000000", "credit": "0"}]
    )
    assert vue["disponible"] is True
    assert vue["honoraires_bruts"] == "12000000"
    assert vue["retenue_theorique_max"] == "900000"
    assert vue["taux_indicatif"] == "0.075"
    assert vue["statut"] == STATUT_A_QUALIFIER
    # Jamais accusatoire : l'humain qualifie et décide.
    assert "qualifier" in vue["synthese"]["libelle_statut"]
    assert "décide" in vue["synthese"]["libelle_statut"]


def test_vue_indisponible_sans_632x():
    vue = evaluer_retenue_honoraires([])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["honoraires_bruts"] == "0"
    assert vue["retenue_theorique_max"] == "0"
    assert vue["comptes_honoraires"] == []


def test_repartition_par_prestataire_jamais_calculable():
    # Le régime du prestataire (résident/non-résident, immatriculé ou
    # non) est absent de la balance : la répartition n'est JAMAIS
    # calculée ni inventée.
    for vue in (
        evaluer_retenue_honoraires([]),
        evaluer_retenue_honoraires(
            [{"compte": "6324", "libelle": "Honoraires", "debit": "100",
              "credit": "0"}]
        ),
    ):
        rep = vue["repartition_par_prestataire"]
        assert rep["calculable"] is False
        assert rep["motif"] == MOTIF_REGIME_PRESTATAIRE_NON_CALCULABLE
        assert "prestataire" in rep["motif"]


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "honoraires_bruts", "comptes_honoraires",
        "taux_indicatif", "retenue_theorique_max",
        "repartition_par_prestataire", "statut", "synthese", "note",
        "references",
    }
    for vue in (
        evaluer_retenue_honoraires([]),
        evaluer_retenue_honoraires(
            [{"compte": "6324", "libelle": "Honoraires",
              "debit": "1000", "credit": "0"}]
        ),
    ):
        assert cles <= set(vue)
        assert vue["taux_indicatif"] == "0.075"
        assert vue["note"] == NOTE_RETENUE_HONORAIRES
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]


def test_montants_serialises_en_str():
    vue = evaluer_retenue_honoraires(
        [{"compte": "6324", "libelle": "Honoraires",
          "debit": "12000000", "credit": "0"}]
    )
    assert isinstance(vue["honoraires_bruts"], str)
    assert isinstance(vue["retenue_theorique_max"], str)
    assert all(
        isinstance(c["solde"], str) for c in vue["comptes_honoraires"]
    )


def test_note_limite_documentee_et_non_accusatoire():
    assert "consultati" in NOTE_RETENUE_HONORAIRES
    assert "632x" in NOTE_RETENUE_HONORAIRES
    assert "MAXIMALE" in NOTE_RETENUE_HONORAIRES
    assert "régime du prestataire" in NOTE_RETENUE_HONORAIRES
    assert "à expliquer" in NOTE_RETENUE_HONORAIRES
    assert "font foi" in NOTE_RETENUE_HONORAIRES
    assert "décide" in NOTE_RETENUE_HONORAIRES


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

    lib = f"v-rhon-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="retenue honoraires")
    publier_version(session, lib, "rhon@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rhon.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RetenueHonoraires {email}",
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


def _solde(session, tenant_id: int, mission_id: int, compte: str,
           libelle: str, debit: str, credit: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO solde_compte (tenant_id, mission_id, "
                "compte, libelle, debit, credit) "
                "VALUES (:t, :m, :c, :l, :d, :cr)"
            ),
            {"t": tenant_id, "m": mission_id, "c": compte, "l": libelle,
             "d": debit, "cr": credit},
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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/retenue-honoraires"


def test_api_structure_complete(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueHonoraires FICTIVE")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "6324", "Honoraires conseil FICTIF",
           "12000000", "0")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["honoraires_bruts"] == "12000000.00"
    assert corps["taux_indicatif"] == "0.075"
    # 12 000 000 × 7,5 % = 900 000 (maximum théorique indicatif).
    assert corps["retenue_theorique_max"] == "900000"
    assert corps["statut"] == "a_qualifier"
    assert corps["synthese"]["nb_comptes_honoraires"] == 1
    assert corps["repartition_par_prestataire"]["calculable"] is False
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_tolerance_sans_balance(session):
    # Tolérance : sans balance, la vue se sert quand même —
    # disponible=false, clés stables, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueHonoraires Vide FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["honoraires_bruts"] == "0"
    assert corps["retenue_theorique_max"] == "0"
    assert corps["repartition_par_prestataire"]["calculable"] is False
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueHonoraires Journal FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(mid), headers=h).status_code == 200

    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m "
                    "AND action = 'consultation_retenue_honoraires'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_retenue_honoraires" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(
        session, tid_a, "PM RetenueHonoraires Cross FICTIVE"
    )
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
