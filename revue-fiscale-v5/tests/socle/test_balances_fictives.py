"""Balances SYSCOHADA synthétiques FICTIF — calage mapping / contrôles."""
from __future__ import annotations

from pathlib import Path

from backend.socle.controles import controler_balance
from backend.socle.lecteurs.balance import parser_balance

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_balance_fictif_commerce_equilibree():
    lignes = parser_balance((FIXTURES / "balance_fictif_commerce.csv").read_bytes())
    assert all("[FICTIF]" in (ligne.libelle or "") for ligne in lignes)
    assert controler_balance(lignes) == []


def test_balance_fictif_services_equilibree():
    lignes = parser_balance((FIXTURES / "balance_fictif_services.csv").read_bytes())
    assert len(lignes) >= 8
    assert controler_balance(lignes) == []


def test_balance_fictif_desequilibree_detectee():
    lignes = parser_balance(
        (FIXTURES / "balance_fictif_desequilibree.csv").read_bytes()
    )
    anomalies = controler_balance(lignes)
    assert any("desequilibree" in a for a in anomalies)
