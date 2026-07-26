"""Revue analytique N / N-1 — fonction pure + endpoint (gardes tenant)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.revue_analytique import (
    CLASSEMENT_APPARITION,
    CLASSEMENT_DISPARITION,
    CLASSEMENT_STABLE,
    CLASSEMENT_VARIATION_FORTE,
    comparer_soldes,
)


def _ligne(resultat: dict, compte: str) -> dict:
    return next(x for x in resultat["lignes"] if x["compte"] == compte)


# ── Fonction pure (sans DB) ────────────────────────────────────────


def test_apparition_compte_present_en_n_absent_en_n1():
    r = comparer_soldes(
        [{"compte": "627", "libelle": "Frais bancaires", "debit": 500000, "credit": 0}],
        [],
    )
    ligne = _ligne(r, "627")
    assert ligne["classement"] == CLASSEMENT_APPARITION
    assert ligne["solde_n"] == 500000.0
    assert ligne["solde_n1"] == 0.0
    assert ligne["variation_pct"] is None
    assert ligne["sens"] == "hausse"


def test_disparition_compte_absent_en_n_present_en_n1():
    r = comparer_soldes(
        [],
        [{"compte": "706", "libelle": "Prestations", "debit": 0, "credit": 2000000}],
    )
    ligne = _ligne(r, "706")
    assert ligne["classement"] == CLASSEMENT_DISPARITION
    assert ligne["solde_n"] == 0.0
    assert ligne["solde_n1"] == -2000000.0
    assert ligne["sens"] == "hausse"  # -2 000 000 → 0


def test_variation_forte_au_dessus_des_deux_seuils():
    # N-1 : 4 000 000 ; N : 6 000 000 → +50 % et +2 000 000 FCFA
    r = comparer_soldes(
        [{"compte": "601", "libelle": "Achats", "debit": 6000000, "credit": 0}],
        [{"compte": "601", "libelle": "Achats", "debit": 4000000, "credit": 0}],
    )
    ligne = _ligne(r, "601")
    assert ligne["classement"] == CLASSEMENT_VARIATION_FORTE
    assert ligne["variation"] == 2000000.0
    assert ligne["variation_pct"] == 50.0
    assert ligne["sens"] == "hausse"


def test_stable_sous_le_seuil_pourcentage():
    # +2 000 000 FCFA mais seulement +10 % → stable (les DEUX seuils requis)
    r = comparer_soldes(
        [{"compte": "601", "debit": 22000000, "credit": 0}],
        [{"compte": "601", "debit": 20000000, "credit": 0}],
    )
    assert _ligne(r, "601")["classement"] == CLASSEMENT_STABLE


def test_stable_sous_le_seuil_montant():
    # +50 % mais seulement +500 000 FCFA → stable
    r = comparer_soldes(
        [{"compte": "622", "debit": 1500000, "credit": 0}],
        [{"compte": "622", "debit": 1000000, "credit": 0}],
    )
    assert _ligne(r, "622")["classement"] == CLASSEMENT_STABLE


def test_tri_par_variation_absolue_decroissante():
    r = comparer_soldes(
        [
            {"compte": "601", "debit": 100, "credit": 0},
            {"compte": "701", "debit": 0, "credit": 9000000},
        ],
        [
            {"compte": "601", "debit": 5000100, "credit": 0},
            {"compte": "701", "debit": 0, "credit": 2000000},
        ],
    )
    comptes = [x["compte"] for x in r["lignes"]]
    assert comptes == ["701", "601"]  # |−7 000 000| > |−5 000 000|


def test_totaux_par_classe_1_a_7():
    r = comparer_soldes(
        [
            {"compte": "601", "debit": 3000000, "credit": 0},
            {"compte": "622", "debit": 1000000, "credit": 0},
            {"compte": "701", "debit": 0, "credit": 8000000},
            {"compte": "890", "debit": 42, "credit": 0},  # hors classes 1-7
        ],
        [
            {"compte": "601", "debit": 2000000, "credit": 0},
            {"compte": "701", "debit": 0, "credit": 5000000},
        ],
    )
    totaux = {t["classe"]: t for t in r["totaux_par_classe"]}
    assert set(totaux) == {6, 7}
    assert totaux[6]["total_n"] == 4000000.0
    assert totaux[6]["total_n1"] == 2000000.0
    assert totaux[6]["variation"] == 2000000.0
    assert totaux[7]["total_n"] == -8000000.0
    assert totaux[7]["total_n1"] == -5000000.0
    assert totaux[7]["variation"] == -3000000.0


# ── Endpoint (DB + RLS) ────────────────────────────────────────────


@pytest.fixture
def client_cab(session):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-ra-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="revue analytique")
        publier_version(session, lib, "ra@test.ci")

    def _provisionner():
        email = f"ra.{uuid.uuid4().hex[:8]}@demo.local"
        provisionner_cabinet(
            session,
            denomination=f"Cab RA {email}",
            type_tenant="cabinet",
            palier="standard",
            email_admin=email,
            mot_de_passe_admin="admin-admin1",
            creer_demo=False,
        )
        session.commit()
        client = TestClient(app)
        login = client.post(
            "/api/v1/auth/connexion",
            json={"email": email, "mot_de_passe": "admin-admin1"},
        )
        assert login.status_code == 200, login.text
        return client, {"Authorization": f"Bearer {login.json()['jeton']}"}

    return _provisionner


def _mission(client, h, *, ncc: str, exercice: int = 2025) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "dfe": f"DFE-{ncc}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": int(c.json()["id"]),
            "exercice": exercice,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "preventive",
            "perimetre_impots": ["BIC", "TVA"],
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


@pytest.mark.db
def test_endpoint_indisponible_sans_mission_n1(session, client_cab):
    client, h = client_cab()
    mid = _mission(client, h, ncc=f"CI-RA-{uuid.uuid4().hex[:6]}")

    r = client.get(f"/api/v1/missions/{mid}/revue-analytique", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disponible"] is False
    assert body["exercice_n"] == 2025
    assert body["exercice_n1"] == 2024
    assert body["mission_n1_id"] is None
    assert body["lignes"] == []
    assert body["totaux_par_classe"] == []


@pytest.mark.db
def test_endpoint_404_cross_tenant(session, client_cab):
    client_a, h_a = client_cab()
    mid_a = _mission(client_a, h_a, ncc=f"CI-RA-{uuid.uuid4().hex[:6]}")

    client_b, h_b = client_cab()
    r = client_b.get(
        f"/api/v1/missions/{mid_a}/revue-analytique", headers=h_b
    )
    assert r.status_code == 404, r.text
