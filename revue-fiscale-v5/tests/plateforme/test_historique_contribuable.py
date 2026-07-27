"""Historique pluriannuel contribuable : tendances, RLS, auth."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.historique_contribuable import (  # noqa: E402
    calculer_tendances,
)
from tests.plateforme.test_comparatif_executions import (  # noqa: E402
    _conclusion,
    _execution,
)
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _creer_regle_version,
    _version_brouillon_test,
)


def _contribuable(client: TestClient, h: dict[str, str]) -> int:
    suffixe = uuid.uuid4().hex[:6].upper()
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM Historique FICTIF {suffixe}",
            "ncc": f"CI-HIS-{suffixe}",
            "forme": "pm",
            "rccm": f"CI-RCCM-HIS-{suffixe}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan Plateau",
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


def _mission_exercice(
    client: TestClient, h: dict[str, str], contribuable_id: int, exercice: int
) -> int:
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": contribuable_id,
            "type_engagement": "preventive",
            "exercice": exercice,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def _regles(session, n: int, suffixe: str) -> list[int]:
    vr = _version_brouillon_test(session)
    rvs = [
        _creer_regle_version(
            session, vr, f"HIS-{i}-{suffixe}", f"Règle historique {i}"
        )
        for i in range(n)
    ]
    session.commit()
    return rvs


# ── Fonction pure ──────────────────────────────────────────────────


def test_calculer_tendances_pure():
    assert calculer_tendances([]) == []
    assert calculer_tendances([2]) == [None]
    assert calculer_tendances([2, 3, 3, 1, 1]) == [
        None,
        "hausse",
        "stable",
        "baisse",
        "stable",
    ]
    assert calculer_tendances([0, 0]) == [None, "stable"]


# ── Scénario pluriannuel ───────────────────────────────────────────


def test_historique_pluriannuel_tendances_et_montants(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    cid = _contribuable(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    rvs = _regles(session, 7, suffixe)

    # 2023 : 1 exécution — 2 anomalies (1000 + 500) + 1 conforme.
    m2023 = _mission_exercice(client, h, cid, 2023)
    e23 = _execution(session, tid, m2023)
    _conclusion(session, tid, e23, rvs[0], "anomalie", "1000")
    _conclusion(session, tid, e23, rvs[1], "anomalie", "500")
    _conclusion(session, tid, e23, rvs[2], "conforme")

    # 2024 : 2 exécutions — la dernière compte 1 anomalie (200),
    # 1 non_verifiable et 1 sous_seuil (bucket « autres »).
    m2024 = _mission_exercice(client, h, cid, 2024)
    e24a = _execution(session, tid, m2024)
    _conclusion(session, tid, e24a, rvs[3], "anomalie", "999")
    e24b = _execution(session, tid, m2024)
    _conclusion(session, tid, e24b, rvs[4], "anomalie", "200")
    _conclusion(session, tid, e24b, rvs[5], "non_verifiable")
    _conclusion(session, tid, e24b, rvs[6], "sous_seuil")

    # 2025 : mission sans exécution.
    m2025 = _mission_exercice(client, h, cid, 2025)

    # Risques : un ouvert (repris), un résolu (exclu).
    from backend.plateforme.risques import creer_risque

    ouvert = creer_risque(
        session,
        tid,
        contribuable_id=cid,
        impot="BIC",
        libelle="Charge non déductible récurrente",
        exercice_origine=2023,
        montant_estime=Decimal("300000"),
    )
    creer_risque(
        session,
        tid,
        contribuable_id=cid,
        impot="TVA",
        libelle="TVA déjà régularisée",
        exercice_origine=2024,
        statut="resolu",
    )
    session.commit()

    resp = client.get(f"/api/v1/contribuables/{cid}/historique", headers=h)
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["contribuable"]["id"] == cid
    assert "Historique FICTIF" in out["contribuable"]["denomination"]
    assert out["contribuable"]["ncc"].startswith("CI-HIS-")

    exercices = out["exercices"]
    assert [e["exercice"] for e in exercices] == [2023, 2024, 2025]

    ex23, ex24, ex25 = exercices
    assert ex23["mission_id"] == m2023
    assert ex23["nb_executions"] == 1
    assert ex23["derniere_execution_id"] == e23
    assert ex23["conclusions"] == {
        "anomalie": 2,
        "non_verifiable": 0,
        "conforme": 1,
        "autres": 0,
    }
    assert Decimal(ex23["montant_anomalies"]) == Decimal("1500")
    assert ex23["tendance_anomalies"] is None
    # 3 conclusions à niveau « moyen » (poids 2) → score heuristique 6.
    assert ex23["score_risque"] == 6

    assert ex24["nb_executions"] == 2
    assert ex24["derniere_execution_id"] == e24b
    assert ex24["conclusions"] == {
        "anomalie": 1,
        "non_verifiable": 1,
        "conforme": 0,
        "autres": 1,
    }
    assert Decimal(ex24["montant_anomalies"]) == Decimal("200")
    assert ex24["tendance_anomalies"] == "baisse"

    assert ex25["mission_id"] == m2025
    assert ex25["nb_executions"] == 0
    assert ex25["derniere_execution_id"] is None
    assert ex25["conclusions"]["anomalie"] == 0
    assert ex25["score_risque"] is None
    assert ex25["tendance_anomalies"] == "baisse"

    # Risques ouverts : seul le non clos est repris.
    ids_ouverts = [r["id"] for r in out["risques_ouverts"]]
    assert ouvert["id"] in ids_ouverts
    reprise = next(r for r in out["risques_ouverts"] if r["id"] == ouvert["id"])
    assert reprise["impot"] == "BIC"
    assert reprise["exercice_origine"] == 2023
    assert reprise["statut"] == "ouvert"
    assert Decimal(reprise["montant_estime"]) == Decimal("300000")
    assert all(
        r["statut"] in {"ouvert", "en_traitement"}
        for r in out["risques_ouverts"]
    )

    assert out["synthese"] == {
        "nb_exercices": 3,
        "total_anomalies_dernier_exercice": 0,
        "exercices_avec_anomalies": 2,
    }


def test_historique_contribuable_sans_mission(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    cid = _contribuable(client, h)

    resp = client.get(f"/api/v1/contribuables/{cid}/historique", headers=h)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["exercices"] == []
    assert out["risques_ouverts"] == []
    assert out["synthese"] == {
        "nb_exercices": 0,
        "total_anomalies_dernier_exercice": 0,
        "exercices_avec_anomalies": 0,
    }


def test_historique_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _tid_a = _connexion(client, email_a)
    h_b, _tid_b = _connexion(client, email_b)
    cid = _contribuable(client, h_a)

    resp = client.get(f"/api/v1/contribuables/{cid}/historique", headers=h_b)
    assert resp.status_code == 404, resp.text
    assert "introuvable" in resp.json()["detail"]


def test_historique_auth_requise():
    client = TestClient(app)
    resp = client.get("/api/v1/contribuables/1/historique")
    assert resp.status_code == 401, resp.text
