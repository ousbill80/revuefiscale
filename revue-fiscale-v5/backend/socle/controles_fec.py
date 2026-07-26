"""Contrôles de vraisemblance d'un FEC — informationnels, jamais bloquants.

Fonction pure (aucun accès base) : restitue à l'expert des signaux de
fiabilité de la source avant tout calcul fiscal. Chaque contrôle porte un
statut ok/alerte, un compteur et un échantillon (max 5 occurrences).

Convention « ligne » : index 1-based de l'écriture dans le fichier parsé
(les lignes vides étant ignorées par le lecteur FEC).
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

from backend.socle.modeles import EcritureFec

_MAX_ECHANTILLON = 5

# Classes SYSCOHADA admises pour la comptabilité générale (1 à 7).
# 0 = inexistante, 8 = autres charges/produits HAO (comptes 8 existent en
# SYSCOHADA mais hors plan minimal ici), 9 = comptabilité analytique.
_CLASSES_HORS_PLAN = ("0", "8", "9")

_RE_SUFFIXE_NUM = re.compile(r"(\d+)\s*$")


def _controle(
    code: str,
    libelle: str,
    compteur: int,
    echantillon: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "code": code,
        "libelle": libelle,
        "statut": "alerte" if compteur > 0 else "ok",
        "compteur": compteur,
        "echantillon": echantillon[:_MAX_ECHANTILLON],
    }


def _ecritures_non_equilibrees(
    lignes: list[EcritureFec],
) -> dict[str, Any]:
    """Somme débit ≠ somme crédit par écriture (JournalCode + EcritureNum)."""
    totaux: dict[tuple[str, str], list] = {}
    for no, e in enumerate(lignes, start=1):
        cle = (e.journal_code, e.ecriture_num)
        if cle not in totaux:
            totaux[cle] = [no, Decimal("0"), Decimal("0")]
        totaux[cle][1] += e.debit
        totaux[cle][2] += e.credit
    echantillon: list[dict[str, Any]] = []
    compteur = 0
    for (journal, num), (no, deb, cre) in totaux.items():
        if deb != cre:
            compteur += 1
            if len(echantillon) < _MAX_ECHANTILLON:
                echantillon.append(
                    {
                        "ligne": no,
                        "valeur": (
                            f"{journal}/{num} : débit {deb} ≠ crédit {cre} "
                            f"(écart {deb - cre})"
                        ),
                    }
                )
    return _controle(
        "ecritures_non_equilibrees",
        "Écritures non équilibrées (débit ≠ crédit par EcritureNum)",
        compteur,
        echantillon,
    )


def _dates_hors_exercice(
    lignes: list[EcritureFec], exercice: int
) -> dict[str, Any]:
    echantillon: list[dict[str, Any]] = []
    compteur = 0
    for no, e in enumerate(lignes, start=1):
        if e.ecriture_date.year != exercice:
            compteur += 1
            if len(echantillon) < _MAX_ECHANTILLON:
                echantillon.append(
                    {"ligne": no, "valeur": e.ecriture_date.isoformat()}
                )
    return _controle(
        "dates_hors_exercice",
        f"Dates hors exercice contrôlé ({exercice})",
        compteur,
        echantillon,
    )


def _doublons_stricts(lignes: list[EcritureFec]) -> dict[str, Any]:
    """Même journal + numéro + compte + date + montants → doublon strict."""
    vus: set[tuple] = set()
    echantillon: list[dict[str, Any]] = []
    compteur = 0
    for no, e in enumerate(lignes, start=1):
        cle = (
            e.journal_code,
            e.ecriture_num,
            e.compte_num,
            e.ecriture_date,
            e.debit,
            e.credit,
        )
        if cle in vus:
            compteur += 1
            if len(echantillon) < _MAX_ECHANTILLON:
                echantillon.append(
                    {
                        "ligne": no,
                        "valeur": (
                            f"{e.journal_code}/{e.ecriture_num} "
                            f"compte {e.compte_num} du "
                            f"{e.ecriture_date.isoformat()} "
                            f"(D {e.debit} / C {e.credit})"
                        ),
                    }
                )
        else:
            vus.add(cle)
    return _controle(
        "doublons_stricts",
        "Doublons stricts d'écritures (journal, numéro, compte, date, montants)",
        compteur,
        echantillon,
    )


def _comptes_hors_plan(lignes: list[EcritureFec]) -> dict[str, Any]:
    """Compte non numérique ou de classe 0/8/9 — hors plan SYSCOHADA général."""
    echantillon: list[dict[str, Any]] = []
    comptes_signales: set[str] = set()
    compteur = 0
    for no, e in enumerate(lignes, start=1):
        compte = e.compte_num.strip()
        hors_plan = (not compte.isdigit()) or compte.startswith(
            _CLASSES_HORS_PLAN
        )
        if not hors_plan:
            continue
        compteur += 1
        if compte not in comptes_signales and len(echantillon) < _MAX_ECHANTILLON:
            comptes_signales.add(compte)
            echantillon.append({"ligne": no, "valeur": compte})
    return _controle(
        "comptes_hors_plan",
        "Comptes hors plan SYSCOHADA (classe 0/8/9 ou non numérique)",
        compteur,
        echantillon,
    )


def _trous_sequence(lignes: list[EcritureFec]) -> dict[str, Any]:
    """Trous de numérotation d'EcritureNum par journal — informationnel."""
    numeros: dict[str, dict[int, int]] = defaultdict(dict)  # journal → num → ligne
    for no, e in enumerate(lignes, start=1):
        m = _RE_SUFFIXE_NUM.search(e.ecriture_num)
        if not m:
            continue
        n = int(m.group(1))
        numeros[e.journal_code].setdefault(n, no)
    echantillon: list[dict[str, Any]] = []
    compteur = 0
    for journal in sorted(numeros):
        suite = sorted(numeros[journal])
        for precedent, suivant in zip(suite, suite[1:], strict=False):
            if suivant - precedent > 1:
                compteur += 1
                if len(echantillon) < _MAX_ECHANTILLON:
                    echantillon.append(
                        {
                            "ligne": numeros[journal][suivant],
                            "valeur": (
                                f"journal {journal} : saut de "
                                f"{precedent} à {suivant}"
                            ),
                        }
                    )
    return _controle(
        "trous_sequence",
        "Trous de séquence EcritureNum par journal (informationnel)",
        compteur,
        echantillon,
    )


def controles_vraisemblance_fec(
    lignes: list[EcritureFec], exercice: int
) -> list[dict[str, Any]]:
    """Contrôles de vraisemblance d'une source FEC — jamais bloquants.

    Retourne une liste de contrôles :
    [{code, libelle, statut ok|alerte, compteur, echantillon[{ligne, valeur}]}]
    """
    return [
        _ecritures_non_equilibrees(lignes),
        _dates_hors_exercice(lignes, exercice),
        _doublons_stricts(lignes),
        _comptes_hors_plan(lignes),
        _trous_sequence(lignes),
    ]
