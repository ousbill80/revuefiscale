"""Analyse de prescription des risques — délai de reprise (pratique LPF CI).

Hypothèse juridique documentée (droit commun) : en pratique, d'après le
Livre de procédures fiscales de Côte d'Ivoire, le droit de reprise de
l'administration s'exerce jusqu'à la fin de la TROISIÈME année suivant
celle au titre de laquelle l'impôt est dû. Un risque né de l'exercice N
est donc réputé prescrit après le 31 décembre de N + 3.

ATTENTION : des délais spéciaux existent (activités occultes, agréments,
déficits reportés, droits d'enregistrement…) — cette analyse est
CONSULTATIVE : elle signale au fiscaliste les risques a priori prescrits
(à basculer au statut « prescrit », exposition à sortir du chiffrage) et
les exercices encore reprenables ; l'humain décide.

Distinct de ``backend.plateforme.prescription`` (R5) : ce dernier est le
socle d'auto-bascule désarmé en attente du référentiel millésimé visé
(Lot 5) et ne calcule aucune date. Ici : analyse consultative en lecture
seule, aucune écriture, aucun LLM — fonctions pures + lecture sous RLS.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import STATUTS_NON_CLOS

# Délai de reprise de droit commun (pratique LPF CI) — voir docstring.
DELAI_REPRISE_ANNEES: Final[int] = 3

MENTION_HYPOTHESE: Final[str] = (
    "Délai de reprise de droit commun (pratique LPF CI) : fin de la 3e "
    "année suivant celle au titre de laquelle l'impôt est dû. Des délais "
    "spéciaux existent — analyse consultative, à valider par le fiscaliste."
)


class ErreurPrescriptionRisques(Exception):
    """Échec de l'analyse (ex. mission hors tenant → « introuvable »)."""


def date_prescription(exercice_origine: int) -> date:
    """Date de prescription de droit commun d'un exercice.

    Hypothèse (pratique LPF CI, droit commun) : le droit de reprise court
    jusqu'au 31 décembre de ``exercice_origine + 3``. Les délais spéciaux
    ne sont pas modélisés ici (analyse consultative).
    """
    return date(int(exercice_origine) + DELAI_REPRISE_ANNEES, 12, 31)


def _dans_un_an(aujourd_hui: date) -> date:
    """Même jour l'année suivante (29 février → 28 février)."""
    try:
        return aujourd_hui.replace(year=aujourd_hui.year + 1)
    except ValueError:  # 29 février
        return aujourd_hui.replace(year=aujourd_hui.year + 1, day=28)


def _montant_expose(risque: dict[str, Any]) -> Decimal | None:
    """Exposition brute d'un risque : montant_estime + penalites_estimees."""
    montant = risque.get("montant_estime")
    penalites = risque.get("penalites_estimees")
    if montant is None and penalites is None:
        return None
    total = Decimal("0")
    if montant is not None and montant != "":
        total += Decimal(str(montant))
    if penalites is not None and penalites != "":
        total += Decimal(str(penalites))
    return total


def _item(risque: dict[str, Any], limite: date) -> dict[str, Any]:
    montant = _montant_expose(risque)
    return {
        "risque_id": int(risque.get("id") or risque.get("risque_id")),
        "libelle": str(risque.get("libelle") or ""),
        "impot": str(risque.get("impot") or "").upper(),
        "exercice_origine": int(risque["exercice_origine"]),
        "statut": str(risque.get("statut") or "ouvert"),
        "montant": str(montant) if montant is not None else None,
        "date_prescription": limite.isoformat(),
    }


def analyser_prescription(
    risques: list[dict[str, Any]], aujourd_hui: date
) -> dict[str, Any]:
    """Classe les risques NON CLOS face au délai de reprise — fonction pure.

    Retourne ``{prescrits_a_basculer, proches_prescription, non_prescrits,
    exposition_prescrite}`` :

    - ``prescrits_a_basculer`` : date de prescription déjà dépassée
      (``< aujourd_hui``) — à basculer au statut « prescrit » ;
    - ``proches_prescription`` : prescription dans les 12 mois ;
    - ``non_prescrits`` : le reste (exercices encore reprenables) ;
    - ``exposition_prescrite`` : somme (str Decimal) des montants exposés
      des risques prescrits (montant_estime + penalites_estimees).

    Les risques clos (résolu, accepté, prescrit) sont ignorés.
    """
    horizon = _dans_un_an(aujourd_hui)
    prescrits: list[dict[str, Any]] = []
    proches: list[dict[str, Any]] = []
    non_prescrits: list[dict[str, Any]] = []
    exposition = Decimal("0")

    for r in risques:
        statut = str(r.get("statut") or "ouvert").lower()
        if statut not in STATUTS_NON_CLOS:
            continue
        limite = date_prescription(int(r["exercice_origine"]))
        item = _item(r, limite)
        if limite < aujourd_hui:
            prescrits.append(item)
            montant = _montant_expose(r)
            if montant is not None:
                exposition += montant
        elif limite <= horizon:
            proches.append(item)
        else:
            non_prescrits.append(item)

    return {
        "prescrits_a_basculer": prescrits,
        "proches_prescription": proches,
        "non_prescrits": non_prescrits,
        "exposition_prescrite": str(exposition),
    }


def exercices_reprenables(aujourd_hui: date) -> list[int]:
    """Les trois derniers exercices clos encore reprenables (droit commun).

    Un exercice N reste reprenable tant que ``date_prescription(N)`` n'est
    pas dépassée, soit ``N >= année_courante - 3``. On liste les trois
    derniers exercices clos : ``[A-3, A-2, A-1]``.
    """
    annee = aujourd_hui.year
    return [annee - 3, annee - 2, annee - 1]


def analyse_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Analyse de prescription des risques du contribuable d'une mission.

    Lecture seule sous RLS. Lève ``ErreurPrescriptionRisques``
    (« introuvable ») si la mission n'existe pas dans le tenant.
    """
    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text("SELECT id, contribuable_id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurPrescriptionRisques(
                f"mission {mission_id} introuvable"
            )
        contribuable_id = int(mission["contribuable_id"])
        rows = session.execute(
            text(
                "SELECT id, libelle, impot, exercice_origine, statut, "
                "montant_estime, penalites_estimees "
                "FROM risque WHERE contribuable_id = :c "
                "AND statut = ANY(:sts) "
                "ORDER BY exercice_origine ASC, id ASC"
            ),
            {"c": contribuable_id, "sts": list(STATUTS_NON_CLOS)},
        ).mappings().all()

    analyse = analyser_prescription([dict(r) for r in rows], jour)
    return {
        "mission_id": int(mission["id"]),
        "contribuable_id": contribuable_id,
        "date_analyse": jour.isoformat(),
        "exercices_reprenables": exercices_reprenables(jour),
        "analyse": analyse,
        "synthese": {
            "prescrits_a_basculer": len(analyse["prescrits_a_basculer"]),
            "proches_prescription": len(analyse["proches_prescription"]),
            "non_prescrits": len(analyse["non_prescrits"]),
            "exposition_prescrite": analyse["exposition_prescrite"],
        },
        "hypothese": MENTION_HYPOTHESE,
    }
