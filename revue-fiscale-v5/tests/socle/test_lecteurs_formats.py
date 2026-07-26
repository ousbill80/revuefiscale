"""Lecteurs EF / grand livre / FEC — parsing et controles."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backend.socle.controles import (
    controler_etats_financiers,
    controler_fec,
    controler_grand_livre,
)
from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.lecteurs.etats_financiers import parser_etats_financiers
from backend.socle.lecteurs.fec import parser_fec
from backend.socle.lecteurs.grand_livre import parser_grand_livre
from backend.socle.modeles import EcritureGrandLivre, LigneEtatFinancier
from backend.socle.service import (
    agreger_ecritures_en_balance,
    etats_financiers_en_balance,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"


def test_parser_etats_financiers_csv():
    lignes = parser_etats_financiers((FIXTURES / "etats_financiers_demo.csv").read_bytes())
    assert len(lignes) == 4
    assert lignes[0].compte == "7011"
    assert lignes[0].montant_n == Decimal("1000000")
    assert lignes[0].montant_n1 == Decimal("900000")


def test_parser_etats_financiers_json():
    lignes = parser_etats_financiers((FIXTURES / "etats_financiers_demo.json").read_bytes())
    assert len(lignes) == 2
    assert lignes[0].compte == "7011"
    assert lignes[1].compte == "6011"


def test_controler_etats_financiers_vide():
    assert any("vides" in a for a in controler_etats_financiers([]))


def test_controler_etats_financiers_ok():
    lignes = [
        LigneEtatFinancier(compte="701", montant_n=Decimal("100")),
        LigneEtatFinancier.model_validate({"poste": "601", "montant_n": "40"}),
    ]
    assert controler_etats_financiers(lignes) == []


def test_etats_financiers_en_balance_sens():
    lignes = [
        LigneEtatFinancier(compte="701", libelle="Ventes", montant_n=Decimal("1000")),
        LigneEtatFinancier(compte="601", libelle="Achats", montant_n=Decimal("400")),
    ]
    balance = etats_financiers_en_balance(lignes)
    par_compte = {ligne.compte: ligne for ligne in balance}
    assert par_compte["701"].credit == Decimal("1000")
    assert par_compte["701"].debit == Decimal("0")
    assert par_compte["601"].debit == Decimal("400")
    assert par_compte["601"].credit == Decimal("0")


def test_parser_grand_livre_csv():
    ecritures = parser_grand_livre((FIXTURES / "grand_livre_demo.csv").read_bytes())
    assert len(ecritures) == 4
    assert ecritures[0].compte == "411"
    assert ecritures[0].debit == Decimal("1000")
    assert controler_grand_livre(ecritures) == []


def test_grand_livre_desequilibre():
    ecritures = [
        EcritureGrandLivre(compte="411", debit=Decimal("100"), credit=Decimal("0")),
        EcritureGrandLivre(compte="701", debit=Decimal("0"), credit=Decimal("50")),
    ]
    anomalies = controler_grand_livre(ecritures)
    assert any("desequilibre" in a for a in anomalies)


def test_agreger_grand_livre():
    ecritures = parser_grand_livre((FIXTURES / "grand_livre_demo.csv").read_bytes())
    balance = agreger_ecritures_en_balance(ecritures)
    par = {ligne.compte: ligne for ligne in balance}
    assert par["411"].debit == Decimal("1000")
    assert par["701"].credit == Decimal("1000")
    assert par["601"].debit == Decimal("400")
    assert par["401"].credit == Decimal("400")
    assert sum(ligne.debit for ligne in balance) == sum(ligne.credit for ligne in balance)


def test_parser_fec_pipe():
    ecritures = parser_fec((FIXTURES / "fec_demo.txt").read_bytes())
    assert len(ecritures) == 4
    assert ecritures[0].journal_code == "VE"
    assert ecritures[0].compte_num == "411"
    assert ecritures[0].debit == Decimal("1500.00")
    assert ecritures[0].ecriture_date.isoformat() == "2025-01-15"
    assert controler_fec(ecritures) == []


def test_parser_fec_tab():
    contenu = (
        "JournalCode\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tDebit\tCredit\n"
        "OD\t1\t20250301\t512\tBanque\t200\t0\n"
        "OD\t1\t20250301\t401\tFournisseurs\t0\t200\n"
    )
    ecritures = parser_fec(contenu)
    assert len(ecritures) == 2
    assert controler_fec(ecritures) == []


def test_parser_fec_entete_manquant():
    with pytest.raises(ErreurLectureBalance, match="entete FEC"):
        parser_fec("a|b|c\n1|2|3\n")


def test_agreger_fec():
    ecritures = parser_fec((FIXTURES / "fec_demo.txt").read_bytes())
    balance = agreger_ecritures_en_balance(ecritures)
    par = {ligne.compte: ligne for ligne in balance}
    assert par["411"].debit == Decimal("1500.00")
    assert par["701"].credit == Decimal("1500.00")
