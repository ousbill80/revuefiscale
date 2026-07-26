"""Traçabilité journal_audit + isolation inter-cabinets.

Aucun taux / article inventé — événements dossier uniquement.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")

from backend.main import app  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BALANCE_JSON = FIXTURES / "balance_fictif_commerce.json"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-audit-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="audit")
    publier_version(session, lib, "audit@test.ci")


def _login_cabinet(session, *, suffix: str):
    email = f"audit.{suffix}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Audit {email}",
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
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}, r.tenant_id


def _mission_avec_parcours(client, headers) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=headers,
        json={
            "denomination": "PM Audit FICTIF",
            "ncc": f"CI-AUD-{uuid.uuid4().hex[:6].upper()}",
            "forme": "pm",
            "rccm": "CI-RCCM-AUD",
            "dfe": "DFE-AUD-1",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    cid = c.json()["id"]

    m = client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    mid = m.json()["id"]

    corps = json.loads(BALANCE_JSON.read_text(encoding="utf-8"))
    bal = client.post(f"/api/v1/missions/{mid}/balance", headers=headers, json=corps)
    assert bal.status_code == 200, bal.text

    ex = client.post(
        f"/api/v1/missions/{mid}/executer",
        headers=headers,
        json={"reponses": {}},
    )
    assert ex.status_code == 200, ex.text

    clot = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=headers,
        json={"statut": "cloturee"},
    )
    assert clot.status_code == 200, clot.text
    return mid


def test_audit_timeline_complete_et_synthese(session):
    _assurer_version(session)
    client, h, _tid = _login_cabinet(session, suffix="a")
    mid = _mission_avec_parcours(client, h)

    audit = client.get(f"/api/v1/missions/{mid}/audit", headers=h)
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["mission_id"] == mid
    assert "synthese" in body
    assert body["synthese"]["ecriture_seule"] is True
    assert body["synthese"]["chaine_hash"] is True
    assert body["synthese"]["total"] >= 4

    actions = {e["action"] for e in body["entrees"]}
    assert "creation_mission" in actions
    assert "import_balance" in actions
    assert "execution_moteur" in actions
    assert "changement_statut" in actions

    par = body["synthese"]["par_action"]
    assert par.get("creation_mission", 0) >= 1
    assert par.get("import_balance", 0) >= 1
    assert par.get("execution_moteur", 0) >= 1
    assert par.get("changement_statut", 0) >= 1

    for e in body["entrees"]:
        assert e.get("hash_court")
        assert e.get("acteur")
        assert isinstance(e.get("charge_utile"), dict)


def test_audit_pas_de_fuite_inter_cabinets(session):
    _assurer_version(session)
    client_a, h_a, _ = _login_cabinet(session, suffix="iso-a")
    client_b, h_b, _ = _login_cabinet(session, suffix="iso-b")

    mid_a = _mission_avec_parcours(client_a, h_a)
    mid_b = _mission_avec_parcours(client_b, h_b)

    # A ne voit pas la mission B
    fuite = client_a.get(f"/api/v1/missions/{mid_b}/audit", headers=h_a)
    assert fuite.status_code == 404, fuite.text

    # B ne voit pas la mission A
    fuite2 = client_b.get(f"/api/v1/missions/{mid_a}/audit", headers=h_b)
    assert fuite2.status_code == 404, fuite2.text

    ok_a = client_a.get(f"/api/v1/missions/{mid_a}/audit", headers=h_a)
    assert ok_a.status_code == 200
    assert all(
        e["action"] != "inconnu" for e in ok_a.json()["entrees"]
    )
    # Les IDs d'entrées de B ne doivent pas apparaître chez A
    ids_a = {e["id"] for e in ok_a.json()["entrees"] if e.get("id") is not None}
    ok_b = client_b.get(f"/api/v1/missions/{mid_b}/audit", headers=h_b)
    ids_b = {e["id"] for e in ok_b.json()["entrees"] if e.get("id") is not None}
    assert ids_a.isdisjoint(ids_b)
