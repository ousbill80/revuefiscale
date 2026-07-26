"""File d'envoi email + templates invitation — pas de faux succès silencieux en prod."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import config

logger = logging.getLogger(__name__)


class ErreurEmail(Exception):
    """Échec d'envoi ou d'enregistrement outbox."""


@dataclass(frozen=True)
class ResultatEnvoi:
    outbox_id: int
    statut: str
    mode: str  # resend | simule_dev | echec


def _corps_invitation(*, email: str, role: str, token: str, base_url: str) -> tuple[str, str, str]:
    sujet = "Invitation — Revue Fiscale"
    lien = f"{base_url.rstrip('/')}/app/?invitation={token}"
    html = (
        "<p>Bonjour,</p>"
        f"<p>Vous êtes invité(e) sur Revue Fiscale en tant que <strong>{role}</strong>.</p>"
        f"<p><a href=\"{lien}\">Accepter l'invitation</a></p>"
        "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p>"
    )
    texte = (
        f"Invitation Revue Fiscale (rôle {role})\n"
        f"Lien : {lien}\n"
    )
    return sujet, html, texte


def _envoyer_resend(*, destinataire: str, sujet: str, html: str, texte: str) -> None:
    if not config.resend_api_key:
        raise ErreurEmail("RESEND_API_KEY manquant")
    corps = {
        "from": config.resend_from,
        "to": [destinataire],
        "subject": sujet,
        "html": html,
        "text": texte,
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {config.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=corps,
        )
    if r.status_code >= 400:
        logger.error("Resend invitation erreur %s : %s", r.status_code, r.text[:500])
        raise ErreurEmail(f"échec Resend HTTP {r.status_code}")


def enregistrer_outbox(
    session: Session,
    *,
    destinataire: str,
    sujet: str,
    template: str,
    payload: dict[str, Any],
    tenant_id: int | None,
    statut: str = "en_attente",
    dernier_erreur: str | None = None,
) -> int:
    oid = session.execute(
        text(
            "INSERT INTO email_outbox "
            "(tenant_id, destinataire, sujet, template, payload, "
            "statut, tentatives, dernier_erreur) "
            "VALUES (:t, :d, :s, :tpl, CAST(:p AS jsonb), :st, 0, :err) "
            "RETURNING id"
        ),
        {
            "t": tenant_id,
            "d": destinataire,
            "s": sujet,
            "tpl": template,
            "p": json.dumps(payload, ensure_ascii=False),
            "st": statut,
            "err": dernier_erreur,
        },
    ).scalar_one()
    return int(oid)


def envoyer_invitation(
    session: Session,
    *,
    tenant_id: int,
    email: str,
    role: str,
    token: str,
    base_url: str | None = None,
) -> ResultatEnvoi:
    """Envoie l'invitation via Resend si clé présente ; sinon outbox.

    - ENV=dev sans clé → statut ``simule_dev`` (jeton toujours renvoyé à l'UI).
    - ENV≠dev sans clé → statut ``echec`` explicite (pas de faux envoi silencieux).
    """
    url = base_url or "http://localhost:8000"
    sujet, html, texte = _corps_invitation(
        email=email, role=role, token=token, base_url=url
    )
    # Payload : pas de données missions — token pour reprise d'envoi uniquement.
    payload = {
        "role": role,
        "token": token,
        "base_url": url,
        "avertissement": "Jeton invitation — ne contient pas de données fiscales.",
    }

    if config.resend_api_key:
        try:
            _envoyer_resend(destinataire=email, sujet=sujet, html=html, texte=texte)
            oid = enregistrer_outbox(
                session,
                destinataire=email,
                sujet=sujet,
                template="invitation",
                payload={**payload, "token": "[envoye]"},
                tenant_id=tenant_id,
                statut="envoye",
            )
            session.execute(
                text(
                    "UPDATE email_outbox SET envoye_le = now(), tentatives = 1 "
                    "WHERE id = :id"
                ),
                {"id": oid},
            )
            return ResultatEnvoi(outbox_id=oid, statut="envoye", mode="resend")
        except ErreurEmail as e:
            oid = enregistrer_outbox(
                session,
                destinataire=email,
                sujet=sujet,
                template="invitation",
                payload=payload,
                tenant_id=tenant_id,
                statut="echec",
                dernier_erreur=str(e),
            )
            session.execute(
                text("UPDATE email_outbox SET tentatives = 1 WHERE id = :id"),
                {"id": oid},
            )
            return ResultatEnvoi(outbox_id=oid, statut="echec", mode="echec")

    if config.env == "dev":
        oid = enregistrer_outbox(
            session,
            destinataire=email,
            sujet=sujet,
            template="invitation",
            payload=payload,
            tenant_id=tenant_id,
            statut="simule_dev",
            dernier_erreur="RESEND_API_KEY absent — simulation dev (jeton UI)",
        )
        return ResultatEnvoi(outbox_id=oid, statut="simule_dev", mode="simule_dev")

    oid = enregistrer_outbox(
        session,
        destinataire=email,
        sujet=sujet,
        template="invitation",
        payload=payload,
        tenant_id=tenant_id,
        statut="echec",
        dernier_erreur=(
            "RESEND_API_KEY absent — brancher la clé API (docs/13-s7-durcissement.md). "
            "Aucun envoi silencieux en production."
        ),
    )
    return ResultatEnvoi(outbox_id=oid, statut="echec", mode="echec")


def lister_outbox(
    session: Session,
    *,
    tenant_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Liste récente de l'outbox email (plateforme — pas de données mission)."""
    lim = max(1, min(int(limit), 200))
    if tenant_id is not None:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, destinataire, sujet, template, payload, "
                "statut, tentatives, dernier_erreur, cree_le, envoye_le "
                "FROM email_outbox WHERE tenant_id = :t "
                "ORDER BY id DESC LIMIT :lim"
            ),
            {"t": tenant_id, "lim": lim},
        ).mappings().all()
    else:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, destinataire, sujet, template, payload, "
                "statut, tentatives, dernier_erreur, cree_le, envoye_le "
                "FROM email_outbox ORDER BY id DESC LIMIT :lim"
            ),
            {"lim": lim},
        ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        payload = d.get("payload")
        if isinstance(payload, dict) and "token" in payload:
            d["payload"] = {**payload, "token": "[masque]"}
        out.append(d)
    return out


def statut_resend() -> dict[str, Any]:
    """Indique si Resend est branché — pour l'UI outbox."""
    branche = bool(config.resend_api_key)
    return {
        "resend_configure": branche,
        "resend_from": config.resend_from if branche else None,
        "mode_sans_cle": (
            None
            if branche
            else ("simule_dev" if config.env == "dev" else "echec")
        ),
        "note": (
            "Resend actif."
            if branche
            else (
                "RESEND_API_KEY absent — en ENV=dev les envois sont "
                "simule_dev (jeton UI + outbox). En prod : echec explicite."
            )
        ),
    }
