"""Paramètres et calcul de rentabilité d'une mission.

POURQUOI : le cabinet convient d'HONORAIRES forfaitaires par mission et
applique un TAUX HORAIRE standard interne pour valoriser le temps passé.
La rentabilité se pilote ainsi : coût estimé = heures saisies × taux
horaire ; marge estimée = honoraires − coût ; taux de marge =
marge / honoraires × 100. Les deux paramètres sont portés par la table
``mission`` (colonnes nullables — migration 040) : tant qu'ils ne sont
pas renseignés, les indicateurs correspondants restent ``null`` sans
bloquer la saisie des temps.

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. Le calcul est une fonction pure
(:func:`calculer_rentabilite`) en :class:`~decimal.Decimal` — jamais de
float — testable sans base.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant


def _fmt(d: Decimal) -> str:
    """Décimal → texte stable, sans notation scientifique ni zéros finaux."""
    return format(d.normalize(), "f")


class ErreurRentabilite(Exception):
    """Paramètre de rentabilité invalide (négatif, non numérique) — 422."""


class ErreurRentabiliteIntrouvable(ErreurRentabilite):
    """Mission hors périmètre du tenant — 404."""


def _valider_montant(valeur: Any, libelle: str) -> Decimal | None:
    """Montant >= 0, deux décimales max — ``None`` conservé (effacement)."""
    if valeur is None:
        return None
    try:
        m = Decimal(str(valeur))
    except (InvalidOperation, ValueError) as e:
        raise ErreurRentabilite(f"{libelle} invalide « {valeur} »") from e
    if not m.is_finite() or m < 0:
        raise ErreurRentabilite(
            f"{libelle} invalide « {valeur} » — attendu : montant >= 0"
        )
    if -m.as_tuple().exponent > 2:
        raise ErreurRentabilite(
            f"{libelle} invalide « {valeur} » — deux décimales maximum"
        )
    return m


def calculer_rentabilite(
    honoraires: Any,
    taux_horaire: Any,
    total_heures: Any,
) -> dict[str, Any]:
    """PUR — indicateurs de rentabilité d'une mission (Decimal, pas float).

    - ``cout_estime`` : heures × taux horaire — ``null`` sans taux ;
    - ``marge_estimee`` : honoraires − coût — ``null`` si l'un des deux
      paramètres manque (on ne fait pas croire à une marge sans base) ;
    - ``taux_marge_pct`` : marge / honoraires × 100, arrondi commercial à
      une décimale — ``null`` si honoraires absents ou nuls (division).
    """
    h = _valider_montant(honoraires, "honoraires")
    t = _valider_montant(taux_horaire, "taux horaire")
    heures = Decimal(str(total_heures))

    cout: Decimal | None = None if t is None else heures * t
    marge: Decimal | None = (
        None if (h is None or cout is None) else h - cout
    )
    taux_pct: Decimal | None = None
    if marge is not None and h is not None and h > 0:
        taux_pct = (marge / h * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    return {
        "honoraires": None if h is None else _fmt(h),
        "taux_horaire": None if t is None else _fmt(t),
        "total_heures": _fmt(heures),
        "cout_estime": None if cout is None else _fmt(cout),
        "marge_estimee": None if marge is None else _fmt(marge),
        "taux_marge_pct": None if taux_pct is None else format(taux_pct, "f"),
    }


def definir_parametres(
    session: Session,
    tenant_id: int,
    mission_id: int,
    honoraires: Any = None,
    taux_horaire: Any = None,
) -> dict[str, Any]:
    """Enregistre les paramètres de rentabilité de la mission.

    ``None`` efface le paramètre (retour à « non convenu »). Valeur
    négative ou non numérique → :class:`ErreurRentabilite` (422).
    Mission hors périmètre du tenant (RLS) →
    :class:`ErreurRentabiliteIntrouvable` (404). Retourne les paramètres
    enregistrés, sérialisés.
    """
    h = _valider_montant(honoraires, "honoraires")
    t = _valider_montant(taux_horaire, "taux horaire")
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE mission SET honoraires = :h, taux_horaire = :t "
                "WHERE id = :m RETURNING honoraires, taux_horaire"
            ),
            {"h": h, "t": t, "m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurRentabiliteIntrouvable(
            f"mission {mission_id} introuvable"
        )
    return {
        "honoraires": (
            None if row["honoraires"] is None
            else _fmt(Decimal(str(row["honoraires"])))
        ),
        "taux_horaire": (
            None if row["taux_horaire"] is None
            else _fmt(Decimal(str(row["taux_horaire"])))
        ),
    }


def rentabilite_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rentabilité de la mission : paramètres, coût, marge, taux de marge.

    Lit sous RLS les paramètres de la mission et le cumul d'heures
    saisies (``temps_mission``), puis délègue le calcul à la fonction
    pure :func:`calculer_rentabilite`. Mission hors périmètre du tenant
    → :class:`ErreurRentabiliteIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.honoraires, m.taux_horaire, "
                "COALESCE(SUM(t.heures), 0) AS total_heures "
                "FROM mission m "
                "LEFT JOIN temps_mission t ON t.mission_id = m.id "
                "WHERE m.id = :m GROUP BY m.honoraires, m.taux_horaire"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurRentabiliteIntrouvable(
            f"mission {mission_id} introuvable"
        )
    return calculer_rentabilite(
        honoraires=row["honoraires"],
        taux_horaire=row["taux_horaire"],
        total_heures=row["total_heures"],
    )
