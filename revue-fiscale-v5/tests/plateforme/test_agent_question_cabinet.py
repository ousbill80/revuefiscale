"""Assistant fiscal indépendant du cabinet — accessible sans mission ouverte,
même moteur regle-based que le chemin mission (repondre() n'est pas modifié)."""
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

    lib = f"v-agent-cabinet-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="agent-cabinet")
    publier_version(session, lib, "agent-cabinet@test.ci")


def _cabinet(session) -> str:
    email = f"agent.cabinet.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Agent {email}",
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


def test_agent_question_cabinet_reponse_avec_citation(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)

    r = client.post(
        "/api/v1/agent/question",
        headers=h,
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "repondu"
    assert "DEMO-18-G" in corps["references"]
    assert corps["citations"]
    assert corps["contexte"] == "Assistant du cabinet"


def test_agent_question_cabinet_avec_historique(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)

    r = client.post(
        "/api/v1/agent/question",
        headers=h,
        json={
            "question": "Que dit l'article DEMO-18-G sur les dons ?",
            "historique": [
                {"question": "Bonjour", "reponse": "Bonjour, comment puis-je aider ?"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "repondu"


def test_agent_question_cabinet_abstention_hors_corpus(session):
    _assurer_version(session)
    seed_corpus_demo(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)

    r = client.post(
        "/api/v1/agent/question",
        headers=h,
        json={"question": "Que dit l'article 999 du CGI invente ?"},
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "abstention"
    assert corps["references"] == []


def test_agent_question_cabinet_vide_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)

    r = client.post(
        "/api/v1/agent/question",
        headers=h,
        json={"question": "   "},
    )
    assert r.status_code == 422, r.text


def test_agent_question_cabinet_401_sans_jeton(session):
    r = TestClient(app).post(
        "/api/v1/agent/question",
        json={"question": "Que dit l'article DEMO-18-G sur les dons ?"},
    )
    assert r.status_code == 401, r.text
