"""Passage du resultat comptable au resultat fiscal — totaux deterministes.

Agregation des conclusions du moteur (reintegration / deduction).
Aucun taux ni seuil fiscal invente ici : seuls les montants deja calcules
par le moteur sont somes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

SENS_REINTEGRATION = "reintegration"
SENS_DEDUCTION = "deduction"
SENS_VALIDES = frozenset({SENS_REINTEGRATION, SENS_DEDUCTION})


@dataclass(frozen=True)
class LignePassage:
    regle_id: str
    montant: Decimal
    sens: str
    niveau_risque: str


@dataclass(frozen=True)
class Passage:
    """Tableau de passage : lignes + totaux.

    solde_net = total_reintegration - total_deduction
    (positif = reintegrations nettes).
    """

    lignes: tuple[LignePassage, ...]
    total_reintegration: Decimal
    total_deduction: Decimal
    solde_net: Decimal


def _dec(valeur: object) -> Decimal:
    if isinstance(valeur, Decimal):
        return valeur
    if valeur is None:
        raise ValueError("montant manquant")
    return Decimal(str(valeur))


def construire_passage(
    conclusions: Sequence[Mapping[str, object]],
) -> Passage:
    """Construit le passage a partir des conclusions declenchees.

    Chaque element attend : regle_id, montant, sens, niveau_risque.
    Les entrees sans montant ou sans sens valide sont ignorees (pas de zero silencieux
    sur un montant absurde — elles n entrent simplement pas dans le tableau).
    """
    lignes: list[LignePassage] = []
    total_reint = Decimal("0")
    total_ded = Decimal("0")

    for raw in conclusions:
        sens = raw.get("sens")
        montant_brut = raw.get("montant")
        if sens not in SENS_VALIDES or montant_brut is None:
            continue
        montant = _dec(montant_brut)
        ligne = LignePassage(
            regle_id=str(raw["regle_id"]),
            montant=montant,
            sens=str(sens),
            niveau_risque=str(raw.get("niveau_risque") or ""),
        )
        lignes.append(ligne)
        if ligne.sens == SENS_REINTEGRATION:
            total_reint += montant
        else:
            total_ded += montant

    return Passage(
        lignes=tuple(lignes),
        total_reintegration=total_reint,
        total_deduction=total_ded,
        solde_net=total_reint - total_ded,
    )
