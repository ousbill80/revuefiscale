"""Smoke — seed démo commercial (ENV=dev) + auth /app.

Aucun taux fiscal inventé. Credentials via CABINET_DEMO_* / config.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

from backend.config import config  # noqa: E402
from backend.main import app  # noqa: E402
from backend.scripts.demo_commercial import (  # noqa: E402
    IdentifiantsDemo,
    identifiants_demo,
    provisionner_parcours_demo,
    refuser_hors_dev,
)


def test_identifiants_demo_depuis_config():
    ids = identifiants_demo()
    assert "@" in ids.email
    assert len(ids.mot_de_passe) >= 8
    assert ids.email == config.cabinet_demo_email.strip().lower()


def test_refuser_hors_dev(monkeypatch):
    monkeypatch.setattr(config, "env", "production")
    with pytest.raises(SystemExit, match="Refusé"):
        refuser_hors_dev()
    # Force autorisé
    refuser_hors_dev(forcer=True)
    monkeypatch.setenv("FORCE_DEMO_SEED", "1")
    refuser_hors_dev()
    monkeypatch.delenv("FORCE_DEMO_SEED", raising=False)
    monkeypatch.setattr(config, "env", "dev")


def test_sante_expose_demo_uniquement_en_dev(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(config, "env", "dev")
    r = client.get("/sante")
    assert r.status_code == 200
    body = r.json()
    assert body["env"] == "dev"
    assert body["demo"]["rejouer"] == "make demolot"
    assert body["demo"]["email"] == config.cabinet_demo_email.strip().lower()

    monkeypatch.setattr(config, "env", "production")
    r2 = client.get("/sante")
    assert r2.status_code == 200
    assert "demo" not in r2.json()
    monkeypatch.setattr(config, "env", "dev")


def test_demo_commercial_provisionne_et_auth(session, monkeypatch):
    """Cabinet isolé + mission FICTIF + login API."""
    import uuid

    from backend.editorial.publication import creer_version_brouillon, publier_version
    from backend.plateforme.provisionnement import derniere_version_publiee

    monkeypatch.setattr(config, "env", "dev")
    if derniere_version_publiee(session) is None:
        creer_version_brouillon(session, "v-demo-commercial", note="demo")
        publier_version(session, "v-demo-commercial", "demo@test.ci")

    ids = IdentifiantsDemo(
        email=f"demo.comm.{uuid.uuid4().hex[:8]}@demo.local",
        mot_de_passe="demo-demo1",
    )
    resultat = provisionner_parcours_demo(session, ids=ids)
    session.commit()

    assert resultat.tenant_id > 0
    assert resultat.mission_id > 0
    assert resultat.nb_comptes >= 1

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": ids.email, "mot_de_passe": ids.mot_de_passe},
    )
    assert login.status_code == 200, login.text
    jeton = login.json()["jeton"]
    h = {"Authorization": f"Bearer {jeton}"}

    missions = client.get("/api/v1/missions", headers=h)
    assert missions.status_code == 200
    ids_m = {m["id"] for m in missions.json()}
    assert resultat.mission_id in ids_m

    rest = client.get(
        f"/api/v1/missions/{resultat.mission_id}/restitution", headers=h
    )
    assert rest.status_code == 200, rest.text
    assert rest.json().get("version_referentiel_id")
