"""Provision pour risques fiscaux — proposition déterministe (SYSCOHADA).

Règle d'expertise comptable : les risques fiscaux OUVERTS (non résolus,
non acceptés, non prescrits) à probabilité « probable » donnent lieu à
une PROVISION POUR RISQUES, pénalités et intérêts de retard inclus
(chiffrage indicatif de ``backend.plateforme.penalites``). Les risques
ouverts seulement « possibles » ne sont pas provisionnés mais mentionnés
en annexe (passifs éventuels).

Écriture proposée (SYSCOHADA, à adapter au plan de comptes de l'entité) :
débit 6911 « Dotations aux provisions d'exploitation » /
crédit 1918 « Autres provisions pour risques ».

AUCUN appel LLM — fonctions pures + lecture base sous RLS.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.penalites import MENTION_INDICATIVE
from backend.plateforme.risques import STATUTS_NON_CLOS, lister_risques

COMPTE_DOTATION: Final[str] = "6911"
INTITULE_DOTATION: Final[str] = "Dotations aux provisions d'exploitation"
COMPTE_PROVISION: Final[str] = "1918"
INTITULE_PROVISION: Final[str] = "Autres provisions pour risques"

PROBABILITE_PROVISIONNABLE: Final[str] = "probable"
PROBABILITE_PASSIF_EVENTUEL: Final[str] = "possible"

MENTION_PROPOSITION: Final[str] = (
    "Proposition indicative à valider par l'expert-comptable ; "
    "comptes à adapter au plan de l'entité."
)
MENTION_BAREME: Final[str] = (
    "Pénalités incluses selon le barème indicatif : intérêt de retard "
    "0,5 %/mois plafonné à 50 % du droit simple, pénalité d'assiette "
    "25 % (bonne foi présumée). " + MENTION_INDICATIVE
)
MENTION_PASSIFS: Final[str] = (
    "Risques ouverts « possibles » : non provisionnés, à mentionner en "
    "annexe comme passifs éventuels."
)


class ErreurProvisionRisques(Exception):
    """Échec du calcul de provision (ex. contribuable hors tenant)."""


def _decimal(valeur: Any) -> Decimal:
    if valeur is None or valeur == "":
        return Decimal("0")
    return Decimal(str(valeur))


def _exposition_risque(risque: dict[str, Any]) -> Decimal:
    """Exposition totale d'un risque, pénalités incluses.

    Priorité au chiffrage indicatif (``chiffrage_penalites.total_estime``,
    déjà pénalités + intérêts inclus) ; à défaut, cumul brut
    montant_estime + penalites_estimees saisis.
    """
    chiffrage = risque.get("chiffrage_penalites")
    if isinstance(chiffrage, dict) and chiffrage.get("total_estime"):
        return _decimal(chiffrage["total_estime"])
    return _decimal(risque.get("montant_estime")) + _decimal(
        risque.get("penalites_estimees")
    )


def calculer_provision_depuis_risques(
    risques: list[dict[str, Any]],
    *,
    exercice_courant: int | None = None,
) -> dict[str, Any]:
    """Provision pour risques fiscaux — fonction pure, testable.

    ``risques`` : liste sérialisée du registre (voir ``risques.lister_risques``).
    Montants renvoyés en ``str`` (JSON-safe, FCFA entiers).
    """
    exercice = int(exercice_courant or date.today().year)
    lignes: list[dict[str, Any]] = []
    passifs: list[dict[str, Any]] = []
    total = Decimal("0")

    for r in risques:
        statut = str(r.get("statut") or "ouvert").lower()
        if statut not in STATUTS_NON_CLOS:
            continue
        probabilite = str(r.get("probabilite") or "possible").lower()
        chiffrage = r.get("chiffrage_penalites")
        base = (
            _decimal(chiffrage.get("droit_simple"))
            if isinstance(chiffrage, dict)
            else _decimal(r.get("montant_estime"))
        )
        exposition = _exposition_risque(r)
        if probabilite == PROBABILITE_PROVISIONNABLE:
            lignes.append(
                {
                    "risque_id": int(r["id"]),
                    "titre": str(r.get("libelle") or ""),
                    "impot": str(r.get("impot") or ""),
                    "exercice": int(r.get("exercice_origine") or 0),
                    "probabilite": probabilite,
                    "statut": statut,
                    "base_droit_simple": str(base),
                    "penalites_interets": str(exposition - base),
                    "montant_provisionnable": str(exposition),
                }
            )
            total += exposition
        elif probabilite == PROBABILITE_PASSIF_EVENTUEL:
            passifs.append(
                {
                    "risque_id": int(r["id"]),
                    "titre": str(r.get("libelle") or ""),
                    "montant_estime": str(exposition),
                }
            )

    libelle = f"Provision pour risques fiscaux — exercice {exercice}"
    ecriture = {
        "libelle": libelle,
        "lignes": [
            {
                "compte": COMPTE_DOTATION,
                "intitule": INTITULE_DOTATION,
                "sens": "debit",
                "montant": str(total),
            },
            {
                "compte": COMPTE_PROVISION,
                "intitule": INTITULE_PROVISION,
                "sens": "credit",
                "montant": str(total),
            },
        ],
    }
    hypotheses = [MENTION_PROPOSITION, MENTION_BAREME]
    if passifs:
        hypotheses.append(MENTION_PASSIFS)

    return {
        "lignes": lignes,
        "total_provision": str(total),
        "passifs_eventuels": passifs,
        "ecriture_proposee": ecriture,
        "hypotheses": hypotheses,
    }


def calculer_provision(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Provision pour risques fiscaux d'un contribuable (RLS).

    Lève ``ErreurProvisionRisques`` (« introuvable ») si le contribuable
    n'existe pas dans le tenant — pas de fuite cross-tenant.
    """
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT id FROM contribuable WHERE id = :c"),
            {"c": contribuable_id},
        ).scalar_one_or_none()
    if existe is None:
        raise ErreurProvisionRisques(
            f"contribuable {contribuable_id} introuvable"
        )

    risques = lister_risques(
        session, tenant_id, contribuable_id=contribuable_id
    )
    resultat = calculer_provision_depuis_risques(risques)
    resultat["contribuable_id"] = contribuable_id
    return resultat
