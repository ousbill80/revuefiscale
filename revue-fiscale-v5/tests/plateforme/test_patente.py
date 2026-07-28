"""Estimation consultative de la contribution des patentes."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.patente import (
    MOTIF_VALEUR_LOCATIVE_NON_CALCULABLE,
    NOTE_PATENTE,
    PLAFOND_DROIT_CA_INDICATIF_FCFA,
    PLANCHER_DROIT_CA_FCFA,
    STATUT_ESTIMEE,
    STATUT_INDISPONIBLE,
    TAUX_DROIT_CA,
    arrondir_franc,
    calculer_droit_chiffre_affaires,
    calculer_estimation_patente,
    extraire_chiffre_affaires,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_constantes_cgi():
    assert str(TAUX_DROIT_CA) == "0.005"
    assert str(PLANCHER_DROIT_CA_FCFA) == "300000"
    assert PLAFOND_DROIT_CA_INDICATIF_FCFA > PLANCHER_DROIT_CA_FCFA


def test_arrondir_franc():
    assert arrondir_franc(Decimal("1234.49")) == Decimal("1234")
    assert arrondir_franc(Decimal("1234.50")) == Decimal("1235")


def test_extraire_chiffre_affaires_comptes_70x():
    soldes = [
        {"compte": "701", "libelle": "Ventes march.", "debit": "0",
         "credit": "80000000"},
        {"compte": "706", "libelle": "Services", "debit": "0",
         "credit": "20000000"},
        # RRR accordés 709x : débiteur, vient en moins du CA.
        {"compte": "7091", "libelle": "RRR accordés",
         "debit": "5000000", "credit": "0"},
        # Hors 70x : ignorés (71x subventions, 77x financiers, 6x…).
        {"compte": "718", "libelle": "Subventions", "debit": "0",
         "credit": "999999"},
        {"compte": "771", "libelle": "Intérêts", "debit": "0",
         "credit": "888888"},
        {"compte": "601", "libelle": "Achats", "debit": "1", "credit": "0"},
    ]
    ca = extraire_chiffre_affaires(soldes)
    assert ca["chiffre_affaires"] == Decimal("95000000")
    assert ca["nb_comptes_ca"] == 3
    assert ca["disponible"] is True
    assert [c["compte"] for c in ca["comptes"]] == ["701", "706", "7091"]
    assert ca["comptes"][2]["solde"] == Decimal("-5000000")


def test_extraire_chiffre_affaires_indisponible():
    vide = extraire_chiffre_affaires([])
    assert vide["disponible"] is False
    assert vide["chiffre_affaires"] == Decimal("0")
    sans_70 = extraire_chiffre_affaires(
        [{"compte": "771", "libelle": "x", "debit": "0", "credit": "1"}]
    )
    assert sans_70["disponible"] is False


def test_droit_ca_taux_general():
    # 200 000 000 × 0,5 % = 1 000 000 — entre plancher et plafond.
    d = calculer_droit_chiffre_affaires(Decimal("200000000"))
    assert d["droit_theorique"] == Decimal("1000000")
    assert d["droit_retenu"] == Decimal("1000000")
    assert d["plancher_applique"] is False
    assert d["plafond_applique"] is False


def test_droit_ca_plancher_300000():
    # 40 000 000 × 0,5 % = 200 000 < 300 000 → plancher appliqué.
    d = calculer_droit_chiffre_affaires(Decimal("40000000"))
    assert d["droit_theorique"] == Decimal("200000")
    assert d["droit_retenu"] == PLANCHER_DROIT_CA_FCFA
    assert d["plancher_applique"] is True
    assert d["plafond_applique"] is False
    # CA nul ou négatif : jamais de droit négatif, plancher appliqué.
    for ca in (Decimal("0"), Decimal("-5000000")):
        d0 = calculer_droit_chiffre_affaires(ca)
        assert d0["droit_theorique"] == Decimal("0")
        assert d0["droit_retenu"] == PLANCHER_DROIT_CA_FCFA
        assert d0["plancher_applique"] is True


def test_droit_ca_plafond_indicatif():
    # 1 000 000 000 × 0,5 % = 5 000 000 > plafond → plafonné.
    d = calculer_droit_chiffre_affaires(Decimal("1000000000"))
    assert d["droit_theorique"] == Decimal("5000000")
    assert d["droit_retenu"] == PLAFOND_DROIT_CA_INDICATIF_FCFA
    assert d["plafond_applique"] is True
    assert d["plancher_applique"] is False


def test_droit_ca_arrondi_au_franc():
    # 123 456 789 × 0,5 % = 617 283,945 → 617 284 (half-up).
    d = calculer_droit_chiffre_affaires(Decimal("123456789"))
    assert d["droit_theorique"] == Decimal("617284")


def test_estimation_complete_estimee():
    soldes = [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "200000000"},
    ]
    vue = calculer_estimation_patente(soldes)
    assert vue["disponible"] is True
    assert vue["chiffre_affaires"] == "200000000"
    assert vue["taux"] == "0.005"
    assert vue["droit_chiffre_affaires"] == "1000000"
    assert vue["plancher_applique"] is False
    assert vue["plafond_applique"] is False
    # VL : jamais calculée, motif explicite.
    assert vue["droit_valeur_locative"]["calculable"] is False
    assert vue["droit_valeur_locative"]["motif"] == (
        MOTIF_VALEUR_LOCATIVE_NON_CALCULABLE
    )
    # Total partiel = droit CA seul (la VL manque, assumé).
    assert vue["estimation_totale_partielle"] == "1000000"
    assert vue["synthese"]["statut"] == STATUT_ESTIMEE
    assert vue["synthese"]["nb_comptes_ca"] == 1
    assert vue["note"] == NOTE_PATENTE
    assert any(
        "274" in r["reference"] for r in vue["references"]
    )


def test_estimation_plancher_signale():
    soldes = [
        {"compte": "706", "libelle": "Services", "debit": "0",
         "credit": "10000000"},
    ]
    vue = calculer_estimation_patente(soldes)
    # 10 000 000 × 0,5 % = 50 000 → plancher 300 000.
    assert vue["droit_chiffre_affaires"] == "300000"
    assert vue["plancher_applique"] is True
    assert vue["estimation_totale_partielle"] == "300000"


def test_estimation_indisponible_cles_stables():
    cles = {
        "disponible", "chiffre_affaires", "comptes_ca", "taux",
        "droit_chiffre_affaires", "plancher_applique",
        "plafond_applique", "plancher_fcfa", "plafond_indicatif_fcfa",
        "droit_valeur_locative", "estimation_totale_partielle",
        "synthese", "note", "references",
    }
    vue = calculer_estimation_patente([])
    assert cles <= set(vue)
    assert vue["disponible"] is False
    assert vue["synthese"]["statut"] == STATUT_INDISPONIBLE
    # Rien n'est inventé sans balance : aucun montant chiffré.
    assert vue["droit_chiffre_affaires"] == "0"
    assert vue["estimation_totale_partielle"] == "0"
    assert vue["plancher_applique"] is False
    assert vue["droit_valeur_locative"]["calculable"] is False
    assert vue["note"] == NOTE_PATENTE
    assert vue["references"]


def test_note_consultative_humain_decide():
    assert "consultati" in NOTE_PATENTE
    assert "décide" in NOTE_PATENTE
    assert "partielle" in NOTE_PATENTE


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

    lib = f"v-pat-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="patente")
    publier_version(session, lib, "pat@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"pat.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Patente {email}",
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
    return f"/api/v1/missions/{mid}/patente"


def test_api_estimation_structure_complete(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Patente FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "150000000")
    _solde(session, tid, mid, "706", "Services", "0", "50000000")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    # CA 70x : 150M + 50M = 200 000 000 (601 ignoré).
    assert corps["chiffre_affaires"] == "200000000.00"
    assert corps["taux"] == "0.005"
    # 200M × 0,5 % = 1 000 000 — entre plancher et plafond.
    assert corps["droit_chiffre_affaires"] == "1000000"
    assert corps["plancher_applique"] is False
    assert corps["plafond_applique"] is False
    assert corps["estimation_totale_partielle"] == "1000000"
    assert corps["droit_valeur_locative"]["calculable"] is False
    assert "valeur locative" in corps["droit_valeur_locative"]["motif"]
    assert corps["synthese"]["statut"] == "estimation_partielle"
    assert corps["synthese"]["nb_comptes_ca"] == 2
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_tolerance_sans_balance(session):
    # Tolérance : sans comptes 70x, la vue se sert quand même —
    # disponible=false, clés stables, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Patente Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["droit_chiffre_affaires"] == "0"
    assert corps["estimation_totale_partielle"] == "0"
    assert corps["droit_valeur_locative"]["calculable"] is False
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Patente Journal FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "10000000")
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
                    "AND action = 'consultation_patente'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_patente" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM Patente Cross FICTIF")
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
