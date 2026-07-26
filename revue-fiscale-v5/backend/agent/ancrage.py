"""Verification d ancrage — chaque citation doit etre sous-chaine d un fragment."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultatAncrage:
    ok: bool
    citations_valides: list[str]
    citations_rejetees: list[str]


def verifier_ancrage(
    citations: list[str],
    fragments: list[str],
) -> ResultatAncrage:
    """Verifie que chaque citation est une sous-chaine d au moins un fragment.

    Normalisation legere des espaces ; pas de fuzzy matching (trop permissif).
    """
    corpus = [_normaliser(f) for f in fragments if f]
    valides: list[str] = []
    rejetees: list[str] = []
    for cit in citations:
        if not cit or not cit.strip():
            rejetees.append(cit)
            continue
        cible = _normaliser(cit)
        if any(cible in frag for frag in corpus):
            valides.append(cit)
        else:
            rejetees.append(cit)
    return ResultatAncrage(
        ok=len(rejetees) == 0 and len(valides) > 0 if citations else True,
        citations_valides=valides,
        citations_rejetees=rejetees,
    )


def _normaliser(texte: str) -> str:
    return " ".join((texte or "").split()).casefold()
