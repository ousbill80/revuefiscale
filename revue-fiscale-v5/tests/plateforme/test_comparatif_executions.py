"""Comparatif entre deux exécutions : transitions, delta, cloisonnement."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _creer_regle_version,
    _mission,
    _version_brouillon_test,
)


def _execution(session, tenant_id: int, mission_id: int) -> int:
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@comparatif') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
    session.commit()
    return int(eid)


def _conclusion(
    session,
    tenant_id: int,
    execution_id: int,
    regle_version_id: int,
    statut: str,
    montant: str | None = None,
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO conclusion (tenant_id, execution_id, "
                "regle_version_id, niveau_risque, statut, montant) "
                "VALUES (:t, :e, :rv, 'moyen', :s, :mt)"
            ),
            {
                "t": tenant_id,
                "e": execution_id,
                "rv": regle_version_id,
                "s": statut,
                "mt": montant,
            },
        )
    session.commit()


def _scenario_contraste(session, tid: int, mid: int, suffixe: str):
    """Deux exécutions avec transitions contrastées.

    R-AMEL : non_verifiable(1000) → conforme(None)     amélioration
    R-DEGR : conforme(None)       → anomalie(2500)     dégradation
    R-INCH : non_verifiable(300)  → non_verifiable(450) inchangé à risque
    R-NOUV : (absent)             → anomalie(700)      nouveau + dégradation
    R-DISP : anomalie(900)        → (absent)           disparu
    """
    vr = _version_brouillon_test(session)
    rv = {
        nom: _creer_regle_version(
            session, vr, f"{nom}-{suffixe}", f"Règle {nom}"
        )
        for nom in ("R-AMEL", "R-DEGR", "R-INCH", "R-NOUV", "R-DISP")
    }
    session.commit()
    e1 = _execution(session, tid, mid)
    _conclusion(session, tid, e1, rv["R-AMEL"], "non_verifiable", "1000")
    _conclusion(session, tid, e1, rv["R-DEGR"], "conforme")
    _conclusion(session, tid, e1, rv["R-INCH"], "non_verifiable", "300")
    _conclusion(session, tid, e1, rv["R-DISP"], "anomalie", "900")
    e2 = _execution(session, tid, mid)
    _conclusion(session, tid, e2, rv["R-AMEL"], "conforme")
    _conclusion(session, tid, e2, rv["R-DEGR"], "anomalie", "2500")
    _conclusion(session, tid, e2, rv["R-INCH"], "non_verifiable", "450")
    _conclusion(session, tid, e2, rv["R-NOUV"], "anomalie", "700")
    return e1, e2


def test_comparatif_transitions_et_delta(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    e1, e2 = _scenario_contraste(session, tid, mid, suffixe)

    resp = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions", headers=h
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    # Défaut : A = avant-dernière, B = dernière — avec dates.
    assert out["execution_a"]["id"] == e1
    assert out["execution_b"]["id"] == e2
    assert out["execution_a"]["date"] is not None
    assert out["execution_b"]["date"] is not None

    assert out["ameliorations"] == [
        {
            "regle_id": f"R-AMEL-{suffixe}",
            "avant": "non_verifiable",
            "apres": "conforme",
            "montant_avant": "1000.00",
            "montant_apres": None,
        }
    ]
    # Dégradations : conforme→anomalie + apparition d'anomalie (R-NOUV).
    assert out["degradations"] == [
        {
            "regle_id": f"R-DEGR-{suffixe}",
            "avant": "conforme",
            "apres": "anomalie",
            "montant_avant": None,
            "montant_apres": "2500.00",
        },
        {
            "regle_id": f"R-NOUV-{suffixe}",
            "avant": None,
            "apres": "anomalie",
            "montant_avant": None,
            "montant_apres": "700.00",
        },
    ]
    assert out["inchanges_a_risque"] == [
        {
            "regle_id": f"R-INCH-{suffixe}",
            "avant": "non_verifiable",
            "apres": "non_verifiable",
            "montant_avant": "300.00",
            "montant_apres": "450.00",
        }
    ]
    assert [n["regle_id"] for n in out["nouveaux"]] == [f"R-NOUV-{suffixe}"]
    assert [d["regle_id"] for d in out["disparus"]] == [f"R-DISP-{suffixe}"]
    assert out["disparus"][0]["avant"] == "anomalie"
    assert out["disparus"][0]["apres"] is None

    # Delta anomalies : B (2500 + 700) − A (900) = 2300.
    assert out["synthese"] == {
        "ameliorations": 1,
        "degradations": 2,
        "inchanges_a_risque": 1,
        "nouveaux": 1,
        "disparus": 1,
        "delta_montant_anomalies": "2300.00",
    }


def test_comparatif_executions_explicites(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    e1, e2 = _scenario_contraste(session, tid, mid, suffixe)
    e3 = _execution(session, tid, mid)  # troisième exécution vide

    resp = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions"
        f"?execution_a={e1}&execution_b={e2}",
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["execution_a"]["id"] == e1
    assert out["execution_b"]["id"] == e2
    assert out["synthese"]["ameliorations"] == 1

    # Exécution inconnue de la mission → 404.
    inconnue = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions?execution_a=999999999",
        headers=h,
    )
    assert inconnue.status_code == 404
    # A = B → 400 message clair.
    memes = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions"
        f"?execution_a={e3}&execution_b={e3}",
        headers=h,
    )
    assert memes.status_code == 400
    assert "distinctes" in memes.json()["detail"]


def test_moins_de_deux_executions_409(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)

    # Aucune exécution.
    r0 = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions", headers=h
    )
    assert r0.status_code == 409
    assert "au moins deux exécutions" in r0.json()["detail"]

    # Une seule exécution.
    _execution(session, tid, mid)
    r1 = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions", headers=h
    )
    assert r1.status_code == 409
    assert "au moins deux exécutions" in r1.json()["detail"]


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, tid_a = _connexion(client, email_a)
    mid = _mission(client, h_a)
    suffixe = uuid.uuid4().hex[:6].upper()
    _scenario_contraste(session, tid_a, mid, suffixe)

    h_b, _ = _connexion(client, email_b)
    assert (
        client.get(
            f"/api/v1/missions/{mid}/comparatif-executions", headers=h_b
        ).status_code
        == 404
    )
    # Le tenant légitime, lui, compare normalement.
    ok = client.get(
        f"/api/v1/missions/{mid}/comparatif-executions", headers=h_a
    )
    assert ok.status_code == 200, ok.text
