"""Tests unitaires — construction du passage comptable / fiscal."""
from decimal import Decimal

from backend.restitution.passage import construire_passage


def test_passage_totaux_reintegration_et_deduction():
    conclusions = [
        {
            "regle_id": "BIC-A",
            "montant": Decimal("100000"),
            "sens": "reintegration",
            "niveau_risque": "moyen",
        },
        {
            "regle_id": "BIC-B",
            "montant": Decimal("25000"),
            "sens": "deduction",
            "niveau_risque": "faible",
        },
        {
            "regle_id": "BIC-C",
            "montant": Decimal("50000"),
            "sens": "reintegration",
            "niveau_risque": "eleve",
        },
    ]
    p = construire_passage(conclusions)
    assert len(p.lignes) == 3
    assert p.total_reintegration == Decimal("150000")
    assert p.total_deduction == Decimal("25000")
    assert p.solde_net == Decimal("125000")


def test_passage_ignore_sans_montant_ou_sens():
    conclusions = [
        {"regle_id": "X", "montant": None, "sens": "reintegration", "niveau_risque": "faible"},
        {"regle_id": "Y", "montant": Decimal("10"), "sens": None, "niveau_risque": "faible"},
        {"regle_id": "Z", "montant": Decimal("10"), "sens": "autre", "niveau_risque": "faible"},
        {"regle_id": "OK", "montant": "20.50", "sens": "deduction", "niveau_risque": "moyen"},
    ]
    p = construire_passage(conclusions)
    assert len(p.lignes) == 1
    assert p.lignes[0].regle_id == "OK"
    assert p.lignes[0].montant == Decimal("20.50")
    assert p.total_deduction == Decimal("20.50")
    assert p.total_reintegration == Decimal("0")
    assert p.solde_net == Decimal("-20.50")


def test_passage_vide():
    p = construire_passage([])
    assert p.lignes == ()
    assert p.total_reintegration == Decimal("0")
    assert p.total_deduction == Decimal("0")
    assert p.solde_net == Decimal("0")
