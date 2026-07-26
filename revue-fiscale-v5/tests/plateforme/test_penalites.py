"""Barème indicatif pénalités + intérêts de retard — pur, déterministe."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.plateforme.penalites import (
    ErreurChiffragePenalites,
    chiffrer_penalites,
    chiffrer_risque,
    date_exigibilite_estimee,
    mois_de_retard,
)

AUJOURD_HUI = date(2026, 7, 26)


def test_zero_mois_de_retard_aucun_interet():
    r = chiffrer_penalites(Decimal("1000000"), mois_retard=0)
    assert r["interet_retard"] == Decimal("0")
    assert r["penalite_assiette"] == Decimal("250000")
    assert r["total_estime"] == Decimal("1250000")
    assert r["mois_retard"] == 0
    assert any("indicatif" in h.lower() for h in r["hypotheses"])
    assert any("associé" in h for h in r["hypotheses"])


def test_bonne_foi_12_mois():
    # 0,5 % × 12 mois = 6 % ; assiette 25 %.
    r = chiffrer_penalites(Decimal("2000000"), mois_retard=12)
    assert r["droit_simple"] == Decimal("2000000")
    assert r["interet_retard"] == Decimal("120000")
    assert r["penalite_assiette"] == Decimal("500000")
    assert r["total_estime"] == Decimal("2620000")


def test_plafond_interet_50_pourcent():
    # 0,5 % × 200 mois = 100 % → plafonné à 50 % du droit simple.
    r = chiffrer_penalites(Decimal("1000000"), mois_retard=200)
    assert r["interet_retard"] == Decimal("500000")
    assert any("plafonné à 50 %" in h for h in r["hypotheses"])


def test_mauvaise_foi_50_pourcent():
    r = chiffrer_penalites(
        Decimal("1000000"), mois_retard=0, caractere="mauvaise_foi"
    )
    assert r["penalite_assiette"] == Decimal("500000")
    assert r["caractere"] == "mauvaise_foi"
    assert any("mauvaise foi" in h for h in r["hypotheses"])


def test_entrees_invalides():
    with pytest.raises(ErreurChiffragePenalites):
        chiffrer_penalites(Decimal("-1"), mois_retard=1)
    with pytest.raises(ErreurChiffragePenalites):
        chiffrer_penalites(Decimal("1"), mois_retard=-1)
    with pytest.raises(ErreurChiffragePenalites):
        chiffrer_penalites(Decimal("1"), mois_retard=1, caractere="dolosif")
    with pytest.raises(ErreurChiffragePenalites):
        chiffrer_penalites(Decimal("1"))  # ni mois_retard ni date


def test_mois_de_retard_calcul():
    d = date(2024, 12, 31)
    assert mois_de_retard(d, aujourd_hui=date(2024, 12, 31)) == 0
    assert mois_de_retard(d, aujourd_hui=date(2024, 6, 1)) == 0
    assert mois_de_retard(d, aujourd_hui=date(2025, 1, 30)) == 0
    assert mois_de_retard(d, aujourd_hui=date(2025, 1, 31)) == 1
    assert mois_de_retard(d, aujourd_hui=AUJOURD_HUI) == 18


def test_date_exigibilite_estimee_fin_exercice():
    assert date_exigibilite_estimee(2024) == date(2024, 12, 31)


def test_chiffrer_risque_registre():
    r = chiffrer_risque(
        {"montant_estime": "1000000", "exercice_origine": 2024},
        aujourd_hui=AUJOURD_HUI,
    )
    assert r is not None
    # 18 mois × 0,5 % = 9 % ; assiette 25 % (bonne foi présumée).
    assert r["mois_retard"] == 18
    assert r["interet_retard"] == "90000"
    assert r["penalite_assiette"] == "250000"
    assert r["total_estime"] == "1340000"
    assert r["caractere"] == "bonne_foi"
    assert isinstance(r["hypotheses"], list) and r["hypotheses"]


def test_chiffrer_risque_sans_montant_none():
    assert chiffrer_risque({"montant_estime": None, "exercice_origine": 2024}) is None
    assert chiffrer_risque({"montant_estime": "", "exercice_origine": 2024}) is None
    assert (
        chiffrer_risque({"montant_estime": "100", "exercice_origine": 0}) is None
    )
