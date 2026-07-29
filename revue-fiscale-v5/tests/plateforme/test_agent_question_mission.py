"""Question à l'agent fiscal depuis une mission cabinet : cloisonnement tenant,
validations et anti-invention (le moteur repondre() n'est pas modifié ici)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

from backend.corpus.ingestion import seed_corpus_demo  # noqa: E402
from backend.main import app  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-agent-mission-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="agent-mission")
    publier_version(session, lib, "agent-mission@test.ci")


def _cabinet(session) -> str:
    email = f"agent.mission.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Agent Mission {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return email


def _connexion(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['jeton']}"}


def _mission_cadree(client: TestClient, h: dict[str, str]) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Agent Mission FICTIF",
            "ncc": "CI-AGENT-MISSION-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-AGENT-MISSION",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan Plateau",
        },
    )
    assert c.status_code == 200, c.text
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": c.json()["id"],
            "type_engagement": "preventive",
            "perimetre_impots": ["BIC", "TVA"],
            "exclusions_declarees": "Douanes exclues du périmètre.",
            "seuil_signification": 500000,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def test_agent_question_mission_reponse_avec_citation(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    r = client.post(
        f"/api/v1/missions/{mid}/agent/question",
        headers=h,
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] in ("repondu", "abstention")
    assert corps["statut"] == "repondu"
    assert "DEMO-18-G" in corps["references"]
    assert corps["citations"]
    assert f"Mission #{mid}" in corps["contexte"]
    assert "2025" in corps["contexte"]


def test_agent_question_mission_avec_historique(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    r = client.post(
        f"/api/v1/missions/{mid}/agent/question",
        headers=h,
        json={
            "question": "Que dit l'article DEMO-18-G sur les dons ?",
            "historique": [
                {"question": "Bonjour", "reponse": "Bonjour, comment puis-je aider ?"},
                {
                    "question": "Peux-tu m'expliquer le régime des dons ?",
                    "reponse": "Le régime des dons dépend du corpus applicable.",
                },
                {
                    "question": "Et pour les entreprises soumises au réel ?",
                    "reponse": "Le traitement suit les règles générales du CGI.",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "repondu"
    assert "DEMO-18-G" in corps["references"]


def test_agent_question_mission_abstention_hors_corpus(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    r = client.post(
        f"/api/v1/missions/{mid}/agent/question",
        headers=h,
        json={"question": "Que dit l'article 999 du CGI invente ?"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "abstention"
    assert corps["references"] == []


def test_agent_question_mission_cross_tenant_404(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a = _connexion(client, email_a)
    mid = _mission_cadree(client, h_a)

    h_b = _connexion(client, email_b)
    r = client.post(
        f"/api/v1/missions/{mid}/agent/question",
        headers=h_b,
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 404, r.text


def test_agent_question_mission_introuvable_404(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)

    r = client.post(
        "/api/v1/missions/999999999/agent/question",
        headers=h,
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 404, r.text


def test_agent_question_mission_vide_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    r = client.post(
        f"/api/v1/missions/{mid}/agent/question",
        headers=h,
        json={"question": "   "},
    )
    assert r.status_code == 422, r.text


def test_agent_question_mission_401_sans_jeton(session):
    r = TestClient(app).post(
        "/api/v1/missions/1/agent/question",
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 401, r.text
