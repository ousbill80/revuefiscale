"""Score de risque heuristique — NON REGLEMENTAIRE.

Ce score n est PAS un chiffrage CGI ni une sanction. Il agrège les
`niveau_risque` deja poses sur les conclusions (faible / moyen / eleve)
avec des poids arbitraires de presentation :

    faible = 1, moyen = 2, eleve = 3

Aucun montant de sanction n est invente ici. La table `sanction` n est
pas interrogee tant que les montants CGI ne sont pas figes en referentiel.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Heuristique de presentation — PAS une grille CGI.
POIDS_NIVEAU: dict[str, int] = {
    "faible": 1,
    "moyen": 2,
    "eleve": 3,
}

AVERTISSEMENT = (
    "Score heuristique de presentation — non reglementaire. "
    "Ne constitue ni une sanction CGI ni un chiffrage d amende."
)


@dataclass(frozen=True)
class ScoreRisque:
    score: int
    comptages: dict[str, int]
    avertissement: str = AVERTISSEMENT


def scorer_risques(
    conclusions: Sequence[Mapping[str, object]],
) -> ScoreRisque:
    """Calcule le score a partir des niveau_risque des conclusions.

    Les niveaux inconnus sont ignores (pas de poids invente).
    """
    comptages: Counter[str] = Counter()
    score = 0
    for raw in conclusions:
        niveau = str(raw.get("niveau_risque") or "").strip().lower()
        if niveau not in POIDS_NIVEAU:
            continue
        comptages[niveau] += 1
        score += POIDS_NIVEAU[niveau]
    return ScoreRisque(
        score=score,
        comptages=dict(comptages),
        avertissement=AVERTISSEMENT,
    )
