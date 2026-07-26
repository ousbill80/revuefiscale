"""Smoke auth Moonshot + DeepSeek — sans exposer les secrets.

Usage :
  cd revue-fiscale-v5
  make check-llm
  .venv/bin/python -m backend.scripts.check_llm
"""
from __future__ import annotations

import sys

import httpx

from backend.config import _ENV_FILE, config, reload_config
from backend.socle.llm_providers import _endpoint_chat, lister_providers


def _masquer(cle: str) -> str:
    cle = (cle or "").strip()
    if not cle:
        return "(vide)"
    if cle.startswith("wAw"):
        pref = "wAw"
    elif cle.startswith("sk-"):
        pref = "sk-"
    else:
        pref = cle[:4]
    suffix = cle[-4:] if len(cle) >= 4 else cle
    return f"{pref}…{suffix} (len={len(cle)})"


def _probe(nom: str, api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    if not (api_key or "").strip():
        return False, "clé absente"
    url = _endpoint_chat(base_url)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        return False, f"transport {type(e).__name__}"

    if r.status_code == 200:
        return True, f"HTTP 200 model={model}"
    detail = (r.text or "")[:120].replace(api_key, "***")
    return False, f"HTTP {r.status_code} {detail}"


def main() -> int:
    reload_config(force=True)
    print(f"Fichier .env : {_ENV_FILE}")
    print(f"  existe={_ENV_FILE.is_file()}")
    print()

    alerte = config.alerte_format_moonshot()
    if alerte:
        print(f"⚠  {alerte}")
        print()

    providers = {p.id: p for p in lister_providers()}
    moon = providers.get("moonshot")
    deep = providers.get("deepseek")

    print("--- Moonshot (vision / scans) ---")
    if moon is None:
        print("  non enregistré")
        ok_m = False
    else:
        print(f"  key  : {_masquer(moon.api_key)}")
        print(f"  base : {moon.base_url}")
        print(f"  chat : {moon.model_chat}")
        print(f"  vision: {moon.model_vision}")
        ok_m, msg_m = _probe(
            "moonshot",
            moon.api_key,
            moon.base_url,
            moon.model_chat or "moonshot-v1-8k",
        )
        print(f"  auth : {'OK' if ok_m else 'ÉCHEC'} — {msg_m}")
        if not ok_m and moon.api_key and not moon.api_key.startswith("sk-"):
            print(
                "  → Coller une clé Moonshot/Kimi format sk-… dans "
                "revue-fiscale-v5/.env (ligne MOONSHOT_API_KEY=), "
                "puis relancer make check-llm."
            )

    print()
    print("--- DeepSeek (texte / PDF texte) ---")
    if deep is None:
        print("  non enregistré")
        ok_d = False
    else:
        print(f"  key  : {_masquer(deep.api_key)}")
        print(f"  base : {deep.base_url}")
        print(f"  model: {deep.model_chat}")
        ok_d, msg_d = _probe(
            "deepseek",
            deep.api_key,
            deep.base_url,
            deep.model_chat or "deepseek-chat",
        )
        print(f"  auth : {'OK' if ok_d else 'ÉCHEC'} — {msg_d}")

    print()
    if ok_d and not ok_m:
        print(
            "Bilan : DeepSeek OK — extraction PDF texte utilisable. "
            "Scans / images : Moonshot requis (clé sk-…)."
        )
        return 2
    if ok_m and ok_d:
        print("Bilan : Moonshot + DeepSeek OK.")
        return 0
    if ok_m:
        print("Bilan : Moonshot OK ; DeepSeek à corriger (failover texte limité).")
        return 0
    print("Bilan : aucun fournisseur authentifié — corriger .env.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
