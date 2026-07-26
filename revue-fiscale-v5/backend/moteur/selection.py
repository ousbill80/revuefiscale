"""Selection des regles applicables selon comptes et profil."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.profil.service import profil_compatible_regle
from backend.referentiel.depot import RegleChargee


def selectionner_regles(
    regles: list[RegleChargee],
    soldes: Mapping[str, object],
    profil: Mapping[str, object] | None = None,
    perimetre_impots: Sequence[str] | None = None,
) -> list[RegleChargee]:
    """Conserve les regles dont au moins un compte declencheur matche un solde.

    Un prefixe declencheur matche s il egal un compte ou si un compte commence
    par ce prefixe (ex. '658' matche '6582').
    Filtre ensuite sur profils_applicables si un profil est fourni.
    Si ``perimetre_impots`` est une liste non vide, ne retient que les regles
    dont ``regle.impot`` appartient au perimetre (deterministe).
    ``None`` = tous les impots (retrocompatibilite).
    """
    comptes = list(soldes.keys())
    perimetre: frozenset[str] | None = None
    if perimetre_impots is not None:
        perimetre = frozenset(str(c).strip().upper() for c in perimetre_impots if str(c).strip())

    selection: list[RegleChargee] = []
    for regle in regles:
        if perimetre is not None and regle.impot.upper() not in perimetre:
            continue
        if not profil_compatible_regle(regle.profils_applicables, profil):
            continue
        declencheurs = regle.comptes_declencheurs
        if not declencheurs:
            selection.append(regle)
            continue
        for prefixe in declencheurs:
            if any(c == prefixe or c.startswith(prefixe) for c in comptes):
                selection.append(regle)
                break
    return selection
