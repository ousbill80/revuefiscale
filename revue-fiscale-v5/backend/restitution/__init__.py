"""Couche restitution — passage, risques, rapport."""
from backend.restitution.passage import Passage, construire_passage
from backend.restitution.risques import ScoreRisque, scorer_risques
from backend.restitution.service import Restitution, produire_restitution

__all__ = [
    "Passage",
    "Restitution",
    "ScoreRisque",
    "construire_passage",
    "produire_restitution",
    "scorer_risques",
]
