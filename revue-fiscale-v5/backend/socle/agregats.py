"""Agregats normalises — definitions SYSCOHADA, jamais de seuil fiscal.

Voir docs/02-format-pivot.md. FRAIS_GENERAUX reste a figer (A CONFIRMER).
"""
from __future__ import annotations

from decimal import Decimal

# Prefixe d achats SYSCOHADA provisoires (A CONFIRMER) — exclus de FRAIS_GENERAUX.
_PREFIXES_ACHATS = ("601", "602", "603", "604", "605", "607", "608", "609")


def solde_naturel(compte: str, debit: Decimal, credit: Decimal) -> Decimal:
    """Solde en sens naturel : positif = montant present au compte.

    Classes 6 (charges) et 1-5 : debit - credit.
    Classe 7 (produits) : credit - debit.
    """
    if compte.startswith("7"):
        return credit - debit
    return debit - credit


def soldes_depuis_lignes(
    lignes: list[tuple[str, Decimal, Decimal]],
) -> dict[str, Decimal]:
    """Construit le dict compte -> solde naturel a partir de (compte, debit, credit)."""
    soldes: dict[str, Decimal] = {}
    for compte, debit, credit in lignes:
        soldes[compte] = solde_naturel(compte, debit, credit)
    return soldes


def _prefixe_dans(compte: str, debut: int, fin: int) -> bool:
    """Vrai si le compte commence par un prefixe numerique dans [debut, fin] inclus."""
    return any(compte.startswith(str(n)) for n in range(debut, fin + 1))


def _est_achat(compte: str) -> bool:
    return any(compte.startswith(p) for p in _PREFIXES_ACHATS)


def calculer_agregats(soldes: dict[str, Decimal]) -> dict[str, Decimal]:
    """Calcule les agregats normalises a partir des soldes nets.

    - CA : somme des comptes 701 a 707 (poste XB).
    - BENEFICE_COMPTABLE : poste XI (comptes 13*) si present, sinon produits 7 - charges 6.
    - RESULTAT_AVANT_IMPOT : BENEFICE_COMPTABLE + comptes 891* (impot RS) s ils existent.
    - FRAIS_GENERAUX : A CONFIRMER — hypothese provisoire : charges 60-65 hors achats
      (601-605, 607-609) et hors dotations (68*). Ne pas traiter comme verite fiscale.
    """
    ca = sum(
        (v for k, v in soldes.items() if _prefixe_dans(k, 701, 707)),
        Decimal(0),
    )

    postes_13 = {k: v for k, v in soldes.items() if k.startswith("13")}
    if postes_13:
        # Poste XI : solde credit habituel du resultat → naturel classe 1 = debit-credit,
        # donc on prend l oppose pour un benefice positif.
        benefice = -sum(postes_13.values(), Decimal(0))
    else:
        produits = sum((v for k, v in soldes.items() if k.startswith("7")), Decimal(0))
        charges = sum((v for k, v in soldes.items() if k.startswith("6")), Decimal(0))
        benefice = produits - charges

    impot_rs = sum((v for k, v in soldes.items() if k.startswith("891")), Decimal(0))
    resultat_avant_impot = benefice + impot_rs

    # A CONFIRMER — definition FRAIS_GENERAUX non figee (docs/02-format-pivot.md).
    frais = Decimal(0)
    for k, v in soldes.items():
        if not _prefixe_dans(k, 60, 65):
            continue
        if k.startswith("68"):
            continue
        if _est_achat(k):
            continue
        frais += v

    return {
        "CA": ca,
        "BENEFICE_COMPTABLE": benefice,
        "RESULTAT_AVANT_IMPOT": resultat_avant_impot,
        # Marqueur explicite : cette cle ne doit pas etre prise pour verite fiscale.
        "FRAIS_GENERAUX": frais,  # A CONFIRMER
    }
