"""OTP email inscription via Resend — hash HMAC, rate-limit, TTL."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import config
from backend.plateforme.emails_jetables import valider_email_inscription

logger = logging.getLogger(__name__)


class ErreurOtp(Exception):
    """Échec flux OTP / inscription."""


@dataclass(frozen=True)
class DemarrerOtpResultat:
    email: str
    expire_le: datetime
    otp_debug: str | None
    renvoye: bool


@dataclass(frozen=True)
class VerifierOtpResultat:
    email: str
    jeton_inscription: str


def _secret() -> bytes:
    cle = config.secret_key or "dev-only-otp-secret"
    return cle.encode("utf-8")


def hasher(valeur: str) -> str:
    return hmac.new(_secret(), valeur.encode("utf-8"), hashlib.sha256).hexdigest()


def generer_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generer_jeton_inscription() -> str:
    return secrets.token_urlsafe(32)


def _maintenant() -> datetime:
    return datetime.now(UTC)


def _envoyer_resend(*, destinataire: str, code: str) -> None:
    if not config.resend_api_key:
        raise ErreurOtp("envoi email indisponible : RESEND_API_KEY manquant")
    corps = {
        "from": config.resend_from,
        "to": [destinataire],
        "subject": "Votre code de vérification — Revue Fiscale",
        "html": (
            "<p>Bonjour,</p>"
            f"<p>Votre code de vérification est <strong>{code}</strong>.</p>"
            f"<p>Il expire dans {config.otp_ttl_seconds // 60} minutes.</p>"
            "<p>Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p>"
        ),
        "text": (
            f"Votre code de vérification Revue Fiscale : {code}\n"
            f"Expire dans {config.otp_ttl_seconds // 60} minutes.\n"
        ),
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
        logger.error("Resend erreur %s : %s", r.status_code, r.text[:500])
        raise ErreurOtp("échec d'envoi de l'email de vérification")


def demarrer_otp(session: Session, email_brut: str) -> DemarrerOtpResultat:
    try:
        email = valider_email_inscription(email_brut)
    except ValueError as e:
        raise ErreurOtp(str(e)) from e

    # Email déjà abonné ?
    existe = session.execute(
        text("SELECT 1 FROM auth_lookup_utilisateur(:e)"),
        {"e": email},
    ).scalar_one_or_none()
    if existe:
        raise ErreurOtp("cet email est déjà associé à un espace")

    maintenant = _maintenant()
    row = session.execute(
        text(
            "SELECT id, derniere_demande_le, verifie_le FROM inscription_pending "
            "WHERE email = :e"
        ),
        {"e": email},
    ).mappings().one_or_none()

    if row is not None:
        derniere = row["derniere_demande_le"]
        if derniere is not None:
            if derniere.tzinfo is None:
                derniere = derniere.replace(tzinfo=UTC)
            delta = (maintenant - derniere).total_seconds()
            if delta < config.otp_cooldown_seconds:
                reste = int(config.otp_cooldown_seconds - delta)
                raise ErreurOtp(f"patientez {reste}s avant de renvoyer un code")

    otp = generer_otp()
    expire = maintenant + timedelta(seconds=config.otp_ttl_seconds)
    otp_h = hasher(f"{email}:{otp}")

    if row is None:
        session.execute(
            text(
                "INSERT INTO inscription_pending "
                "(email, otp_hash, expire_le, essais, verifie_le, jeton_hash, "
                "jeton_expire_le, derniere_demande_le) "
                "VALUES (:e, :h, :exp, 0, NULL, NULL, NULL, :now)"
            ),
            {"e": email, "h": otp_h, "exp": expire, "now": maintenant},
        )
        renvoye = False
    else:
        session.execute(
            text(
                "UPDATE inscription_pending SET "
                "otp_hash = :h, expire_le = :exp, essais = 0, "
                "verifie_le = NULL, jeton_hash = NULL, jeton_expire_le = NULL, "
                "derniere_demande_le = :now "
                "WHERE email = :e"
            ),
            {"e": email, "h": otp_h, "exp": expire, "now": maintenant},
        )
        renvoye = True

    session.flush()

    # Envoi : Resend si clé ; en prod obligatoire ; en dev sans clé ou échec Resend → otp_debug.
    otp_debug: str | None = None
    if config.resend_api_key:
        try:
            _envoyer_resend(destinataire=email, code=otp)
        except ErreurOtp:
            if config.env != "dev":
                raise
            logger.exception(
                "Resend indisponible — OTP servi en otp_debug (ENV=dev) pour %s", email
            )
    elif config.env == "dev":
        logger.warning("OTP %s pour %s (pas de RESEND_API_KEY — debug local)", otp, email)
    else:
        raise ErreurOtp("service email non configuré")

    if config.env == "dev":
        otp_debug = otp

    return DemarrerOtpResultat(
        email=email, expire_le=expire, otp_debug=otp_debug, renvoye=renvoye
    )


def verifier_otp(session: Session, email_brut: str, code: str) -> VerifierOtpResultat:
    try:
        email = valider_email_inscription(email_brut)
    except ValueError as e:
        raise ErreurOtp(str(e)) from e

    code_n = (code or "").strip().replace(" ", "")
    if not code_n.isdigit() or len(code_n) != 6:
        raise ErreurOtp("code invalide")

    row = session.execute(
        text(
            "SELECT id, otp_hash, expire_le, essais FROM inscription_pending "
            "WHERE email = :e"
        ),
        {"e": email},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurOtp("aucune demande de vérification pour cet email")

    maintenant = _maintenant()
    expire = row["expire_le"]
    if expire is not None and expire.tzinfo is None:
        expire = expire.replace(tzinfo=UTC)
    if expire is not None and expire < maintenant:
        raise ErreurOtp("code expiré — renvoyez un nouveau code")

    if int(row["essais"]) >= config.otp_max_essais:
        raise ErreurOtp("trop de tentatives — renvoyez un nouveau code")

    attendu = hasher(f"{email}:{code_n}")
    if not hmac.compare_digest(attendu, str(row["otp_hash"])):
        session.execute(
            text(
                "UPDATE inscription_pending SET essais = essais + 1 WHERE email = :e"
            ),
            {"e": email},
        )
        session.flush()
        raise ErreurOtp("code incorrect")

    jeton = generer_jeton_inscription()
    jeton_exp = maintenant + timedelta(seconds=config.jeton_inscription_ttl_seconds)
    session.execute(
        text(
            "UPDATE inscription_pending SET "
            "verifie_le = :now, jeton_hash = :jh, jeton_expire_le = :je, essais = 0 "
            "WHERE email = :e"
        ),
        {
            "e": email,
            "now": maintenant,
            "jh": hasher(jeton),
            "je": jeton_exp,
        },
    )
    session.flush()
    return VerifierOtpResultat(email=email, jeton_inscription=jeton)


def consommer_jeton_inscription(session: Session, jeton: str) -> str:
    """Valide le jeton post-OTP et retourne l'email. Ne consomme pas encore (finaliser)."""
    if not jeton or len(jeton) < 16:
        raise ErreurOtp("jeton d'inscription invalide")
    jh = hasher(jeton)
    row = session.execute(
        text(
            "SELECT email, verifie_le, jeton_expire_le FROM inscription_pending "
            "WHERE jeton_hash = :jh"
        ),
        {"jh": jh},
    ).mappings().one_or_none()
    if row is None or row["verifie_le"] is None:
        raise ErreurOtp("jeton d'inscription invalide ou expiré")
    exp = row["jeton_expire_le"]
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if exp is not None and exp < _maintenant():
        raise ErreurOtp("jeton d'inscription expiré — recommencez la vérification email")
    return str(row["email"])


def supprimer_pending(session: Session, email: str) -> None:
    session.execute(
        text("DELETE FROM inscription_pending WHERE email = :e"),
        {"e": email},
    )
    session.flush()
