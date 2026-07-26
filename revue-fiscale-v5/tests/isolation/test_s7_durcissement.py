"""Tests S7 — durcissement auth agent/usages, empty state client, PDF facture."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.abonne.service import creer_lien_acces  # noqa: E402
from backend.billing.factures import (  # noqa: E402
    creer_facture_brouillon,
    lire_facture,
    rendre_facture_pdf,
)
from backend.billing.service import creer_tenant  # noqa: E402
from backend.editorial.publication import (  # noqa: E402
    creer_version_brouillon,
    publier_version,
)
from backend.main import app  # noqa: E402
from backend.plateforme.auth import hasher_mot_de_passe  # noqa: E402
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.missions import creer_mission  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _assurer_version_publiee(session) -> None:
    row = session.execute(
        text(
            "SELECT id FROM version_referentiel "
            "WHERE publiee_le IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
    ).scalar_one_or_none()
    if row is not None:
        return
    lib = f"v-s7-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="test")
    publier_version(session, lib, "test@2aaz.ci")


def _staff_jeton(session, role: str) -> str:
    email = _email(f"s7-{role}")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, :r)"
        ),
        {"e": email, "h": hasher_mot_de_passe("StaffTest2026!"), "r": role},
    )
    session.commit()
    client = TestClient(app)
    auth = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": email, "mot_de_passe": "StaffTest2026!"},
    )
    assert auth.status_code == 200
    return auth.json()["jeton"]


def test_agent_et_usages_exigent_staff_editorial(session):
    client = TestClient(app)
    assert client.post(
        "/api/v1/agent/question",
        json={"question": "Quel article traite des dons ?"},
    ).status_code == 401
    assert client.post(
        "/api/v1/editorial/usages/differentiel",
        json={"texte_ancien": "a", "texte_nouveau": "b"},
    ).status_code == 401
    assert client.post(
        "/api/v1/editorial/usages/conversion-assistee",
        json={"texte_article": "Article fictif de test."},
    ).status_code == 401
    assert client.post(
        "/api/v1/editorial/propositions",
        json={"charge_utile": {"regle_id": "X"}, "sources": []},
    ).status_code == 401

    jeton_billing = _staff_jeton(session, "billing")
    h_bill = {"Authorization": f"Bearer {jeton_billing}"}
    assert (
        client.post(
            "/api/v1/editorial/usages/differentiel",
            headers=h_bill,
            json={"texte_ancien": "a", "texte_nouveau": "b"},
        ).status_code
        == 403
    )

    jeton_ed = _staff_jeton(session, "editorial")
    h_ed = {"Authorization": f"Bearer {jeton_ed}"}
    ok = client.post(
        "/api/v1/editorial/usages/differentiel",
        headers=h_ed,
        json={"texte_ancien": "ancien", "texte_nouveau": "nouveau"},
    )
    assert ok.status_code == 200
    assert "changements" in ok.json()

    conv = client.post(
        "/api/v1/editorial/usages/conversion-assistee",
        headers=h_ed,
        json={"texte_article": "Texte article CGI fictif pour conversion."},
    )
    assert conv.status_code == 200


def test_portail_client_sans_execution_empty_state(session):
    _assurer_version_publiee(session)
    email = _email("cab-s7")
    r = creer_tenant(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client S7') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=int(cid),
        exercice=2025,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )
    with contexte_tenant(session, r.tenant_id):
        lien = creer_lien_acces(
            session,
            r.tenant_id,
            mission_id=mid,
            email_contact="client@exemple.ci",
            cree_par=r.utilisateur_id,
        )
    effacer_contexte_tenant(session)
    session.commit()

    client = TestClient(app)
    resp = client.get(f"/api/v1/client/{lien['token']}/restitution")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sans_restitution"] is True
    assert body["restitution"] is None
    assert body["mission_id"] == mid
    assert "exécut" in body["message"].lower() or "restitution" in body["message"].lower()


def test_facture_pdf_minimal(session):
    email = _email("cab-pdf")
    r = creer_tenant(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    f = creer_facture_brouillon(session, r.tenant_id)
    session.commit()
    facture = lire_facture(session, f.id)
    pdf = rendre_facture_pdf(facture)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 200

    jeton = _staff_jeton(session, "billing")
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/billing/factures/{f.id}/pdf",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:4] == b"%PDF"

    assert (
        client.get(f"/api/v1/billing/factures/{f.id}/pdf").status_code == 401
    )


def test_tarifs_a_confirmer_lecture_seule_staff(session):
    """GET /tarifs-a-confirmer — inventaire honnête, staff only, pas d'écriture."""
    client = TestClient(app)
    assert client.get("/api/v1/billing/tarifs-a-confirmer").status_code == 401

    jeton = _staff_jeton(session, "billing")
    resp = client.get(
        "/api/v1/billing/tarifs-a-confirmer",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lecture_seule"] is True
    assert body["edition"] is False
    assert "paliers" in body["tarifs"]
    assert len(body["tarifs"]["paliers"]) == 4
    assert "champs" in body["mentions_facture"]
    assert len(body["mentions_facture"]["champs"]) == 7
    # Pas de secret Resend dans ce payload lecture seule
    blob = str(body).lower()
    assert "resend_api_key" not in blob
    assert body["tarifs"]["tarifs_a_confirmer"] is True or isinstance(
        body["tarifs"]["tarifs_a_confirmer"], bool
    )
