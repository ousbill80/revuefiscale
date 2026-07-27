"""Historique pluriannuel d'un contribuable — vision associé.

POURQUOI : un cabinet suit un même contribuable sur plusieurs exercices
(une mission par exercice). L'associé a besoin d'une lecture
PLURIANNUELLE pour repérer la RÉCURRENCE des faiblesses (des anomalies
qui reviennent exercice après exercice signalent un défaut de process
chez le client, pas un accident) et pour raisonner PRESCRIPTION : en
Côte d'Ivoire, le droit de reprise de l'administration est en principe
de trois ans (art. L171 s. LPF) — un risque non corrigé se reconstitue
à chaque exercice alors que les plus anciens se prescrivent.

Pour chaque exercice : statut de la mission, nombre d'exécutions,
répartition des conclusions de la DERNIÈRE exécution (photo la plus
récente du dossier), montant cumulé des anomalies, score de risque
heuristique si une exécution existe, et tendance du nombre d'anomalies
par rapport à l'exercice précédent. S'y ajoutent les risques encore
ouverts du registre (tous exercices confondus).

AUCUN appel LLM — lecture seule, déterministe, sous RLS.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import STATUTS_NON_CLOS, lister_risques
from backend.restitution.risques import scorer_risques

STATUTS_COMPTES: Final[frozenset[str]] = frozenset(
    {"anomalie", "non_verifiable", "conforme"}
)


class ErreurHistoriqueContribuable(Exception):
    """Echec métier de l'historique (ex. contribuable hors tenant)."""


def calculer_tendances(nb_anomalies: list[int]) -> list[str | None]:
    """Tendance exercice par exercice — fonction pure, testable.

    ``nb_anomalies`` : nombre d'anomalies par exercice, trié par exercice
    croissant. Retour aligné : ``None`` pour le premier exercice (pas de
    référence), puis ``"hausse"`` / ``"baisse"`` / ``"stable"`` par
    rapport à l'exercice précédent.
    """
    tendances: list[str | None] = []
    for i, nb in enumerate(nb_anomalies):
        if i == 0:
            tendances.append(None)
            continue
        precedent = nb_anomalies[i - 1]
        if nb > precedent:
            tendances.append("hausse")
        elif nb < precedent:
            tendances.append("baisse")
        else:
            tendances.append("stable")
    return tendances


def _conclusions_derniere_execution(
    session: Session, execution_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT statut, montant, niveau_risque FROM conclusion "
            "WHERE execution_id = :e ORDER BY id"
        ),
        {"e": execution_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _repartition(conclusions: list[dict[str, Any]]) -> dict[str, int]:
    repartition = {
        "anomalie": 0,
        "non_verifiable": 0,
        "conforme": 0,
        "autres": 0,
    }
    for c in conclusions:
        statut = str(c.get("statut") or "anomalie")
        if statut in STATUTS_COMPTES:
            repartition[statut] += 1
        else:  # sous_seuil, hors_perimetre…
            repartition["autres"] += 1
    return repartition


def _montant_anomalies(conclusions: list[dict[str, Any]]) -> str:
    somme = Decimal("0")
    for c in conclusions:
        if str(c.get("statut") or "") != "anomalie":
            continue
        montant = c.get("montant")
        if montant is None or montant == "":
            continue
        try:
            somme += Decimal(str(montant))
        except Exception:  # noqa: BLE001 — montant non numérique toléré
            pass
    return str(somme)


def construire_historique(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Vision pluriannuelle d'un contribuable (lecture seule, RLS).

    Lève ``ErreurHistoriqueContribuable`` (« introuvable ») si le
    contribuable n'existe pas dans le tenant — pas de fuite cross-tenant.
    """
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "SELECT id, denomination, ncc FROM contribuable "
                "WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contrib is None:
            raise ErreurHistoriqueContribuable(
                f"contribuable {contribuable_id} introuvable"
            )

        missions = session.execute(
            text(
                "SELECT id, exercice, statut FROM mission "
                "WHERE contribuable_id = :c "
                "ORDER BY exercice ASC, id ASC"
            ),
            {"c": contribuable_id},
        ).mappings().all()

        exercices: list[dict[str, Any]] = []
        for m in missions:
            mission_id = int(m["id"])
            executions = session.execute(
                text(
                    "SELECT id FROM execution "
                    "WHERE mission_id = :m ORDER BY id"
                ),
                {"m": mission_id},
            ).scalars().all()
            derniere = int(executions[-1]) if executions else None
            conclusions = (
                _conclusions_derniere_execution(session, derniere)
                if derniere is not None
                else []
            )
            exercices.append(
                {
                    "exercice": int(m["exercice"]),
                    "mission_id": mission_id,
                    "statut_mission": str(m["statut"]),
                    "nb_executions": len(executions),
                    "derniere_execution_id": derniere,
                    "conclusions": _repartition(conclusions),
                    "montant_anomalies": _montant_anomalies(conclusions),
                    "score_risque": (
                        scorer_risques(conclusions).score
                        if derniere is not None
                        else None
                    ),
                    "tendance_anomalies": None,  # posé ci-dessous
                }
            )

    tendances = calculer_tendances(
        [e["conclusions"]["anomalie"] for e in exercices]
    )
    for e, tendance in zip(exercices, tendances):
        e["tendance_anomalies"] = tendance

    risques_ouverts = [
        {
            "id": r["id"],
            "libelle": r["libelle"],
            "impot": r["impot"],
            "exercice_origine": r["exercice_origine"],
            "statut": r["statut"],
            "montant_estime": r["montant_estime"],
        }
        for r in lister_risques(
            session, tenant_id, contribuable_id=contribuable_id
        )
        if r["statut"] in STATUTS_NON_CLOS
    ]

    total_dernier = (
        exercices[-1]["conclusions"]["anomalie"] if exercices else 0
    )
    return {
        "contribuable": {
            "id": int(contrib["id"]),
            "denomination": str(contrib["denomination"]),
            "ncc": contrib["ncc"],
        },
        "exercices": exercices,
        "risques_ouverts": risques_ouverts,
        "synthese": {
            "nb_exercices": len(exercices),
            "total_anomalies_dernier_exercice": total_dernier,
            "exercices_avec_anomalies": sum(
                1 for e in exercices if e["conclusions"]["anomalie"] > 0
            ),
        },
    }
