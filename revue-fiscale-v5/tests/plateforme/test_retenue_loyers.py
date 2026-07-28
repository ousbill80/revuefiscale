"""Retenue à la source sur loyers — vue consultative depuis la balance."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.retenue_loyers import (
    MOTIF_QUALITE_BAILLEUR_NON_CALCULABLE,
    NOTE_RETENUE_LOYERS,
    STATUT_A_QUALIFIER,
    STATUT_INDISPONIBLE,
    TAUX_RETENUE_LOYERS,
    calculer_retenue_theorique_max,
    evaluer_retenue_loyers,
    extraire_charges_locatives,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_constantes():
    assert str(TAUX_RETENUE_LOYERS) == "0.15"


def test_extraction_comptes_622_seulement():
    soldes = [
        {"compte": "6221", "libelle": "Location bâtiments",
         "debit": "12000000", "credit": "0"},
        {"compte": "622300", "libelle": "Location matériel",
         "debit": "3000000", "credit": "500000"},
        {"compte": "623", "libelle": "Entretien", "debit": "999999",
         "credit": "0"},
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "50000000"},
    ]
    charges = extraire_charges_locatives(soldes)
    assert charges["loyers_bruts"] == Decimal("14500000")
    assert charges["nb_comptes_loyers"] == 2
    assert charges["disponible"] is True
    assert [c["compte"] for c in charges["comptes"]] == [
        "6221", "622300",
    ]


def test_extraction_vide_indisponible():
    charges = extraire_charges_locatives(
        [{"compte": "601", "libelle": "Achats", "debit": "1",
          "credit": "0"}]
    )
    assert charges["loyers_bruts"] == Decimal("0")
    assert charges["disponible"] is False


def test_retenue_theorique_max_quinze_pct():
    # 12 000 000 × 15 % = 1 800 000 — arrondi au franc.
    assert calculer_retenue_theorique_max(
        Decimal("12000000")
    ) == Decimal("1800000")
    # Arrondi : 1 000 001 × 0,15 = 150 000,15 → 150 000.
    assert calculer_retenue_theorique_max(
        Decimal("1000001")
    ) == Decimal("150000")


def test_retenue_theorique_assiette_negative_ramenee_a_zero():
    # Solde 622x créditeur net (avoirs) : aucune retenue négative.
    assert calculer_retenue_theorique_max(
        Decimal("-500000")
    ) == Decimal("0")


def test_vue_disponible_statut_a_qualifier():
    vue = evaluer_retenue_loyers(
        [{"compte": "6221", "libelle": "Location siège",
          "debit": "12000000", "credit": "0"}]
    )
    assert vue["disponible"] is True
    assert vue["loyers_bruts"] == "12000000"
    assert vue["retenue_theorique_max"] == "1800000"
    assert vue["taux_indicatif"] == "0.15"
    assert vue["statut"] == STATUT_A_QUALIFIER
    # Jamais accusatoire : l'humain qualifie et décide.
    assert "qualifier" in vue["synthese"]["libelle_statut"]
    assert "décide" in vue["synthese"]["libelle_statut"]


def test_vue_indisponible_sans_622x():
    vue = evaluer_retenue_loyers([])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["loyers_bruts"] == "0"
    assert vue["retenue_theorique_max"] == "0"
    assert vue["comptes_loyers"] == []


def test_repartition_par_bailleur_jamais_calculable():
    # La qualité du bailleur (PP/PM, régime) est absente de la
    # balance : la répartition n'est JAMAIS calculée ni inventée.
    for vue in (
        evaluer_retenue_loyers([]),
        evaluer_retenue_loyers(
            [{"compte": "6221", "libelle": "Loyer", "debit": "100",
              "credit": "0"}]
        ),
    ):
        rep = vue["repartition_par_bailleur"]
        assert rep["calculable"] is False
        assert rep["motif"] == MOTIF_QUALITE_BAILLEUR_NON_CALCULABLE
        assert "bailleur" in rep["motif"]


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "loyers_bruts", "comptes_loyers",
        "taux_indicatif", "retenue_theorique_max",
        "repartition_par_bailleur", "statut", "synthese", "note",
        "references",
    }
    for vue in (
        evaluer_retenue_loyers([]),
        evaluer_retenue_loyers(
            [{"compte": "6221", "libelle": "Loyer", "debit": "1000",
              "credit": "0"}]
        ),
    ):
        assert cles <= set(vue)
        assert vue["taux_indicatif"] == "0.15"
        assert vue["note"] == NOTE_RETENUE_LOYERS
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]


def test_montants_serialises_en_str():
    vue = evaluer_retenue_loyers(
        [{"compte": "6221", "libelle": "Loyer", "debit": "12000000",
          "credit": "0"}]
    )
    assert isinstance(vue["loyers_bruts"], str)
    assert isinstance(vue["retenue_theorique_max"], str)
    assert all(
        isinstance(c["solde"], str) for c in vue["comptes_loyers"]
    )


def test_note_limite_documentee_et_non_accusatoire():
    assert "consultati" in NOTE_RETENUE_LOYERS
    assert "622x" in NOTE_RETENUE_LOYERS
    assert "MAXIMALE" in NOTE_RETENUE_LOYERS
    assert "qualité du bailleur" in NOTE_RETENUE_LOYERS
    assert "à expliquer" in NOTE_RETENUE_LOYERS
    assert "décide" in NOTE_RETENUE_LOYERS


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

    lib = f"v-rloy-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="retenue loyers")
    publier_version(session, lib, "rloy@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rloy.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RetenueLoyers {email}",
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
    return f"/api/v1/missions/{mid}/retenue-loyers"


def test_api_structure_complete(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueLoyers FICTIVE")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "6221", "Location siège FICTIVE",
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
    assert corps["loyers_bruts"] == "12000000.00"
    assert corps["taux_indicatif"] == "0.15"
    # 12 000 000 × 15 % = 1 800 000 (maximum théorique indicatif).
    assert corps["retenue_theorique_max"] == "1800000"
    assert corps["statut"] == "a_qualifier"
    assert corps["synthese"]["nb_comptes_loyers"] == 1
    assert corps["repartition_par_bailleur"]["calculable"] is False
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_tolerance_sans_balance(session):
    # Tolérance : sans balance, la vue se sert quand même —
    # disponible=false, clés stables, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueLoyers Vide FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["loyers_bruts"] == "0"
    assert corps["retenue_theorique_max"] == "0"
    assert corps["repartition_par_bailleur"]["calculable"] is False
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RetenueLoyers Journal FICTIVE")
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
                    "AND action = 'consultation_retenue_loyers'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_retenue_loyers" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM RetenueLoyers Cross FICTIVE")
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
