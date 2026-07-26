"""Jeu de donnees Lot 1 — balance equilibree pour les six regles types."""
from __future__ import annotations

from decimal import Decimal

from backend.socle.modeles import LigneBalance


def ligne(compte: str, debit: str = "0", credit: str = "0", libelle: str = "") -> LigneBalance:
    return LigneBalance(
        compte=compte,
        libelle=libelle or None,
        debit=Decimal(debit),
        credit=Decimal(credit),
    )


def balance_lot1_types() -> list[LigneBalance]:
    """Declenche les 6 regles types. CA=4 Md, resultat poste 13=200 M."""
    lignes = [
        ligne("701", credit="4000000000", libelle="Ventes"),
        ligne("13", credit="200000000", libelle="Resultat"),
        ligne("6582", debit="150000000", libelle="Dons"),
        ligne("691", debit="12000000", libelle="Provisions"),
        ligne("671", debit="80000000", libelle="Interets CCA"),
        ligne("674", debit="20000000", libelle="Interets lies"),
        ligne("681", debit="5000000", libelle="Dot. amort."),
        ligne("6581", debit="10000000", libelle="Indemn. admin"),
        ligne("622", debit="7500000", libelle="Honoraires"),
    ]
    total_d = sum((x.debit for x in lignes), Decimal(0))
    total_c = sum((x.credit for x in lignes), Decimal(0))
    ecart = total_c - total_d
    lignes.append(ligne("411", debit=str(ecart), libelle="Clients"))
    return lignes


def reponses_lot1_types() -> dict[str, object]:
    return {
        "q_perte_precisee": False,
        "q_releve": True,
        "q_duree_ok": False,
        "q_duree_comptable": Decimal("1"),
        "q_nb_admin": Decimal("2"),
        "q_excede": True,
        "q_seuil_depasse": True,
        "q_declaration": False,
        "q_montant": Decimal("7500000"),
    }
