"""Hachage mot de passe et jetons de session (HMAC). Sans dependance JWT externe."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any

from backend.config import config


class ErreurAuth(Exception):
    """Authentification ou jeton invalide."""


def hasher_mot_de_passe(mot_de_passe: str) -> str:
    sel = secrets.token_bytes(16)
    derive = hashlib.scrypt(
        mot_de_passe.encode("utf-8"),
        salt=sel,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${sel.hex()}${derive.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, empreinte: str) -> bool:
    try:
        algo, sel_hex, hash_hex = empreinte.split("$", 2)
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    derive = hashlib.scrypt(
        mot_de_passe.encode("utf-8"),
        salt=bytes.fromhex(sel_hex),
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return hmac.compare_digest(derive.hex(), hash_hex)


def _cle_secrete() -> bytes:
    cle = config.secret_key or "dev-only-changeme"
    return cle.encode("utf-8")


def emettre_jeton(
    *,
    utilisateur_id: int,
    tenant_id: int,
    role: str,
    email: str,
    ttl_secondes: int = 86_400,
) -> str:
    charge = {
        "typ": "tenant",
        "uid": utilisateur_id,
        "tid": tenant_id,
        "role": role,
        "email": email,
        "exp": int(time.time()) + ttl_secondes,
    }
    corps = urlsafe_b64encode(json.dumps(charge, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_cle_secrete(), corps.encode(), hashlib.sha256).hexdigest()
    return f"{corps}.{sig}"


@dataclass(frozen=True)
class SessionUtilisateur:
    utilisateur_id: int
    tenant_id: int
    role: str
    email: str


def decoder_jeton(jeton: str) -> SessionUtilisateur:
    try:
        corps, sig = jeton.split(".", 1)
    except ValueError as e:
        raise ErreurAuth("jeton mal forme") from e
    attendu = hmac.new(_cle_secrete(), corps.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, sig):
        raise ErreurAuth("signature invalide")
    try:
        charge: dict[str, Any] = json.loads(urlsafe_b64decode(corps + "=="))
    except (json.JSONDecodeError, ValueError) as e:
        raise ErreurAuth("charge invalide") from e
    if int(charge.get("exp", 0)) < int(time.time()):
        raise ErreurAuth("jeton expire")
    # Staff 2AàZ ≠ JWT tenant — deux chaines d auth (docs/11-saas-surfaces.md).
    if charge.get("typ") == "staff":
        raise ErreurAuth("jeton staff refuse sur routes abonne")
    return SessionUtilisateur(
        utilisateur_id=int(charge["uid"]),
        tenant_id=int(charge["tid"]),
        role=str(charge["role"]),
        email=str(charge["email"]),
    )
