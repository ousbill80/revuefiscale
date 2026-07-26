"""Paystack — abonnement commercial : HMAC, XOF zero-decimal, 503 sans clé."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.abonne import paystack as paystack_mod
from backend.abonne.paystack import (
    ErreurPaystack,
    montant_xof_entier,
    verifier_signature,
)
from backend.main import app

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.billing.factures import (  # noqa: E402
    creer_facture_brouillon,
    emettre_facture,
    lire_facture,
)
from backend.billing.service import creer_tenant  # noqa: E402
from backend.plateforme.auth import emettre_jeton  # noqa: E402
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _cabinet(session, palier: str = "standard"):
    email = _email("cab")
    r = creer_tenant(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier=palier,
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    return r, email


def _headers_abonne(r, email: str, role: str = "admin") -> dict[str, str]:
    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role=role,
        email=email,
    )
    return {"Authorization": f"Bearer {jeton}"}


def test_montant_xof_zero_decimal():
    """XOF : int(montant) sans *100."""
    assert montant_xof_entier(50_000) == 50_000
    assert montant_xof_entier(Decimal("125000")) == 125_000
    assert montant_xof_entier("1000") == 1000
    with pytest.raises(ErreurPaystack):
        montant_xof_entier(Decimal("10.5"))
    with pytest.raises(ErreurPaystack):
        montant_xof_entier(-1)


def test_verifier_signature_hmac(monkeypatch):
    secret = "sk_test_hmac_unit"
    monkeypatch.setattr(paystack_mod.config, "paystack_secret_key", secret)
    body = b'{"event":"charge.success"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    assert verifier_signature(body, sig) is True
    assert verifier_signature(body, "bad") is False
    assert verifier_signature(body, None) is False


def test_payer_paystack_sans_cle_503(session, monkeypatch):
    monkeypatch.setattr(paystack_mod.config, "paystack_secret_key", "")
    monkeypatch.setattr(paystack_mod.config, "paystack_public_key", "")
    a, email = _cabinet(session)
    f = creer_facture_brouillon(session, a.tenant_id)
    emettre_facture(session, f.id)
    session.commit()

    client = TestClient(app)
    r = client.post(
        f"/api/v1/factures/{f.id}/payer-paystack",
        headers=_headers_abonne(a, email),
        json={},
    )
    assert r.status_code == 503
    assert "indisponible" in r.json()["detail"].lower() or "paystack" in r.json()[
        "detail"
    ].lower()

    cfg = client.get(
        "/api/v1/factures/paystack-config",
        headers=_headers_abonne(a, email),
    )
    assert cfg.status_code == 200
    assert cfg.json()["disponible"] is False


def test_webhook_mauvaise_signature_401(session, monkeypatch):
    monkeypatch.setattr(paystack_mod.config, "paystack_secret_key", "sk_test_webhook")
    client = TestClient(app)
    r = client.post(
        "/api/v1/webhooks/paystack",
        content=b'{"event":"charge.success"}',
        headers={"x-paystack-signature": "invalide"},
    )
    assert r.status_code == 401


def test_initialiser_et_webhook_marque_payee(session, monkeypatch):
    """Mock httpx initialize + verify → webhook pose statut payee."""
    monkeypatch.setattr(paystack_mod.config, "paystack_secret_key", "sk_test_flow")
    monkeypatch.setattr(paystack_mod.config, "paystack_public_key", "pk_test_flow")

    a, email = _cabinet(session)
    f = creer_facture_brouillon(session, a.tenant_id)
    emettre_facture(session, f.id)
    session.commit()
    montant = int(Decimal(str(lire_facture(session, f.id)["montant"])))

    ref_holder: dict[str, str] = {}

    class FakeResp:
        def __init__(self, payload: dict, code: int = 200):
            self._payload = payload
            self.status_code = code
            self.content = json.dumps(payload).encode()

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):  # noqa: A002
            assert "initialize" in url
            assert json["amount"] == montant  # pas *100
            assert json["currency"] == "XOF"
            assert json["channels"] == ["card", "mobile_money"]
            ref = json["reference"]
            ref_holder["ref"] = ref
            return FakeResp(
                {
                    "status": True,
                    "data": {
                        "authorization_url": "https://checkout.paystack.com/test",
                        "access_code": "ACCESS",
                        "reference": ref,
                    },
                }
            )

        def get(self, url, headers=None):
            assert "verify" in url
            return FakeResp(
                {
                    "status": True,
                    "data": {
                        "status": "success",
                        "amount": montant,
                        "currency": "XOF",
                        "reference": ref_holder["ref"],
                        "metadata": {
                            "facture_id": f.id,
                            "tenant_id": a.tenant_id,
                        },
                    },
                }
            )

    monkeypatch.setattr(paystack_mod.httpx, "Client", FakeClient)

    client = TestClient(app)
    ha = _headers_abonne(a, email)
    init = client.post(
        f"/api/v1/factures/{f.id}/payer-paystack",
        headers=ha,
        json={},
    )
    assert init.status_code == 201, init.text
    body = init.json()
    assert body["authorization_url"].startswith("https://")
    assert body["reference"] == ref_holder["ref"]
    assert body["amount_xof"] == montant

    liste = client.get("/api/v1/factures", headers=ha)
    assert liste.status_code == 200
    assert liste.json()["paystack"]["disponible"] is True

    event = {
        "event": "charge.success",
        "data": {
            "reference": ref_holder["ref"],
            "amount": montant,
            "metadata": {
                "facture_id": f.id,
                "tenant_id": a.tenant_id,
            },
        },
    }
    raw = json.dumps(event).encode()
    sig = hmac.new(b"sk_test_flow", raw, hashlib.sha512).hexdigest()
    wh = client.post(
        "/api/v1/webhooks/paystack",
        content=raw,
        headers={"x-paystack-signature": sig},
    )
    assert wh.status_code == 200, wh.text
    assert wh.json().get("marquer_payee") is True

    session.expire_all()
    assert lire_facture(session, f.id)["statut"] == "payee"

    with contexte_tenant(session, a.tenant_id):
        st = session.execute(
            text(
                "SELECT statut FROM paiement_paystack WHERE reference = :r"
            ),
            {"r": ref_holder["ref"]},
        ).scalar_one()
    effacer_contexte_tenant(session)
    assert st == "succes"


def test_rls_paiement_paystack_force(session):
    row = session.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'paiement_paystack'"
        )
    ).one_or_none()
    if row is None:
        pytest.skip("migration 023 non appliquée")
    assert row[0] is True
    assert row[1] is True
