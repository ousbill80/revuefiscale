"""Comparatif déterministe entre deux exécutions d'une même mission.

Une mission de revue fiscale peut être exécutée plusieurs fois : après une
première passe (constats non vérifiables), le cabinet adresse une demande
de renseignements, saisit les réponses client, puis relance une exécution.
L'associé veut voir CE QUI A CHANGÉ entre les deux exécutions : constats
passés de non_verifiable à conforme/anomalie, nouveaux constats, constats
disparus, évolution des montants. Aucun LLM — lecture seule, déterministe.

Classement d'une transition (avant → après) pour une règle présente dans
les deux exécutions :
- vers ``conforme`` / ``sous_seuil`` / ``hors_perimetre`` depuis un statut
  à risque (``anomalie`` / ``non_verifiable``) → amélioration ;
- vers ``anomalie`` → dégradation (idem apparition d'une anomalie sur une
  règle nouvelle : reprise aussi dans ``degradations`` avec avant=None) ;
- depuis un statut sans risque vers ``non_verifiable`` → dégradation ;
- toujours à risque dans les deux (dont non_verifiable→non_verifiable et
  anomalie→non_verifiable) → inchangé à risque.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

STATUTS_A_RISQUE: Final[frozenset[str]] = frozenset(
    {"anomalie", "non_verifiable"}
)
STATUT_DEFAUT: Final[str] = "anomalie"


class ErreurComparatifExecutions(Exception):
    """Echec métier du comparatif d'exécutions (mission/exécutions)."""


def _dec_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return str(Decimal(str(v)))
    except Exception:  # noqa: BLE001 — valeur non numérique tolérée
        return str(v)


def _item(
    regle_id: str,
    avant: dict[str, Any] | None,
    apres: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "regle_id": regle_id,
        "avant": avant["statut"] if avant is not None else None,
        "apres": apres["statut"] if apres is not None else None,
        "montant_avant": avant["montant"] if avant is not None else None,
        "montant_apres": apres["montant"] if apres is not None else None,
    }


def classer_transitions(
    conclusions_a: dict[str, dict[str, Any]],
    conclusions_b: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Classe les règles des deux exécutions — pure, testable.

    ``conclusions_x`` : {regle_id: {"statut": str, "montant": str|None}}.
    """
    ameliorations: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    inchanges_a_risque: list[dict[str, Any]] = []
    nouveaux: list[dict[str, Any]] = []
    disparus: list[dict[str, Any]] = []

    for regle_id in sorted(set(conclusions_a) | set(conclusions_b)):
        avant = conclusions_a.get(regle_id)
        apres = conclusions_b.get(regle_id)
        if avant is None and apres is not None:
            nouveaux.append(_item(regle_id, None, apres))
            if apres["statut"] == "anomalie":
                # Apparition d'une anomalie = dégradation.
                degradations.append(_item(regle_id, None, apres))
            continue
        if apres is None and avant is not None:
            disparus.append(_item(regle_id, avant, None))
            continue
        assert avant is not None and apres is not None  # noqa: S101
        st_avant, st_apres = avant["statut"], apres["statut"]
        risque_avant = st_avant in STATUTS_A_RISQUE
        risque_apres = st_apres in STATUTS_A_RISQUE
        if risque_avant and not risque_apres:
            ameliorations.append(_item(regle_id, avant, apres))
        elif st_apres == "anomalie" and st_avant != "anomalie":
            degradations.append(_item(regle_id, avant, apres))
        elif not risque_avant and st_apres == "non_verifiable":
            degradations.append(_item(regle_id, avant, apres))
        elif risque_avant and risque_apres:
            inchanges_a_risque.append(_item(regle_id, avant, apres))
        # sans risque des deux côtés (conforme→conforme…) : rien à signaler

    return {
        "ameliorations": ameliorations,
        "degradations": degradations,
        "inchanges_a_risque": inchanges_a_risque,
        "nouveaux": nouveaux,
        "disparus": disparus,
    }


def _charger_conclusions_par_regle(
    session: Session, execution_id: int
) -> dict[str, dict[str, Any]]:
    """Dernière conclusion par regle_id d'une exécution (montant en str)."""
    rows = session.execute(
        text(
            "SELECT rv.regle_id, c.statut, c.montant "
            "FROM conclusion c "
            "JOIN regle_version rv ON rv.id = c.regle_version_id "
            "WHERE c.execution_id = :e ORDER BY c.id"
        ),
        {"e": execution_id},
    ).mappings().all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[str(r["regle_id"])] = {
            "statut": str(r["statut"] or STATUT_DEFAUT),
            "montant": _dec_str(r["montant"]),
        }
    return out


def _delta_montant_anomalies(
    conclusions_a: dict[str, dict[str, Any]],
    conclusions_b: dict[str, dict[str, Any]],
) -> str:
    def total(conclusions: dict[str, dict[str, Any]]) -> Decimal:
        somme = Decimal("0")
        for c in conclusions.values():
            if c["statut"] != "anomalie" or c["montant"] is None:
                continue
            try:
                somme += Decimal(str(c["montant"]))
            except Exception:  # noqa: BLE001 — montant non numérique
                pass
        return somme

    return str(total(conclusions_b) - total(conclusions_a))


def comparer_executions(
    session: Session,
    tenant_id: int,
    mission_id: int,
    execution_a: int | None = None,
    execution_b: int | None = None,
) -> dict[str, Any]:
    """Comparatif entre deux exécutions d'une mission (lecture seule).

    Par défaut A = avant-dernière exécution, B = dernière. Erreur métier
    claire si la mission a moins de deux exécutions, si la mission est
    hors tenant (RLS → introuvable) ou si une exécution demandée
    n'appartient pas à la mission.
    """
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurComparatifExecutions(
                f"mission {mission_id} introuvable"
            )
        executions = session.execute(
            text(
                "SELECT id, lancee_le FROM execution "
                "WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mission_id},
        ).mappings().all()
        if len(executions) < 2:
            raise ErreurComparatifExecutions(
                "au moins deux exécutions sont nécessaires pour comparer "
                f"— la mission {mission_id} n'en compte que "
                f"{len(executions)}"
            )
        par_id = {int(e["id"]): e for e in executions}

        def _resoudre(demande: int | None, defaut_index: int) -> dict:
            if demande is None:
                return executions[defaut_index]
            e = par_id.get(int(demande))
            if e is None:
                raise ErreurComparatifExecutions(
                    f"exécution {demande} introuvable "
                    f"pour la mission {mission_id}"
                )
            return e

        exec_a = _resoudre(execution_a, -2)
        exec_b = _resoudre(execution_b, -1)
        if int(exec_a["id"]) == int(exec_b["id"]):
            raise ErreurComparatifExecutions(
                "les deux exécutions à comparer doivent être distinctes"
            )
        conclusions_a = _charger_conclusions_par_regle(
            session, int(exec_a["id"])
        )
        conclusions_b = _charger_conclusions_par_regle(
            session, int(exec_b["id"])
        )

    categories = classer_transitions(conclusions_a, conclusions_b)

    def _date(e: dict) -> str | None:
        v = e.get("lancee_le")
        return v.isoformat() if hasattr(v, "isoformat") else v

    return {
        "execution_a": {"id": int(exec_a["id"]), "date": _date(exec_a)},
        "execution_b": {"id": int(exec_b["id"]), "date": _date(exec_b)},
        **categories,
        "synthese": {
            "ameliorations": len(categories["ameliorations"]),
            "degradations": len(categories["degradations"]),
            "inchanges_a_risque": len(categories["inchanges_a_risque"]),
            "nouveaux": len(categories["nouveaux"]),
            "disparus": len(categories["disparus"]),
            "delta_montant_anomalies": _delta_montant_anomalies(
                conclusions_a, conclusions_b
            ),
        },
    }
