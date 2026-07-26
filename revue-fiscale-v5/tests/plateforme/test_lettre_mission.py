"""Lettre de mission .docx : contenu, en-têtes HTTP et cloisonnement tenant."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.main import app  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-lettre-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="lettre-mission")
    publier_version(session, lib, "lettre@test.ci")


def _cabinet(session):
    email = f"lettre.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Lettre {email}",
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
            "denomination": "PM Lettre FICTIF",
            "ncc": "CI-LETTRE-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-LETTRE",
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


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_lettre_mission_docx_contenu(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/lettre-mission.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "lettre_mission_PM_LETTRE_FICTIF_2025.docx" in dispo
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # Type d'engagement (libellé du cadrage) présent dans le document.
    assert "Revue préventive" in xml
    # Périmètre coché + exclusions déclarées + mention normes.
    assert "Taxe sur la valeur ajoutée" in xml
    assert "Douanes exclues du périmètre." in xml
    assert "ne constitue pas un audit ni une certification" in xml
    # Seuil renseigné → section présente ; champs manquants jamais inventés.
    assert "Seuil de signification" in xml
    assert "[à compléter]" in xml


def test_lettre_mission_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a = _connexion(client, email_a)
    mid = _mission_cadree(client, h_a)

    h_b = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/lettre-mission.docx", headers=h_b)
    assert resp.status_code == 404
