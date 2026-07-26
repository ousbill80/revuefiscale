"""Journal d audit chaine — ecriture seule."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _hash_chaine(hash_prec: str | None, charge: dict[str, Any]) -> str:
    payload = json.dumps(
        {"prec": hash_prec or "", "charge": charge},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_journal(
    session: Session,
    *,
    tenant_id: int,
    mission_id: int | None,
    acteur: str,
    action: str,
    charge_utile: dict[str, Any] | None = None,
) -> int:
    """Ajoute une entree au journal avec hash chaine (sha256 prev+payload).

    Suppose le contexte tenant deja pose (RLS).
    """
    charge = charge_utile or {}
    hash_prec = session.execute(
        text(
            "SELECT hash FROM journal_audit "
            "WHERE tenant_id = :t "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"t": tenant_id},
    ).scalar_one_or_none()

    empreinte = _hash_chaine(hash_prec, {
        "acteur": acteur,
        "action": action,
        "mission_id": mission_id,
        "charge": charge,
    })

    jid = session.execute(
        text(
            "INSERT INTO journal_audit "
            "(tenant_id, mission_id, acteur, action, charge_utile, hash_prec, hash) "
            "VALUES (:t, :m, :a, :act, CAST(:c AS jsonb), :hp, :h) RETURNING id"
        ),
        {
            "t": tenant_id,
            "m": mission_id,
            "a": acteur,
            "act": action,
            "c": json.dumps(charge, ensure_ascii=False, default=str),
            "hp": hash_prec,
            "h": empreinte,
        },
    ).scalar_one()
    return int(jid)
