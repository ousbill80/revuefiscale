"""Paiement abonnement via Paystack (Visa / Mobile Money CI).

Montants **commerciaux** uniquement (facture.montant) — jamais fiscaux CGI.
L'abonné initialise le checkout ; seul le webhook (après vérif signature +
verify Paystack) appelle ``marquer_payee`` sous ``contexte_tenant`` (SET LOCAL).

XOF est une devise zero-decimal chez Paystack : passer ``int(montant)``
tel quel dans ``amount`` (ne pas multiplier par 100).
Webhook documenté : ``POST /api/v1/webhooks/paystack``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.abonne.facturation import lire_facture_tenant
from backend.abonne.service import ErreurAbonne
from backend.billing.factures import ErreurFacture, marquer_payee
from backend.config import config
from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.dependances import SessionDep

PAYSTACK_BASE = "https://api.paystack.co"
# Canaux checkout CI : carte (Visa) + Mobile Money (MTN, Orange, Wave via Paystack).
CHANNELS = ["card", "mobile_money"]

router_webhooks = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class ErreurPaystack(Exception):
    """Échec métier / config Paystack."""


def paystack_disponible() -> bool:
    return bool((config.paystack_secret_key or "").strip())


def config_publique() -> dict[str, Any]:
    """Exposé frontend — jamais la clé secrète."""
    dispo = paystack_disponible()
    return {
        "disponible": dispo,
        "public_key": (config.paystack_public_key or "").strip() if dispo else "",
        "channels": list(CHANNELS),
        "currency": "XOF",
        "message": (
            None
            if dispo
            else (
                "Paiement Paystack indisponible : clés non configurées "
                "(ops 2AàZ — PAYSTACK_SECRET_KEY)."
            )
        ),
    }


def montant_xof_entier(montant: Decimal | int | float | str) -> int:
    """XOF zero-decimal : entier en unités majeures, sans *100.

    Paystack attend pour XOF le montant nominal (ex. 50_000 XOF → 50000),
    contrairement aux devises à sous-unités (NGN/USD) où amount = kobo/cents.
    """
    d = Decimal(str(montant))
    if d < 0:
        raise ErreurPaystack("montant négatif refusé")
    # Factures commerciales : montants entiers XOF ; refuse les fractions.
    if d != d.to_integral_value():
        raise ErreurPaystack(
            f"montant XOF non entier ({d}) — facture.montant attendu entier"
        )
    return int(d)


def _callback_url_defaut() -> str:
    override = (config.paystack_callback_url or "").strip()
    if override:
        return override
    base = (config.app_public_url or "").strip().rstrip("/")
    if not base:
        base = "http://localhost:8000"
    return f"{base}/app/?vue=facturation&paystack=1"


def _headers_secret() -> dict[str, str]:
    cle = (config.paystack_secret_key or "").strip()
    if not cle:
        raise ErreurPaystack("PAYSTACK_SECRET_KEY absent")
    return {
        "Authorization": f"Bearer {cle}",
        "Content-Type": "application/json",
    }


def verifier_signature(raw_body: bytes, signature: str | None) -> bool:
    """HMAC-SHA512(body, secret) == x-paystack-signature."""
    cle = (config.paystack_secret_key or "").strip()
    if not cle or not signature:
        return False
    attendu = hmac.new(
        cle.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(attendu, signature.strip())


def _nouvelle_reference(facture_id: int, tenant_id: int) -> str:
    return f"rf-{tenant_id}-{facture_id}-{uuid.uuid4().hex[:12]}"


def initialiser_paiement(
    session: Session,
    *,
    tenant_id: int,
    facture_id: int,
    email: str,
    callback_url: str | None = None,
) -> dict[str, Any]:
    """POST Paystack /transaction/initialize + ligne paiement_paystack.

    Prérequis : session déjà sous ``contexte_tenant`` (routes ``session_abonne``).
    """
    if not paystack_disponible():
        raise ErreurPaystack(
            "Paiement Paystack indisponible (PAYSTACK_SECRET_KEY non configurée)"
        )

    facture = lire_facture_tenant(session, tenant_id, facture_id)
    if facture["statut"] not in {"emise", "brouillon"}:
        raise ErreurAbonne(
            f"facture non payable via Paystack (statut={facture['statut']})"
        )

    amount = montant_xof_entier(facture["montant"])
    reference = _nouvelle_reference(facture_id, tenant_id)
    cb = (callback_url or "").strip() or _callback_url_defaut()
    email_clean = (email or "").strip().lower()
    if not email_clean or "@" not in email_clean:
        raise ErreurAbonne("email payeur requis pour Paystack")

    payload_init = {
        "email": email_clean,
        "amount": amount,  # XOF zero-decimal : int(montant), pas *100
        "currency": "XOF",
        "reference": reference,
        "callback_url": cb,
        "channels": CHANNELS,
        "metadata": {
            "facture_id": facture_id,
            "tenant_id": tenant_id,
            "custom_fields": [
                {
                    "display_name": "Facture",
                    "variable_name": "facture_id",
                    "value": str(facture_id),
                }
            ],
        },
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                headers=_headers_secret(),
                json=payload_init,
            )
    except httpx.HTTPError as e:
        raise ErreurPaystack(f"Paystack injoignable : {e}") from e

    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or not data.get("status"):
        msg = data.get("message") or f"HTTP {resp.status_code}"
        raise ErreurPaystack(f"initialisation Paystack refusée : {msg}")

    result = data.get("data") or {}
    auth_url = result.get("authorization_url")
    access_code = result.get("access_code")
    ref_retour = result.get("reference") or reference
    if not auth_url:
        raise ErreurPaystack("réponse Paystack sans authorization_url")

    session.execute(
        text(
            "INSERT INTO paiement_paystack "
            "(tenant_id, facture_id, reference, statut, amount_xof, currency, "
            " authorization_url, access_code, paystack_payload, maj_le) "
            "VALUES (:t, :f, :r, 'initialise', :a, 'XOF', :u, :c, CAST(:p AS jsonb), now())"
        ),
        {
            "t": tenant_id,
            "f": facture_id,
            "r": ref_retour,
            "a": amount,
            "u": auth_url,
            "c": access_code,
            "p": json.dumps({"initialize": data}, default=str),
        },
    )

    return {
        "authorization_url": auth_url,
        "reference": ref_retour,
        "access_code": access_code,
        "public_key": (config.paystack_public_key or "").strip(),
        "amount_xof": amount,
        "currency": "XOF",
        "facture_id": facture_id,
    }


def _verifier_transaction(reference: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{PAYSTACK_BASE}/transaction/verify/{reference}",
                headers=_headers_secret(),
            )
    except httpx.HTTPError as e:
        raise ErreurPaystack(f"vérification Paystack injoignable : {e}") from e

    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or not data.get("status"):
        msg = data.get("message") or f"HTTP {resp.status_code}"
        raise ErreurPaystack(f"vérification refusée : {msg}")
    tx = data.get("data") or {}
    if str(tx.get("status") or "").lower() != "success":
        raise ErreurPaystack(
            f"transaction non réussie (status={tx.get('status')})"
        )
    return {"raw": data, "tx": tx}


def traiter_webhook(session: Session, raw_body: bytes, signature: str | None) -> dict[str, Any]:
    """Vérifie signature HMAC, sur charge.success → verify + marquer_payee."""
    if not paystack_disponible():
        raise ErreurPaystack("PAYSTACK_SECRET_KEY absent")

    if not verifier_signature(raw_body, signature):
        raise ErreurPaystack("signature webhook invalide")

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ErreurPaystack("corps webhook JSON invalide") from e

    event_name = str(event.get("event") or "")
    if event_name != "charge.success":
        return {"ok": True, "ignored": True, "event": event_name}

    data = event.get("data") or {}
    reference = str(data.get("reference") or "").strip()
    if not reference:
        raise ErreurPaystack("charge.success sans reference")

    verified = _verifier_transaction(reference)
    tx = verified["tx"]
    meta = tx.get("metadata") or data.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}

    try:
        facture_id = int(meta.get("facture_id"))
        tenant_id = int(meta.get("tenant_id"))
    except (TypeError, ValueError) as e:
        raise ErreurPaystack(
            "metadata facture_id / tenant_id manquants ou invalides"
        ) from e

    # Montant Paystack (XOF zero-decimal) vs facture stockée.
    amount_paid = montant_xof_entier(tx.get("amount") or data.get("amount") or 0)

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, facture_id, tenant_id, amount_xof, statut "
                "FROM paiement_paystack WHERE reference = :r"
            ),
            {"r": reference},
        ).mappings().one_or_none()

        if row is None:
            # Filet : transaction vérifiée mais init locale absente (race / rejoué).
            # On crée une ligne succes pour traçabilité.
            session.execute(
                text(
                    "INSERT INTO paiement_paystack "
                    "(tenant_id, facture_id, reference, statut, amount_xof, "
                    " currency, paystack_payload, maj_le) "
                    "VALUES (:t, :f, :r, 'succes', :a, 'XOF', CAST(:p AS jsonb), now()) "
                    "ON CONFLICT (reference) DO UPDATE SET "
                    " statut = 'succes', paystack_payload = CAST(:p AS jsonb), "
                    " maj_le = now()"
                ),
                {
                    "t": tenant_id,
                    "f": facture_id,
                    "r": reference,
                    "a": amount_paid,
                    "p": json.dumps(
                        {"webhook": event, "verify": verified["raw"]},
                        default=str,
                    ),
                },
            )
        else:
            if int(row["tenant_id"]) != tenant_id or int(row["facture_id"]) != facture_id:
                raise ErreurPaystack("metadata ≠ paiement_paystack local")
            if int(row["amount_xof"]) != amount_paid:
                raise ErreurPaystack(
                    f"montant Paystack ({amount_paid}) ≠ amount_xof local "
                    f"({row['amount_xof']})"
                )
            session.execute(
                text(
                    "UPDATE paiement_paystack SET statut = 'succes', "
                    " paystack_payload = CAST(:p AS jsonb), maj_le = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": int(row["id"]),
                    "p": json.dumps(
                        {"webhook": event, "verify": verified["raw"]},
                        default=str,
                    ),
                },
            )

        # marquer_payee sous le même SET LOCAL (ou redépose via sa propre
        # contexte_tenant) — l'abonné n'appelle jamais cette fonction.
        try:
            facture = marquer_payee(session, facture_id)
        except ErreurFacture as e:
            # Déjà payée / annulée : on a quand même enregistré le succès PSP.
            return {
                "ok": True,
                "reference": reference,
                "facture_id": facture_id,
                "marquer_payee": False,
                "detail": str(e),
            }

    return {
        "ok": True,
        "reference": reference,
        "facture_id": facture_id,
        "tenant_id": tenant_id,
        "facture_statut": facture.get("statut"),
        "marquer_payee": True,
    }


@router_webhooks.post("/paystack")
async def api_webhook_paystack(
    request: Request,
    session: SessionDep,
    x_paystack_signature: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Pas de JWT — authentification = HMAC SHA512 du corps brut."""
    raw = await request.body()
    try:
        return traiter_webhook(session, raw, x_paystack_signature)
    except ErreurPaystack as e:
        msg = str(e)
        if "signature" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=msg,
            ) from e
        if "absent" in msg.lower() or "indisponible" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=msg,
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from e
