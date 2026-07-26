"""Paliers d abonnement — quotas et tarifs provisoires.

À CONFIRMER avec 2AàZ (docs/00-fondations-pv.md) : les volumes et montants
ci-dessous sont des bornes techniques pour faire tourner le provisionnement
et la facturation commerciale, PAS une grille tarifaire officielle.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final

# missions_incluses par mois civil — À CONFIRMER
MISSIONS_PAR_PALIER: Final[dict[str, int]] = {
    "essentiel": 5,
    "standard": 20,
    "premium": 100,
    "souverain": 10_000,
}

# Montants commerciaux mensuels (XOF) — À CONFIRMER commercialement.
# Ces chiffres n'entrent JAMAIS dans un calcul fiscal moteur.
PRIX_MENSUEL_XOF: Final[dict[str, Decimal]] = {
    "essentiel": Decimal("150000"),
    "standard": Decimal("350000"),
    "premium": Decimal("750000"),
    "souverain": Decimal("1500000"),
}

PALIERS_VALIDES: Final[frozenset[str]] = frozenset(MISSIONS_PAR_PALIER)
TYPES_TENANT: Final[frozenset[str]] = frozenset({"cabinet", "entreprise"})

# Drapeau explicite pour l'UI billing — jamais présenter ces montants comme officiels.
TARIFS_A_CONFIRMER: Final[bool] = True
TARIFS_AVERTISSEMENT: Final[str] = (
    "Tarifs À CONFIRMER — bornes techniques provisoires pour le moteur de "
    "quotas / facturation. Pas une grille commerciale officielle 2AàZ."
)


def missions_incluses(palier: str) -> int:
    if palier not in MISSIONS_PAR_PALIER:
        raise ValueError(f"palier inconnu : {palier!r}")
    return MISSIONS_PAR_PALIER[palier]


def prix_mensuel_xof(palier: str) -> Decimal:
    if palier not in PRIX_MENSUEL_XOF:
        raise ValueError(f"palier inconnu : {palier!r}")
    return PRIX_MENSUEL_XOF[palier]
