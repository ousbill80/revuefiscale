"""Controles bloquants sur une balance avant fiabilisation."""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from backend.socle.modeles import EcritureFec, EcritureGrandLivre, LigneBalance, LigneEtatFinancier


class _LigneDebitCredit(Protocol):
    debit: Decimal
    credit: Decimal


def controler_balance(lignes: list[LigneBalance]) -> list[str]:
    """Retourne la liste des anomalies. Vide = balance acceptable.

    - Equilibre : somme debit == somme credit
    - Completude : aucun compte vide ; au moins une ligne
    """
    anomalies: list[str] = []

    if not lignes:
        anomalies.append("balance vide : aucune ligne")
        return anomalies

    total_debit = Decimal(0)
    total_credit = Decimal(0)
    vus: set[str] = set()

    for i, ligne in enumerate(lignes, start=1):
        compte = (ligne.compte or "").strip()
        if not compte:
            anomalies.append(f"ligne {i} : compte vide")
            continue
        if compte in vus:
            anomalies.append(f"compte en double : {compte}")
        vus.add(compte)
        total_debit += ligne.debit
        total_credit += ligne.credit

    if total_debit != total_credit:
        anomalies.append(
            f"balance desequilibree : debit={total_debit} credit={total_credit} "
            f"ecart={total_debit - total_credit}"
        )

    return anomalies


def _equilibre_mouvements(
    lignes: list[_LigneDebitCredit], *, libelle: str
) -> list[str]:
    anomalies: list[str] = []
    if not lignes:
        anomalies.append(f"{libelle} vide : aucune ecriture")
        return anomalies
    total_debit = sum((ligne.debit for ligne in lignes), Decimal(0))
    total_credit = sum((ligne.credit for ligne in lignes), Decimal(0))
    if total_debit != total_credit:
        anomalies.append(
            f"{libelle} desequilibre : debit={total_debit} credit={total_credit} "
            f"ecart={total_debit - total_credit}"
        )
    return anomalies


def controler_grand_livre(ecritures: list[EcritureGrandLivre]) -> list[str]:
    """Equilibre global debit=credit + comptes non vides."""
    anomalies: list[str] = []
    if not ecritures:
        return ["grand livre vide : aucune ecriture"]
    for i, ecriture in enumerate(ecritures, start=1):
        if not (ecriture.compte or "").strip():
            anomalies.append(f"ligne {i} : compte vide")
    anomalies.extend(_equilibre_mouvements(ecritures, libelle="grand livre"))
    return anomalies


def controler_fec(ecritures: list[EcritureFec]) -> list[str]:
    """Equilibre global debit=credit + CompteNum non vides."""
    anomalies: list[str] = []
    if not ecritures:
        return ["fec vide : aucune ecriture"]
    for i, ecriture in enumerate(ecritures, start=1):
        if not (ecriture.compte_num or "").strip():
            anomalies.append(f"ligne {i} : CompteNum vide")
    anomalies.extend(_equilibre_mouvements(ecritures, libelle="fec"))
    return anomalies


def controler_etats_financiers(lignes: list[LigneEtatFinancier]) -> list[str]:
    """Coherence basique : au moins un poste, comptes/postes non vides."""
    anomalies: list[str] = []
    if not lignes:
        anomalies.append("etats financiers vides : aucun poste")
        return anomalies
    for i, ligne in enumerate(lignes, start=1):
        if not (ligne.compte or "").strip():
            anomalies.append(f"ligne {i} : poste/compte vide")
    return anomalies
