"""Configuration, chargee depuis l environnement."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Toujours le .env à la racine du projet (pas le cwd du process).
_RACINE = Path(__file__).resolve().parents[1]
_ENV_FILE = _RACINE / ".env"
_env_mtime: float | None = None


def _nettoyer_secret(valeur: Any) -> str:
    """Strip espaces, préfixe ``export``, guillemets — sans toucher au contenu utile."""
    if valeur is None:
        return ""
    s = str(valeur).strip()
    # BOM éventuel si collé depuis un éditeur Windows
    s = s.lstrip("\ufeff")
    if s.lower().startswith("export "):
        # export MOONSHOT_API_KEY=sk-… collé par erreur sur la même ligne valeur
        reste = s[7:].strip()
        if "=" in reste and not reste.startswith(("sk-", "re_", "wAw")):
            # forme « export NAME=value » entière dans la valeur → prendre après =
            reste = reste.split("=", 1)[1].strip()
        s = reste
    if len(s) >= 2 and (
        (s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")
    ):
        s = s[1:-1].strip()
    return s


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://app_revue:changeme@localhost:5433/revue_fiscale"
    database_url_admin: str = ""
    secret_key: str = ""  # obligatoire hors dev, verifie au demarrage
    env: str = "dev"
    # Provisionnement public POST /api/v1/provisionnement — ferme hors dev sauf flag.
    allow_public_provisioning: bool = False

    # Legacy mono-fournisseur (fallback si Moonshot/DeepSeek absents)
    modele_fournisseur: str = ""
    modele_cle_api: str = ""
    modele_nom: str = ""

    # Multi-LLM — clés uniquement via .env (jamais en dur dans le code)
    moonshot_api_key: str = ""
    # International (hors Chine) : api.moonshot.ai — CN : api.moonshot.cn
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    # Plateforme internationale : kimi-k3 = flagship vision/OCR (2.8T, vision native).
    # Anciens moonshot-v1-*-vision-preview : surtout api.moonshot.cn.
    moonshot_model: str = "kimi-k3"
    moonshot_model_vision: str = "kimi-k3"
    # K3 : thinking toujours ON — low|high|max (défaut API = max).
    # Extraction structurée identité : low (latence) ; high si doc très dégradé.
    moonshot_reasoning_effort: str = "low"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    # deepseek-chat = alias non-thinking de deepseek-v4-flash (compat)
    deepseek_model: str = "deepseek-chat"

    # Ordres de failover (ids : moonshot, deepseek, legacy)
    llm_provider_order: str = "moonshot,deepseek"
    llm_vision_order: str = "moonshot,deepseek,legacy"
    llm_text_order: str = "deepseek,moonshot,legacy"
    llm_timeout_seconds: float = 90.0
    # Vision multi-pages DFE : timeout HTTP (thinking + images)
    llm_vision_timeout_seconds: float = 180.0
    # Rasterisation PDF scan — DPI/pages bas pour latence (DFE = 1–2 p. typiques)
    llm_vision_pdf_max_pages: int = 3
    llm_vision_pdf_dpi: int = 140
    # JPEG compressé (vs PNG) pour réduire le payload base64
    llm_vision_jpeg_quality: int = 82

    # Sessions upload pièces sans fiche client créée — purge TTL (heures)
    pieces_session_ttl_hours: int = 72

    # Resend — OTP email inscription (jamais committer la clé)
    resend_api_key: str = ""
    resend_from: str = "Revue Fiscale <revuefiscal@erparchipro.com>"
    otp_ttl_seconds: int = 600
    otp_max_essais: int = 5
    otp_cooldown_seconds: int = 60
    jeton_inscription_ttl_seconds: int = 1800

    # Paystack — abonnement commercial (Visa + Mobile Money CI). Jamais fiscal CGI.
    # Sans PAYSTACK_SECRET_KEY : API 503 / UI désactivée. Webhook :
    # POST /api/v1/webhooks/paystack (HMAC SHA512, pas de JWT).
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    # Retour checkout ; défaut = {APP_PUBLIC_URL}/app/?vue=facturation&paystack=1
    paystack_callback_url: str = ""
    # Base publique de l'app (callbacks / liens) — ex. https://revue.example.ci
    app_public_url: str = "http://localhost:8000"

    # Mentions légales facture commerciale — vides / À CONFIRMER tant que 2AàZ
    # n'a pas fourni les vraies valeurs. Jamais inventer un RCCM / IDU.
    # FACTURE_SIEDGE = alias accepté pour siège (faute fréquente).
    facture_raison_sociale: str = "2AàZ SAS — À CONFIRMER"
    facture_siege: str = "À CONFIRMER"
    facture_siedge: str = ""  # alias env FACTURE_SIEDGE → prioritaire si non vide
    facture_rccm: str = "À CONFIRMER"
    facture_idu: str = "À CONFIRMER"
    facture_compte_bancaire: str = "À CONFIRMER"
    facture_regime_tva: str = "A_CONFIRMER"
    facture_taux_tva: str = "À CONFIRMER"

    # Compte cabinet démo /app — local uniquement (jamais en prod).
    # Affiché via /sante uniquement si ENV=dev ; UI gate aussi sur localhost.
    cabinet_demo_email: str = "admin@demo.local"
    cabinet_demo_password: str = "demo-demo1"  # noqa: S105 — compte démo local uniquement

    @field_validator(
        "moonshot_api_key",
        "deepseek_api_key",
        "modele_cle_api",
        "resend_api_key",
        "secret_key",
        "paystack_secret_key",
        "paystack_public_key",
        mode="before",
    )
    @classmethod
    def _secrets_propres(cls, v: Any) -> str:
        return _nettoyer_secret(v)

    @field_validator(
        "moonshot_base_url",
        "deepseek_base_url",
        "modele_fournisseur",
        "moonshot_model",
        "moonshot_model_vision",
        "moonshot_reasoning_effort",
        "deepseek_model",
        mode="before",
    )
    @classmethod
    def _urls_modeles_propres(cls, v: Any) -> str:
        return _nettoyer_secret(v) if v is not None else ""

    def provisionnement_public_autorise(self) -> bool:
        """Autorise le self-service uniquement en ENV=dev ou si le flag est true."""
        return self.env == "dev" or self.allow_public_provisioning

    def mentions_legales_facture(self) -> dict[str, str]:
        """Valeurs affichées sur le PDF facture — jamais inventées comme vraies."""
        siege = (self.facture_siedge or self.facture_siege or "").strip() or "À CONFIRMER"
        return {
            "raison_sociale": (self.facture_raison_sociale or "").strip()
            or "2AàZ SAS — À CONFIRMER",
            "siege": siege,
            "rccm": (self.facture_rccm or "").strip() or "À CONFIRMER",
            "idu": (self.facture_idu or "").strip() or "À CONFIRMER",
            "compte_bancaire": (self.facture_compte_bancaire or "").strip()
            or "À CONFIRMER",
            "regime_tva": (self.facture_regime_tva or "").strip() or "A_CONFIRMER",
            "taux_tva": (self.facture_taux_tva or "").strip() or "À CONFIRMER",
        }

    def alerte_format_moonshot(self) -> str | None:
        """Si une clé Moonshot est présente mais n'est pas au format sk-…"""
        cle = (self.moonshot_api_key or "").strip()
        if not cle:
            return None
        if cle.startswith("sk-"):
            return None
        prefix = "wAw" if cle.startswith("wAw") else cle[:4]
        return (
            f"MOONSHOT_API_KEY suspecte (préfixe {prefix}…, len={len(cle)}) — "
            "attendu format sk-… depuis platform.moonshot.ai / console Kimi. "
            "Coller la clé dans revue-fiscale-v5/.env puis make check-llm."
        )


def _mtime_env() -> float:
    try:
        return _ENV_FILE.stat().st_mtime if _ENV_FILE.is_file() else 0.0
    except OSError:
        return 0.0


def reload_config(*, force: bool = False) -> Config:
    """Recharge le `.env` dans le singleton ``config`` (mutation in-place).

    Utile car ``uvicorn --reload`` ne recharge pas dotenv si seul `.env` change,
    et les variables déjà injectées dans ``os.environ`` priment sur le fichier.
    On force ``load_dotenv(..., override=True)`` puis on réapplique sur le singleton
    pour que les modules ayant fait ``from backend.config import config`` voient
    les nouvelles valeurs.
    """
    global _env_mtime
    mtime = _mtime_env()
    if not force and _env_mtime is not None and mtime == _env_mtime:
        return config

    if _ENV_FILE.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(_ENV_FILE, override=True, encoding="utf-8-sig")
        except ImportError:
            pass

    nouveau = Config()
    for cle, valeur in nouveau.model_dump().items():
        setattr(config, cle, valeur)
    _env_mtime = mtime
    return config


config = Config()
_env_mtime = _mtime_env()
