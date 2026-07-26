"""Tests import Excel + filtre profil."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from backend.moteur.selection import selectionner_regles
from backend.profil.service import ErreurProfil, profil_compatible_regle, valider_profil
from backend.referentiel.depot import RegleChargee
from backend.socle.lecteurs.balance_xlsx import parser_balance_xlsx


def test_valider_profil_enrichi():
    p = valider_profil(
        {
            "regime": "reel",
            "forme_juridique": "SA",
            "secteur": "services",
            "type_entite": "sa",
            "cross_border": True,
        }
    )
    assert p["secteur"] == "services"
    assert p["cross_border"] is True
    with pytest.raises(ErreurProfil):
        valider_profil({"regime": "reel"})


def test_profil_filtre_obnl():
    assert profil_compatible_regle(
        ["Organismes non lucratifs"],
        {"regime": "reel", "forme_juridique": "asso", "type_entite": "obnl"},
    )
    assert not profil_compatible_regle(
        ["Organismes non lucratifs"],
        {"regime": "reel", "forme_juridique": "SA"},
    )


def _regle(ident: str, comptes: list[str], profils: list[str]) -> RegleChargee:
    return RegleChargee(
        regle_version_id=1,
        regle_id=ident,
        impot="BIC",
        libelle=ident,
        comptes_declencheurs=comptes,
        nature="sans_objet",
        condition_declenchement="solde(701) > 0",
        expression_resultat="0",
        niveau_risque="faible",
        formule_plafonnement=None,
        questions=[],
        a_confirmer=[],
        profils_applicables=profils,
    )


def test_selection_filtre_profil():
    regles = [
        _regle("A", ["701"], ["Entreprises au regime reel"]),
        _regle("B", ["701"], ["Organismes non lucratifs"]),
    ]
    soldes = {"701": Decimal("1")}
    sel = selectionner_regles(
        regles, soldes, profil={"regime": "reel", "forme_juridique": "SA"}
    )
    assert [r.regle_id for r in sel] == ["A"]


def test_parser_balance_xlsx(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["compte", "libelle", "debit", "credit"])
    ws.append(["701", "Ventes", 0, 1000])
    ws.append(["401", "Fournisseurs", 1000, 0])
    chemin = tmp_path / "balance.xlsx"
    wb.save(chemin)
    lignes = parser_balance_xlsx(chemin.read_bytes())
    assert len(lignes) == 2
    assert lignes[0].compte == "701"
    assert lignes[0].credit == Decimal("1000")
