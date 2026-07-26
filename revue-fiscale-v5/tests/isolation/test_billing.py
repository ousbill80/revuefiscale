"""Tests Admin billing S1 — auth staff, isolation, provisionnement ferme."""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.billing.auth import (  # noqa: E402
    decoder_jeton_staff,
    emettre_jeton_staff,
)
from backend.billing.service import (  # noqa: E402
    PatchTenant,
    creer_tenant,
    lister_tenants,
    patcher_tenant,
)
from backend.config import config  # noqa: E402
from backend.plateforme.auth import (  # noqa: E402
    ErreurAuth,
    decoder_jeton,
    emettre_jeton,
    hasher_mot_de_passe,
)
from backend.plateforme.contexte import (  # noqa: E402
    contexte_tenant,
    effacer_contexte_tenant,
)


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def test_jeton_staff_distinct_du_tenant():
    j_staff = emettre_jeton_staff(staff_id=9, role="billing", email="billing@2aaz.ci")
    s = decoder_jeton_staff(j_staff)
    assert s.staff_id == 9 and s.role == "billing"

    with pytest.raises(ErreurAuth):
        decoder_jeton(j_staff)

    j_tenant = emettre_jeton(
        utilisateur_id=1, tenant_id=2, role="admin", email="a@b.ci"
    )
    with pytest.raises(ErreurAuth):
        decoder_jeton_staff(j_tenant)


def test_connexion_staff_seed(session):
    """Compte demo migration 005 — billing@2aaz.ci."""
    row = session.execute(
        text("SELECT * FROM auth_lookup_staff(:e)"),
        {"e": "billing@2aaz.ci"},
    ).mappings().one_or_none()
    if row is None:
        pytest.skip("seed staff absent — lancez make migrate (005)")
    from backend.plateforme.auth import verifier_mot_de_passe

    mdp = os.getenv("BILLING_DEMO_PASSWORD", "BillingDemo2026!")
    assert verifier_mot_de_passe(mdp, row["password_hash"])
    assert row["role"] == "billing"


def test_creer_tenant_via_billing(session):
    email = _email("bill")
    r = creer_tenant(
        session,
        denomination="Cabinet Billing Test",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="secret12345",
        note="cree par test billing",
    )
    assert r.tenant_id > 0
    abos = session.execute(
        text("SELECT palier, statut, note FROM abonnement WHERE tenant_id = :t"),
        {"t": r.tenant_id},
    ).mappings().all()
    assert len(abos) >= 1
    assert abos[-1]["palier"] == "standard"
    assert abos[-1]["statut"] == "actif"

    liste = lister_tenants(session)
    ids = {row["tenant_id"] for row in liste}
    assert r.tenant_id in ids
    resume = next(x for x in liste if x["tenant_id"] == r.tenant_id)
    assert resume["missions_incluses"] == 20

    maj = patcher_tenant(session, r.tenant_id, PatchTenant(statut="suspendu"))
    assert maj["statut"] == "suspendu"


def test_staff_ne_lit_pas_conclusions_via_routes_abonne(session):
    """Un jeton staff est refuse sur /api/v1/moi (chaine tenant)."""
    email = _email("isol")
    r = creer_tenant(
        session,
        denomination="Cabinet Isol Staff",
        type_tenant="cabinet",
        palier="essentiel",
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    # Donnee sensible sous RLS — visible seulement avec contexte tenant.
    with contexte_tenant(session, r.tenant_id):
        session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Secret Client')"
            ),
            {"t": r.tenant_id},
        )
    effacer_contexte_tenant(session)
    session.commit()

    # Staff sans tenant_id pose : zero ligne sur tables cloisonnees.
    n = session.execute(text("SELECT count(*) FROM contribuable")).scalar_one()
    assert n == 0

    # Seed / creer staff temporaire pour jeton API
    staff_email = _email("staff")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, 'billing')"
        ),
        {"e": staff_email, "h": hasher_mot_de_passe("StaffTest2026!")},
    )
    session.commit()

    from backend.main import app

    client = TestClient(app)
    auth = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": staff_email, "mot_de_passe": "StaffTest2026!"},
    )
    assert auth.status_code == 200
    jeton_staff = auth.json()["jeton"]

    moi = client.get(
        "/api/v1/moi",
        headers={"Authorization": f"Bearer {jeton_staff}"},
    )
    assert moi.status_code == 401

    # Liste billing OK, sans exposer contribuables
    liste = client.get(
        "/api/v1/billing/tenants",
        headers={"Authorization": f"Bearer {jeton_staff}"},
    )
    assert liste.status_code == 200
    payload = liste.json()
    assert any(t["tenant_id"] == r.tenant_id for t in payload)
    assert all("conclusion" not in t for t in payload)
    assert all("contribuable" not in str(t).lower() for t in payload)


def test_provisionnement_public_refuse_quand_flag_off(monkeypatch):
    monkeypatch.setattr(config, "env", "production")
    monkeypatch.setattr(config, "allow_public_provisioning", False)
    assert not config.provisionnement_public_autorise()

    from backend.main import app

    client = TestClient(app)
    r = client.post(
        "/api/v1/provisionnement",
        json={
            "denomination": "Ne doit pas passer",
            "type_tenant": "cabinet",
            "palier": "standard",
            "email_admin": _email("refuse"),
            "mot_de_passe_admin": "secret12345",
        },
    )
    assert r.status_code == 403
    assert "desactive" in r.json()["detail"].lower() or "disabled" in r.json()["detail"].lower()


def test_provisionnement_public_autorise_en_dev(monkeypatch, session):
    monkeypatch.setattr(config, "env", "dev")
    monkeypatch.setattr(config, "allow_public_provisioning", False)
    assert config.provisionnement_public_autorise()

    from backend.main import app

    client = TestClient(app)
    email = _email("pubdev")
    r = client.post(
        "/api/v1/provisionnement",
        json={
            "denomination": "Cabinet Dev Public",
            "type_tenant": "cabinet",
            "palier": "standard",
            "email_admin": email,
            "mot_de_passe_admin": "secret12345",
        },
    )
    assert r.status_code == 200
    assert r.json()["tenant_id"] > 0
