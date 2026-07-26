"""Clients LLM multi-fournisseurs (OpenAI-compatible) + failover.

Priorité typique :
- Vision / OCR (images, PDF scan) → Moonshot d'abord
- Texte / extraction structurée → ordre configurable (défaut DeepSeek puis Moonshot)
- Fallback éventuel : ``MODELE_*`` (legacy)

Aucune clé n'est journalisée. Aucun montant fiscal moteur ici — brouillons IA seulement.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from backend.config import config, reload_config

logger = logging.getLogger(__name__)
_alerte_moonshot_emise = False

Capacite = Literal["chat", "vision"]
KindErreur = Literal[
    "auth",
    "quota",
    "timeout",
    "modele",
    "transport",
    "config",
    "inconnu",
]

# Statuts HTTP qui déclenchent un essai sur le fournisseur suivant
_STATUTS_FAILOVER = frozenset({401, 403, 408, 429, 500, 502, 503, 504})


def classifier_erreur_http(status: int | None, detail: str = "") -> KindErreur:
    """Classe une erreur fournisseur sans exposer de secret."""
    bas = (detail or "").casefold()
    if status in (401, 403) or "invalid authentication" in bas or "unauthorized" in bas:
        return "auth"
    if status == 429 or "rate limit" in bas or (
        "insufficient" in bas and "quota" in bas
    ):
        return "quota"
    if status == 404 or "model" in bas and (
        "not found" in bas or "does not exist" in bas or "unknown" in bas
    ):
        return "modele"
    if status in (408, 504) or "timeout" in bas:
        return "timeout"
    if status is not None and status >= 500:
        return "transport"
    return "inconnu"


def _kind_dominant(kinds: list[KindErreur]) -> KindErreur:
    """Priorité pour le message UX final (auth > quota > timeout > modele…)."""
    for cible in ("auth", "quota", "timeout", "modele", "transport", "config"):
        if cible in kinds:
            return cible  # type: ignore[return-value]
    return "inconnu"


class ErreurLlm(Exception):
    """Échec d'appel LLM (tous fournisseurs ou un seul)."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status: int | None = None,
        retryable: bool = False,
        kind: KindErreur = "inconnu",
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.kind = kind


@dataclass(frozen=True)
class ProviderSpec:
    """Spécification d'un fournisseur OpenAI-compatible."""

    id: str
    api_key: str
    base_url: str
    model_chat: str
    model_vision: str | None = None

    @property
    def disponible(self) -> bool:
        return bool((self.api_key or "").strip()) and bool((self.base_url or "").strip())

    @property
    def supports_vision(self) -> bool:
        return self.disponible and bool((self.model_vision or "").strip())


def _endpoint_chat(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return "https://api.openai.com/v1/chat/completions"
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    # DeepSeek accepte https://api.deepseek.com/chat/completions
    return f"{base}/chat/completions"


def lister_providers() -> list[ProviderSpec]:
    """Registry des fournisseurs connus (même sans clé)."""
    # Recharge .env si modifié (uvicorn --reload ne recharge pas dotenv seul).
    reload_config()
    global _alerte_moonshot_emise
    alerte = config.alerte_format_moonshot()
    if alerte and not _alerte_moonshot_emise:
        logger.warning("%s", alerte)
        _alerte_moonshot_emise = True

    moonshot = ProviderSpec(
        id="moonshot",
        api_key=(config.moonshot_api_key or "").strip(),
        # Défaut international (CI / hors Chine) ; CN = api.moonshot.cn
        base_url=(config.moonshot_base_url or "https://api.moonshot.ai/v1").strip(),
        model_chat=(config.moonshot_model or "kimi-k3").strip(),
        model_vision=(
            config.moonshot_model_vision or "kimi-k3"
        ).strip()
        or None,
    )
    deepseek = ProviderSpec(
        id="deepseek",
        api_key=(config.deepseek_api_key or "").strip(),
        base_url=(config.deepseek_base_url or "https://api.deepseek.com").strip(),
        model_chat=(config.deepseek_model or "deepseek-chat").strip(),
        # DeepSeek chat n'est pas multimodal vision dans l'API standard
        model_vision=None,
    )
    legacy_key = (config.modele_cle_api or "").strip()
    legacy_base = (config.modele_fournisseur or "").strip() or "https://api.openai.com/v1"
    legacy = ProviderSpec(
        id="legacy",
        api_key=legacy_key,
        base_url=legacy_base,
        model_chat=(config.modele_nom or "").strip() or "gpt-4o-mini",
        model_vision=(config.modele_nom or "").strip() or "gpt-4o-mini",
    )
    return [moonshot, deepseek, legacy]


def providers_configures() -> bool:
    return any(p.disponible for p in lister_providers())


def _parse_ordre(brut: str | None, defaut: str) -> list[str]:
    raw = (brut or "").strip() or defaut
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def ordre_providers(
    *,
    capacite: Capacite = "chat",
    vision_stricte: bool = False,
) -> list[ProviderSpec]:
    """Ordre de tentative selon capacité (vision vs texte).

    En vision, seuls les fournisseurs multimodaux sont retenus
    (``vision_stricte`` rappelé pour l'API ; le fallback texte-only
    n'est plus proposé — il inventait depuis le nom de fichier).
    """
    del vision_stricte  # toujours strict en vision ; param conservé pour l'appelant
    disponibles = {p.id: p for p in lister_providers() if p.disponible}
    if not disponibles:
        return []

    master = _parse_ordre(config.llm_provider_order, "moonshot,deepseek")
    if "legacy" in disponibles and "legacy" not in master:
        master = [*master, "legacy"]

    if capacite == "vision":
        vision_ids = _parse_ordre(config.llm_vision_order, "moonshot,deepseek,legacy")
        # Uniquement les fournisseurs capables vision — pas de fallback texte-only
        # (DeepSeek chat sans image invente depuis le nom de fichier / placeholders).
        ordered: list[str] = []
        for pid in vision_ids + master:
            if pid not in disponibles or pid in ordered:
                continue
            if disponibles[pid].supports_vision:
                ordered.append(pid)
        if "moonshot" in ordered:
            ordered = ["moonshot", *[x for x in ordered if x != "moonshot"]]
        return [disponibles[i] for i in ordered]

    # Texte / extraction structurée
    text_ids = _parse_ordre(
        config.llm_text_order,
        "deepseek,moonshot,legacy",
    )
    ordered_text: list[str] = []
    for pid in text_ids + master:
        if pid in disponibles and pid not in ordered_text:
            ordered_text.append(pid)
    return [disponibles[i] for i in ordered_text]


def mime_depuis_nom(nom: str) -> str:
    mime, _ = mimetypes.guess_type(nom)
    if mime and mime.startswith("image/"):
        return mime
    ext = (nom.rsplit(".", 1)[-1] if "." in nom else "").lower()
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "gif": "image/gif",
    }.get(ext, "image/png")


def image_data_uri(contenu: bytes, mime: str) -> str:
    b64 = base64.b64encode(contenu).decode("ascii")
    return f"data:{mime};base64,{b64}"


def message_user_avec_images(
    texte: str,
    images: list[tuple[str, bytes]],
) -> dict[str, Any]:
    """Message user multimodal (OpenAI / Moonshot : image_url en data URI).

    ``images`` : liste de ``(mime, octets)``.
    """
    if not images:
        return {"role": "user", "content": texte}
    parts: list[dict[str, Any]] = []
    for mime, brut in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": image_data_uri(brut, mime)},
            }
        )
    parts.append({"type": "text", "text": texte})
    return {"role": "user", "content": parts}


def _est_failover(exc: BaseException, status: int | None) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if status is not None and status in _STATUTS_FAILOVER:
        return True
    return False


def _messages_sans_images(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Réduit le contenu multimodal en texte seul (failover non-vision)."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        textes: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                textes.append(str(part.get("text") or ""))
            elif isinstance(part, dict) and part.get("type") == "image_url":
                textes.append("[image omise — fournisseur sans vision]")
        out.append({**msg, "content": "\n".join(t for t in textes if t)})
    return out


def _appeler_un(
    provider: ProviderSpec,
    *,
    messages: list[dict[str, Any]],
    modele: str,
    temperature: float,
    json_object: bool,
    timeout: float,
    capacite: Capacite = "chat",
) -> str:
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    # kimi-k3 : temperature fixe côté API — ne pas l'envoyer.
    # thinking toujours ON → reasoning_effort (low|high|max).
    corps: dict[str, Any] = {
        "model": modele,
        "messages": messages,
    }
    modele_bas = (modele or "").casefold()
    est_kimi_k3 = "kimi-k3" in modele_bas or modele_bas == "kimi-k3"
    if est_kimi_k3:
        effort = (config.moonshot_reasoning_effort or "low").strip().lower()
        # Alias UX « medium » → low (API K3 : low|high|max uniquement)
        if effort == "medium":
            effort = "low"
        if effort not in {"low", "high", "max"}:
            effort = "low"
        # Extraction structurée : ne pas forcer high si config = max
        if capacite == "vision" and effort == "max":
            effort = "high"
        corps["reasoning_effort"] = effort
        # Sortie JSON : budget réduit en low (latence) ; high/max plus généreux
        if effort == "low":
            corps["max_completion_tokens"] = 4096 if capacite == "vision" else 2048
        else:
            corps["max_completion_tokens"] = 8192 if capacite == "vision" else 4096
    else:
        corps["temperature"] = temperature

    if json_object:
        corps["response_format"] = {"type": "json_object"}

    url = _endpoint_chat(provider.base_url)
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, json=corps)
            status = r.status_code
            if status >= 400:
                # Corps sans clé ; utile pour diagnostiquer 401/429
                detail = (r.text or "")[:300]
                kind = classifier_erreur_http(status, detail)
                err = ErreurLlm(
                    f"{provider.id} HTTP {status}: {detail}",
                    provider=provider.id,
                    status=status,
                    retryable=_est_failover(Exception(), status),
                    kind=kind,
                )
                raise err
            data = r.json()
    except ErreurLlm:
        raise
    except httpx.TimeoutException as e:
        raise ErreurLlm(
            f"{provider.id} timeout",
            provider=provider.id,
            retryable=True,
            kind="timeout",
        ) from e
    except httpx.HTTPError as e:
        raise ErreurLlm(
            f"{provider.id} transport: {e}",
            provider=provider.id,
            retryable=True,
            kind="transport",
        ) from e

    try:
        message = data["choices"][0]["message"]
        contenu = message.get("content")
        if contenu is None or (isinstance(contenu, str) and not contenu.strip()):
            # Filet : certains modèles pensent d'abord — content peut arriver vide
            # si max trop bas ; on ne lit PAS reasoning_content comme JSON métier.
            raise KeyError("content vide")
        logger.info(
            "llm_http_ok provider=%s capacite=%s model=%s effort=%s duree_ms=%s",
            provider.id,
            capacite,
            modele,
            corps.get("reasoning_effort"),
            int((time.perf_counter() - t0) * 1000),
        )
        return str(contenu)
    except (KeyError, IndexError, TypeError) as e:
        raise ErreurLlm(
            f"{provider.id} réponse illisible",
            provider=provider.id,
            retryable=False,
            kind="inconnu",
        ) from e


def appeler_chat(
    messages: list[dict[str, Any]],
    *,
    capacite: Capacite = "chat",
    temperature: float = 0,
    json_object: bool = True,
    timeout: float | None = None,
    vision_stricte: bool = False,
) -> tuple[str, str, tuple[str, ...]]:
    """Appelle le premier fournisseur qui répond ; failover sur erreurs retryables.

    Retourne ``(contenu_texte, provider_id, failover_depuis)``.
    ``failover_depuis`` = ids des fournisseurs tentés avant le succès (sans clé).
    ``vision_stricte`` : pas de bascule vers un chat texte-seul (scans DFE).
    """
    ordre = ordre_providers(
        capacite=capacite, vision_stricte=vision_stricte and capacite == "vision"
    )
    if not ordre:
        if capacite == "vision" and vision_stricte:
            raise ErreurLlm(
                "aucun fournisseur vision configuré pour PDF scan",
                kind="config",
            )
        raise ErreurLlm(
            "aucun fournisseur LLM configuré",
            kind="config",
        )

    if timeout is not None:
        timeout_s = float(timeout)
    elif capacite == "vision":
        timeout_s = float(config.llm_vision_timeout_seconds or 180.0)
    else:
        timeout_s = float(config.llm_timeout_seconds or 90.0)
    erreurs: list[str] = []
    kinds: list[KindErreur] = []
    derniers_status: list[int] = []
    failover_depuis: list[str] = []

    for provider in ordre:
        if capacite == "vision" and provider.supports_vision:
            modele = provider.model_vision or provider.model_chat
            msgs = messages
        else:
            modele = provider.model_chat
            # Évite d'envoyer des data-URI image à un chat texte-only
            msgs = (
                _messages_sans_images(messages)
                if capacite == "vision"
                else messages
            )
        try:
            contenu = _appeler_un(
                provider,
                messages=msgs,
                modele=modele,
                temperature=temperature,
                json_object=json_object,
                timeout=timeout_s,
                capacite=capacite,
            )
            logger.info(
                "llm_ok provider=%s capacite=%s model=%s failover_depuis=%s",
                provider.id,
                capacite,
                modele,
                failover_depuis,
            )
            return contenu, provider.id, tuple(failover_depuis)
        except ErreurLlm as e:
            msg = str(e)
            erreurs.append(msg)
            kinds.append(e.kind)
            if e.status is not None:
                derniers_status.append(e.status)
            if e.retryable or _est_failover(e, e.status):
                failover_depuis.append(provider.id)
                logger.warning(
                    "llm_failover provider=%s status=%s kind=%s raison=%s",
                    provider.id,
                    e.status,
                    e.kind,
                    msg[:200],
                )
                continue
            logger.error(
                "llm_echec_non_retryable provider=%s kind=%s raison=%s",
                provider.id,
                e.kind,
                msg[:200],
            )
            raise

    kind = _kind_dominant(kinds)
    status_final = derniers_status[-1] if derniers_status else None
    raise ErreurLlm(
        "tous les fournisseurs LLM ont échoué : " + " | ".join(erreurs[:5]),
        status=status_final,
        kind=kind,
        retryable=kind in {"quota", "timeout", "transport"},
    )
