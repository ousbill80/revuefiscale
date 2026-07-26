"""Traçabilité création contribuable + clés manquantes identité."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.abonne.contribuable_identite import completude_identite, normaliser_payload
from backend.main import app
from backend.plateforme.provisionnement import (
    derniere_version_publiee,
    provisionner_cabinet,
)

pytestmark = pytest.mark.db


def _colonnes_audit_ok(session) -> bool:
    n = session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = 'contribuable' "
            "AND column_name IN ('cree_le', 'cree_par')"
        )
    ).scalar_one()
    return int(n) >= 2


def test_completude_cles_manquantes():
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        regime_fiscal="reel",
        forme_juridique="SA",
        capital_social=1,
    )
    c = completude_identite(p)
    assert "cles_manquantes" in c
    assert "commune" in c["cles_manquantes"]
    assert "centre_impots" in c["cles_manquantes"]
    assert "Commune / ville" in c["manquants"]


def test_creation_contribuable_audit_api(session):
    if not _colonnes_audit_ok(session):
        pytest.skip("migration 025 non appliquée — lancez make migrate")

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import creer_version_brouillon, publier_version

        lib = f"v-audit-{uuid.uuid4().hex[:6]}"
        creer_version_brouillon(session, lib, note="audit")
        publier_version(session, lib, "audit@test.ci")

    email = f"audit.{uuid.uuid4().hex[:8]}@demo.local"
    mdp = "audit-audit1"
    r_prov = provisionner_cabinet(
        session,
        denomination=f"Cabinet Audit {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin=mdp,
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": mdp},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    suffix = uuid.uuid4().hex[:8]
    r = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"Audit Trail {suffix}",
            "ncc": f"CI-AUD-{suffix}",
            "forme": "pm",
            "rccm": f"RCCM-{suffix}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("cree_le"), body
    assert body.get("cree_par") is not None, body
    assert body.get("cree_par_email") == email, body

    det = client.get(f"/api/v1/contribuables/{body['id']}", headers=h)
    assert det.status_code == 200
    fiche = det.json()
    assert fiche["cree_le"] == body["cree_le"]
    assert fiche["cree_par_email"] == email
    assert not fiche.get("commune")
    assert not fiche.get("centre_impots")

    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, r_prov.tenant_id):
        n = session.execute(
            text(
                "SELECT COUNT(*) FROM journal_audit "
                "WHERE action = 'creation_contribuable' "
                "AND charge_utile->>'contribuable_id' = :cid"
            ),
            {"cid": str(body["id"])},
        ).scalar_one()
        assert int(n) >= 1
