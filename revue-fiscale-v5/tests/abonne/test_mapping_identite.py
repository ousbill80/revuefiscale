"""Mapping régime / forme juridique — aliases CI vers valeurs formulaire."""
from __future__ import annotations

import pytest

from backend.abonne.extraction_identite import (
    _normaliser_champs,
    libelle_provider,
    mapper_forme_juridique,
    mapper_regime_fiscal,
)


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("reel", "reel"),
        ("RNI", "reel"),
        ("Réel normal d'imposition", "reel"),
        ("simplifie", "reel_simplifie"),
        ("RSI", "reel_simplifie"),
        ("IME", "ime"),
        ("RME", "ime"),
        ("micro-entreprise", "ime"),
        ("TEE", "tee"),
        ("TCE", "tce"),
        ("liberatoire", "autre"),
        ("", None),
        (None, None),
        ("inconnu-xyz", None),
    ],
)
def test_mapper_regime_fiscal(brut, attendu):
    assert mapper_regime_fiscal(brut) == attendu


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("SARL", "SARL"),
        ("sarl", "SARL"),
        ("S.A.R.L.", "SARL"),
        ("Société anonyme", "SA"),
        ("SASU", "SASU"),
        ("entrepreneur individuel", "EI"),
        ("COOP-CA", "COOP-CA"),
        ("", None),
        ("forme inconnue", None),
    ],
)
def test_mapper_forme_juridique(brut, attendu):
    assert mapper_forme_juridique(brut) == attendu


def test_normaliser_champs_mappe_aliases():
    out = _normaliser_champs(
        {
            "denomination": "Demo SA",
            "regime_fiscal": "RNI",
            "forme_juridique": "s.a.r.l.",
            "forme": "pm",
        }
    )
    assert out["regime_fiscal"] == "reel"
    assert out["forme_juridique"] == "SARL"
    assert out["forme"] == "pm"
    assert out["denomination"] == "Demo SA"


def test_libelle_provider_failover():
    assert libelle_provider("deepseek") == "via DeepSeek"
    assert libelle_provider("deepseek", ("moonshot",)) == (
        "via DeepSeek (bascule après Moonshot)"
    )
    assert libelle_provider(None) is None


def test_mapper_regime_im_vers_ime():
    assert mapper_regime_fiscal("IM") == "ime"


def test_message_sans_provider():
    from backend.abonne.extraction_identite import _message_sans_provider

    assert "DeepSeek" not in (
        _message_sans_provider("Brouillon via DeepSeek (bascule après Moonshot)")
        or ""
    )
    assert "Moonshot" not in (_message_sans_provider("via Moonshot") or "")
    assert "Kimi" not in (
        _message_sans_provider("vérifiez MOONSHOT_API_KEY console /Kimi") or ""
    )
    assert "MOONSHOT" not in (
        _message_sans_provider("vérifiez MOONSHOT_API_KEY (format sk-…)") or ""
    )


def test_champs_manquants():
    from backend.abonne.extraction_identite import _champs_manquants

    m = _champs_manquants({"denomination": "X", "ncc": None, "forme": "pm"})
    assert "ncc" in m
    assert "denomination" not in m
    assert "forme" not in m
