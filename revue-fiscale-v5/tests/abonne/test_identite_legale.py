"""Tests identité légale contribuable — complétude documentaire, pas de fiscalité."""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.abonne.contribuable_identite import (
    ErreurIdentiteLegale,
    completude_identite,
    normaliser_payload,
    serialiser_identite,
    valider_identite_legale,
)


def test_pm_complet_ok():
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        dfe=None,  # DFE optionnel — NCC = n° porté sur la DFE
        regime_fiscal="reel",
        forme_juridique="SA",
        capital_social="10_000_000".replace("_", ""),
        mois_cloture=12,
        activite_principale="Commerce — gros",
        commune="Abidjan",
        siege_social="Plateau, bd de la République",
        centre_impots="CDI Plateau",
        date_immatriculation="2020-03-15",
    )
    valider_identite_legale(p)
    assert p["capital_social"] == Decimal("10000000.00")
    assert p["mois_cloture"] == 12
    c = completude_identite(p)
    assert c["complet"] is True
    assert c["pct"] == 100


def test_pm_sans_dfe_api_ok():
    """API n'exige plus la DFE : le n° sur la pièce est le NCC."""
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        regime_fiscal="reel",
        forme_juridique="SA",
        capital_social=1,
    )
    valider_identite_legale(p)
    c = completude_identite(p)
    assert "DFE" not in c["manquants"]


def test_pm_completude_sans_capital():
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        regime_fiscal="ime",
        forme_juridique="SARL",
        activite_principale="Services",
        commune="Abidjan",
        siege_social="Cocody",
        centre_impots="CIME Cocody",
    )
    valider_identite_legale(p)  # API permissive sur capital
    c = completude_identite(p)
    assert "Capital social" in c["manquants"]
    assert c["complet"] is False


def test_pm_completude_sans_centre_impots():
    p = normaliser_payload(
        denomination="SA Démo",
        ncc="CI-1",
        forme="pm",
        rccm="RCCM-1",
        regime_fiscal="reel",
        forme_juridique="SA",
        capital_social=1,
        activite_principale="Industrie / manufacture",
        commune="Bouaké",
        siege_social="Centre-ville",
    )
    valider_identite_legale(p)
    c = completude_identite(p)
    assert "Centre des impôts" in c["manquants"]


def test_pp_allégé():
    p = normaliser_payload(
        denomination="Koné Awa",
        ncc="CI-PP-1",
        forme="pp",
        regime_fiscal="tee",
        activite_principale="Professions libérales",
        commune="Yamoussoukro",
        centre_impots="CDI Yamoussoukro",
    )
    assert p["forme_juridique"] == "EI"
    assert p["mois_cloture"] == 12  # défaut année civile
    valider_identite_legale(p)
    c = completude_identite(p)
    assert c["complet"] is True


def test_mois_cloture_invalide():
    with pytest.raises(ErreurIdentiteLegale, match="mois_cloture"):
        normaliser_payload(
            denomination="X",
            forme="pp",
            ncc="1",
            regime_fiscal="reel",
            mois_cloture=13,
        )


def test_capital_negatif():
    with pytest.raises(ErreurIdentiteLegale, match="capital_social"):
        normaliser_payload(
            denomination="X",
            forme="pm",
            ncc="1",
            regime_fiscal="reel",
            capital_social=-1,
        )


def test_serialiser_identite():
    out = serialiser_identite(
        {
            "capital_social": Decimal("1500.5"),
            "date_immatriculation": __import__("datetime").date(2021, 1, 2),
        }
    )
    assert out["capital_social"] == 1500.5
    assert out["date_immatriculation"] == "2021-01-02"
