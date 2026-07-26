"""Calcul d une regle — evalue condition puis resultat via l evaluateur."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.referentiel.depot import RegleChargee
from backend.referentiel.expressions import Contexte, ErreurEvaluation, evaluer

STATUT_CONFORME = "conforme"
STATUT_ANOMALIE = "anomalie"
STATUT_SOUS_SEUIL = "sous_seuil"
STATUT_NON_VERIFIABLE = "non_verifiable"
STATUT_HORS_PERIMETRE = "hors_perimetre"

STATUTS_CONCLUSION = frozenset(
    {
        STATUT_CONFORME,
        STATUT_ANOMALIE,
        STATUT_SOUS_SEUIL,
        STATUT_NON_VERIFIABLE,
        STATUT_HORS_PERIMETRE,
    }
)


@dataclass(frozen=True)
class ConclusionCalculee:
    regle_version_id: int
    regle_id: str
    declenchee: bool
    montant: Decimal | None
    sens: str | None  # reintegration | deduction | None
    niveau_risque: str
    detail: str | None = None
    inevaluable: bool = False


def statut_brouillon_conclusion(
    c: ConclusionCalculee,
    seuil: Decimal | None,
) -> str | None:
    """Statut brouillon déterministe — jamais un seuil CGI inventé.

    - inevaluable → non_verifiable
    - déclenchée + |montant| < seuil mission (si posé) → sous_seuil
    - déclenchée sinon → anomalie
    - non déclenchée et évaluable → None (pas d'INSERT)
    """
    if c.inevaluable:
        return STATUT_NON_VERIFIABLE
    if not c.declenchee:
        return None
    if (
        seuil is not None
        and c.montant is not None
        and abs(c.montant) < seuil
    ):
        return STATUT_SOUS_SEUIL
    return STATUT_ANOMALIE


def calculer_regle(
    regle: RegleChargee,
    ctx: Contexte,
    *,
    sens_par_defaut: str = "reintegration",
) -> ConclusionCalculee:
    """Pour une regle : evalue condition ; si vraie, evalue resultat."""
    try:
        condition = evaluer(regle.condition_declenchement, ctx)
    except ErreurEvaluation as e:
        return ConclusionCalculee(
            regle_version_id=regle.regle_version_id,
            regle_id=regle.regle_id,
            declenchee=False,
            montant=None,
            sens=None,
            niveau_risque=regle.niveau_risque,
            detail=f"condition inevaluable : {e}",
            inevaluable=True,
        )

    if not isinstance(condition, bool):
        return ConclusionCalculee(
            regle_version_id=regle.regle_version_id,
            regle_id=regle.regle_id,
            declenchee=False,
            montant=None,
            sens=None,
            niveau_risque=regle.niveau_risque,
            detail="condition non booleenne",
            inevaluable=True,
        )

    if not condition:
        return ConclusionCalculee(
            regle_version_id=regle.regle_version_id,
            regle_id=regle.regle_id,
            declenchee=False,
            montant=None,
            sens=None,
            niveau_risque=regle.niveau_risque,
        )

    try:
        resultat = evaluer(regle.expression_resultat, ctx)
    except ErreurEvaluation as e:
        return ConclusionCalculee(
            regle_version_id=regle.regle_version_id,
            regle_id=regle.regle_id,
            declenchee=True,
            montant=None,
            sens=None,
            niveau_risque=regle.niveau_risque,
            detail=f"resultat inevaluable : {e}",
            inevaluable=True,
        )

    if isinstance(resultat, bool):
        montant = None
    else:
        montant = resultat if isinstance(resultat, Decimal) else Decimal(str(resultat))

    return ConclusionCalculee(
        regle_version_id=regle.regle_version_id,
        regle_id=regle.regle_id,
        declenchee=True,
        montant=montant,
        sens=sens_par_defaut if montant is not None else None,
        niveau_risque=regle.niveau_risque,
    )
