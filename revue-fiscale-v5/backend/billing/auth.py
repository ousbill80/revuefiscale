"""Jetons staff 2AàZ — chaine d auth distincte du JWT tenant."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any

from backend.config import config
from backend.plateforme.auth import ErreurAuth


def _cle_staff() -> bytes:
    """Secret derive — un jeton tenant ne peut pas etre rejoue comme staff."""
    cle = config.secret_key or "dev-only-changeme"
    return f"{cle}:staff".encode()


def emettre_jeton_staff(
    *,
    staff_id: int,
    role: str,
    email: str,
    ttl_secondes: int = 86_400,
) -> str:
    charge = {
        "typ": "staff",
        "sid": staff_id,
        "role": role,
        "email": email,
        "exp": int(time.time()) + ttl_secondes,
    }
    corps = urlsafe_b64encode(json.dumps(charge, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_cle_staff(), corps.encode(), hashlib.sha256).hexdigest()
    return f"{corps}.{sig}"


@dataclass(frozen=True)
class SessionStaff:
    staff_id: int
    role: str
    email: str


def decoder_jeton_staff(jeton: str) -> SessionStaff:
    try:
        corps, sig = jeton.split(".", 1)
    except ValueError as e:
        raise ErreurAuth("jeton mal forme") from e
    attendu = hmac.new(_cle_staff(), corps.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, sig):
        raise ErreurAuth("signature invalide")
    try:
        charge: dict[str, Any] = json.loads(urlsafe_b64decode(corps + "=="))
    except (json.JSONDecodeError, ValueError) as e:
        raise ErreurAuth("charge invalide") from e
    if int(charge.get("exp", 0)) < int(time.time()):
        raise ErreurAuth("jeton expire")
    if charge.get("typ") != "staff":
        raise ErreurAuth("jeton non staff")
    return SessionStaff(
        staff_id=int(charge["sid"]),
        role=str(charge["role"]),
        email=str(charge["email"]),
    )
