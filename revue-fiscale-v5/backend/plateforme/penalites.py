"""Chiffrage indicatif des pénalités et intérêts de retard — déterministe.

Barème INDICATIF inspiré du CGI sénégalais (Livre IV — procédures) :
chaque montant produit ici est un ordre de grandeur destiné au comité,
clairement libellé « chiffrage indicatif, à valider par l'associé ».
AUCUN appel LLM — fonctions pures, testables.

Constantes du barème (à ajuster si le barème légal évolue) :

- ``INTERET_RETARD_TAUX_MENSUEL`` : intérêt de retard de 0,5 % par mois
  de retard, décompté depuis la date d'exigibilité estimée.
- ``INTERET_RETARD_PLAFOND`` : l'intérêt de retard cumulé est plafonné
  à 50 % du droit simple.
- ``PENALITE_ASSIETTE_BONNE_FOI`` : pénalité d'assiette de 25 % du
  droit simple (insuffisance de déclaration, bonne foi présumée).
- ``PENALITE_ASSIETTE_MAUVAISE_FOI`` : pénalité portée à 50 % en cas
  de mauvaise foi présumée.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

INTERET_RETARD_TAUX_MENSUEL: Final[Decimal] = Decimal("0.005")
INTERET_RETARD_PLAFOND: Final[Decimal] = Decimal("0.50")
PENALITE_ASSIETTE_BONNE_FOI: Final[Decimal] = Decimal("0.25")
PENALITE_ASSIETTE_MAUVAISE_FOI: Final[Decimal] = Decimal("0.50")

CARACTERES: Final[frozenset[str]] = frozenset({"bonne_foi", "mauvaise_foi"})

MENTION_INDICATIVE: Final[str] = (
    "Chiffrage indicatif, à valider par l'associé — barème inspiré du "
    "CGI sénégalais."
)


class ErreurChiffragePenalites(Exception):
    """Entrées invalides pour le chiffrage des pénalités."""


def _arrondi_fcfa(montant: Decimal) -> Decimal:
    """Arrondi au franc CFA entier (demi vers le haut)."""
    return montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def mois_de_retard(
    date_exigibilite: date, aujourd_hui: date | None = None
) -> int:
    """Mois entiers écoulés depuis la date d'exigibilité (jamais négatif)."""
    auj = aujourd_hui or date.today()
    if auj <= date_exigibilite:
        return 0
    mois = (auj.year - date_exigibilite.year) * 12 + (
        auj.month - date_exigibilite.month
    )
    if auj.day < date_exigibilite.day:
        mois -= 1
    return max(mois, 0)


def chiffrer_penalites(
    droit_simple: Decimal | int | float | str,
    *,
    mois_retard: int | None = None,
    date_exigibilite: date | None = None,
    caractere: str = "bonne_foi",
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Chiffrage indicatif {droit_simple, interet_retard, penalite_assiette,
    total_estime, hypotheses}.

    ``mois_retard`` prime sur ``date_exigibilite`` ; l'un des deux est
    obligatoire. ``caractere`` : bonne_foi (défaut) ou mauvaise_foi.
    Fonction pure — aucun accès base, aucun appel LLM.
    """
    droit = Decimal(str(droit_simple))
    if droit < 0:
        raise ErreurChiffragePenalites("droit_simple négatif interdit")
    car = (caractere or "bonne_foi").strip().lower()
    if car not in CARACTERES:
        raise ErreurChiffragePenalites(
            f"caractere invalide {caractere!r} — attendu : "
            + ", ".join(sorted(CARACTERES))
        )
    if mois_retard is None:
        if date_exigibilite is None:
            raise ErreurChiffragePenalites(
                "mois_retard ou date_exigibilite obligatoire"
            )
        mois = mois_de_retard(date_exigibilite, aujourd_hui)
    else:
        mois = int(mois_retard)
        if mois < 0:
            raise ErreurChiffragePenalites("mois_retard négatif interdit")

    taux_interet_cumule = min(
        INTERET_RETARD_TAUX_MENSUEL * mois, INTERET_RETARD_PLAFOND
    )
    interet = _arrondi_fcfa(droit * taux_interet_cumule)
    plafonne = INTERET_RETARD_TAUX_MENSUEL * mois > INTERET_RETARD_PLAFOND

    taux_assiette = (
        PENALITE_ASSIETTE_MAUVAISE_FOI
        if car == "mauvaise_foi"
        else PENALITE_ASSIETTE_BONNE_FOI
    )
    penalite = _arrondi_fcfa(droit * taux_assiette)
    droit = _arrondi_fcfa(droit)

    hypotheses = [
        MENTION_INDICATIVE,
        (
            f"Intérêt de retard : 0,5 %/mois × {mois} mois de retard estimés"
            + (
                ", plafonné à 50 % du droit simple."
                if plafonne
                else " (plafond 50 % non atteint)."
            )
        ),
        (
            "Pénalité d'assiette : 50 % du droit simple "
            "(mauvaise foi présumée)."
            if car == "mauvaise_foi"
            else "Pénalité d'assiette : 25 % du droit simple "
            "(insuffisance de déclaration, bonne foi présumée)."
        ),
    ]
    if date_exigibilite is not None and mois_retard is None:
        hypotheses.append(
            "Date d'exigibilité estimée : "
            + date_exigibilite.strftime("%d/%m/%Y")
            + "."
        )

    return {
        "droit_simple": droit,
        "interet_retard": interet,
        "penalite_assiette": penalite,
        "total_estime": droit + interet + penalite,
        "mois_retard": mois,
        "caractere": car,
        "hypotheses": hypotheses,
    }


def date_exigibilite_estimee(exercice_origine: int) -> date:
    """Fin de l'exercice concerné (31/12/N) — hypothèse conservatrice."""
    return date(int(exercice_origine), 12, 31)


def chiffrer_risque(
    risque: dict[str, Any], aujourd_hui: date | None = None
) -> dict[str, str | int | list[str]] | None:
    """Chiffrage indicatif d'un risque du registre (montants en str, JSON-safe).

    ``None`` si le risque n'est pas chiffré (montant_estime absent) ou si
    l'exercice d'origine est inexploitable. Retard estimé depuis la fin de
    l'exercice d'origine jusqu'à aujourd'hui, bonne foi présumée.
    """
    montant = risque.get("montant_estime")
    if montant is None or montant == "":
        return None
    try:
        exercice = int(risque.get("exercice_origine") or 0)
    except (TypeError, ValueError):
        return None
    if exercice < 1900 or exercice > 2200:
        return None
    chiffrage = chiffrer_penalites(
        Decimal(str(montant)),
        date_exigibilite=date_exigibilite_estimee(exercice),
        caractere="bonne_foi",
        aujourd_hui=aujourd_hui,
    )
    return {
        "droit_simple": str(chiffrage["droit_simple"]),
        "interet_retard": str(chiffrage["interet_retard"]),
        "penalite_assiette": str(chiffrage["penalite_assiette"]),
        "total_estime": str(chiffrage["total_estime"]),
        "mois_retard": int(chiffrage["mois_retard"]),
        "caractere": str(chiffrage["caractere"]),
        "hypotheses": list(chiffrage["hypotheses"]),
    }
