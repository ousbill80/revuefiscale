"""Smoke HTTP — Contexte CGI + corpus/rechercher (staff editorial)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.corpus.ingestion import ingerer_document  # noqa: E402
from backend.main import app  # noqa: E402
from backend.plateforme.auth import hasher_mot_de_passe  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _staff_jeton(session, role: str = "editorial") -> str:
    email = _email(f"ctx-{role}")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, :r)"
        ),
        {
            "e": email,
            "h": hasher_mot_de_passe("StaffTest2026!"),
            "r": role,
        },
    )
    session.commit()
    client = TestClient(app)
    auth = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": email, "mot_de_passe": "StaffTest2026!"},
    )
    assert auth.status_code == 200
    return auth.json()["jeton"]


def test_http_contexte_cgi_a_confirmer_et_rechercher(session):
    ingerer_document(
        session,
        titre="[TEST] CGI smoke seance",
        type="cgi",
        millesime=2026,
        texte_brut=(
            "Art. 18 G — Dons aux œuvres. Plafond technique de démonstration.\n\n"
            "Art. 99 Z — Hors sujet."
        ),
    )
    session.commit()

    jeton = _staff_jeton(session)
    headers = {"Authorization": f"Bearer {jeton}"}
    client = TestClient(app)

    ctx = client.get(
        "/api/v1/editorial/a-confirmer/contexte-cgi",
        headers=headers,
        params={"entree_id": "BIC-CHG-18G-DONS#0", "millesime": 2026, "limite": 3},
    )
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert "fragments" in body
    assert body.get("type") == "cgi"
    assert body.get("millesime") == 2026
    assert "avertissement" in body
    assert "purge" in (body.get("avertissement") or "").lower() or "a_confirmer" in (
        body.get("avertissement") or ""
    )

    rech = client.get(
        "/api/v1/editorial/corpus/rechercher",
        headers=headers,
        params={"q": "art. 18", "type": "cgi", "millesime": 2026, "limite": 5},
    )
    assert rech.status_code == 200, rech.text
    hits = rech.json()
    assert isinstance(hits, list)
    for h in hits:
        src_type = (h.get("type") or "").lower()
        if src_type:
            assert src_type == "cgi"


def test_http_contexte_cgi_refuse_sans_auth():
    client = TestClient(app)
    assert (
        client.get(
            "/api/v1/editorial/a-confirmer/contexte-cgi",
            params={"entree_id": "BIC-CHG-18G-DONS#0"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/editorial/corpus/rechercher",
            params={"q": "art. 18", "type": "cgi", "millesime": 2026},
        ).status_code
        == 401
    )
