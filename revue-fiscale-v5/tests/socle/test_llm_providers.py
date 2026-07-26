"""Failover multi-provider LLM — mocks HTTP, sans clés réelles."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.socle import llm_providers


def _reponse_ok(contenu: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "choices": [{"message": {"content": json.dumps(contenu)}}]
    }
    r.text = ""
    return r


def _reponse_err(status: int, body: str = "err") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = body
    r.json.side_effect = ValueError("pas de json")
    return r


@pytest.fixture
def providers_mock(monkeypatch):
    monkeypatch.setattr(llm_providers.config, "moonshot_api_key", "sk-moon-test")
    monkeypatch.setattr(
        llm_providers.config, "moonshot_base_url", "https://api.moonshot.cn/v1"
    )
    monkeypatch.setattr(llm_providers.config, "moonshot_model", "moonshot-v1-8k")
    monkeypatch.setattr(
        llm_providers.config,
        "moonshot_model_vision",
        "moonshot-v1-8k-vision-preview",
    )
    monkeypatch.setattr(llm_providers.config, "deepseek_api_key", "sk-deep-test")
    monkeypatch.setattr(
        llm_providers.config, "deepseek_base_url", "https://api.deepseek.com"
    )
    monkeypatch.setattr(llm_providers.config, "deepseek_model", "deepseek-chat")
    monkeypatch.setattr(llm_providers.config, "modele_cle_api", "")
    monkeypatch.setattr(
        llm_providers.config, "llm_provider_order", "moonshot,deepseek"
    )
    monkeypatch.setattr(
        llm_providers.config, "llm_text_order", "deepseek,moonshot,legacy"
    )
    monkeypatch.setattr(
        llm_providers.config, "llm_vision_order", "moonshot,deepseek,legacy"
    )
    monkeypatch.setattr(llm_providers.config, "llm_timeout_seconds", 5.0)


def test_ordre_texte_prefere_deepseek(providers_mock):
    ids = [p.id for p in llm_providers.ordre_providers(capacite="chat")]
    assert ids[0] == "deepseek"
    assert "moonshot" in ids


def test_ordre_vision_prefere_moonshot(providers_mock):
    ids = [p.id for p in llm_providers.ordre_providers(capacite="vision")]
    assert ids[0] == "moonshot"
    # Pas de DeepSeek texte-only en vision (évite hallucination scan)
    assert "deepseek" not in ids


def test_ordre_vision_stricte_accepte_param(providers_mock):
    ids = [
        p.id
        for p in llm_providers.ordre_providers(
            capacite="vision", vision_stricte=True
        )
    ]
    assert ids == ["moonshot"]


def test_failover_429_puis_succes(providers_mock, monkeypatch):
    """Moonshot 429 → DeepSeek OK."""
    monkeypatch.setattr(
        llm_providers.config, "llm_text_order", "moonshot,deepseek"
    )
    appels: list[str] = []

    def fake_post(url, headers=None, json=None):  # noqa: A002
        auth = (headers or {}).get("Authorization", "")
        assert auth in {"Bearer sk-moon-test", "Bearer sk-deep-test"}
        modele = str((json or {}).get("model", ""))
        if "moonshot" in url or modele.startswith("moonshot"):
            appels.append("moonshot")
            return _reponse_err(429, "rate limit")
        appels.append("deepseek")
        return _reponse_ok({"ok": True})

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.side_effect = fake_post

    with patch("backend.socle.llm_providers.httpx.Client", return_value=client):
        contenu, provider, failover = llm_providers.appeler_chat(
            [{"role": "user", "content": "hi"}],
            capacite="chat",
            json_object=True,
        )
    assert provider == "deepseek"
    assert failover == ("moonshot",)
    assert json.loads(contenu)["ok"] is True
    assert appels == ["moonshot", "deepseek"]


def test_failover_timeout_moonshot_vers_deepseek(providers_mock, monkeypatch):
    monkeypatch.setattr(
        llm_providers.config, "llm_text_order", "moonshot,deepseek"
    )
    n = {"i": 0}

    def fake_post(url, headers=None, json=None):  # noqa: A002
        n["i"] += 1
        if n["i"] == 1:
            raise httpx.TimeoutException("timeout")
        return _reponse_ok({"champs": {}})

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.side_effect = fake_post

    with patch("backend.socle.llm_providers.httpx.Client", return_value=client):
        _, provider, failover = llm_providers.appeler_chat(
            [{"role": "user", "content": "x"}],
            capacite="chat",
        )
    assert provider == "deepseek"
    assert failover == ("moonshot",)


def test_auth_error_failover(providers_mock, monkeypatch):
    monkeypatch.setattr(
        llm_providers.config, "llm_text_order", "moonshot,deepseek"
    )
    n = {"i": 0}

    def fake_post(url, headers=None, json=None):  # noqa: A002
        n["i"] += 1
        if n["i"] == 1:
            return _reponse_err(401, "unauthorized")
        return _reponse_ok({"ok": True})

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.side_effect = fake_post

    with patch("backend.socle.llm_providers.httpx.Client", return_value=client):
        _, provider, failover = llm_providers.appeler_chat(
            [{"role": "user", "content": "x"}],
            capacite="chat",
        )
    assert provider == "deepseek"
    assert failover == ("moonshot",)


def test_aucun_provider_leve(monkeypatch):
    monkeypatch.setattr(llm_providers.config, "moonshot_api_key", "")
    monkeypatch.setattr(llm_providers.config, "deepseek_api_key", "")
    monkeypatch.setattr(llm_providers.config, "modele_cle_api", "")
    with pytest.raises(llm_providers.ErreurLlm, match="aucun fournisseur"):
        llm_providers.appeler_chat([{"role": "user", "content": "x"}])


def test_message_user_multimodal_data_uri():
    msg = llm_providers.message_user_avec_images(
        "Lis ce DFE",
        [("image/png", b"\x89PNG\r\n")],
    )
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0]["type"] == "image_url"
    url = msg["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert msg["content"][1]["type"] == "text"


def test_classifier_erreur_http():
    assert llm_providers.classifier_erreur_http(401, "Invalid Authentication") == "auth"
    assert llm_providers.classifier_erreur_http(429, "rate limit") == "quota"
    assert llm_providers.classifier_erreur_http(404, "model not found") == "modele"
    assert llm_providers.classifier_erreur_http(None, "timeout") == "timeout"


def test_failover_vision_401_kind_auth(providers_mock):
    """Vision : seul Moonshot → 401 agrégé avec kind=auth."""

    def fake_post(url, headers=None, json=None):  # noqa: A002
        return _reponse_err(
            401, '{"error":{"message":"Invalid Authentication"}}'
        )

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.side_effect = fake_post

    with patch("backend.socle.llm_providers.httpx.Client", return_value=client):
        with pytest.raises(llm_providers.ErreurLlm) as ei:
            llm_providers.appeler_chat(
                [{"role": "user", "content": "x"}],
                capacite="vision",
                vision_stricte=True,
            )
    assert ei.value.kind == "auth"
    assert ei.value.status == 401


def test_message_erreur_llm_fr_distingue_auth():
    from backend.abonne.extraction_identite import message_erreur_llm_fr

    err = llm_providers.ErreurLlm(
        "tous les fournisseurs LLM ont échoué : moonshot HTTP 401: Invalid",
        status=401,
        kind="auth",
    )
    msg = message_erreur_llm_fr(err)
    assert "authentification" in msg.casefold()
    assert "moonshot" not in msg.casefold()
    assert "kimi" not in msg.casefold()
    assert "MOONSHOT" not in msg
    assert "API_KEY" not in msg
    assert "timeout, saturation ou auth" not in msg.casefold()


def test_message_erreur_llm_fr_distingue_quota():
    from backend.abonne.extraction_identite import message_erreur_llm_fr

    err = llm_providers.ErreurLlm(
        "tous les fournisseurs LLM ont échoué : deepseek HTTP 429",
        status=429,
        kind="quota",
    )
    msg = message_erreur_llm_fr(err)
    assert "satur" in msg.casefold() or "réessayez" in msg.casefold()
    assert "deepseek" not in msg.casefold()
    assert "429" not in msg
    assert "HTTP" not in msg

