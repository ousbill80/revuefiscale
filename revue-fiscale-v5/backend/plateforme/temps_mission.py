"""Suivi des temps passés par mission (pilotage de la rentabilité).

POURQUOI : un cabinet pilote la rentabilité de ses missions en comparant
le temps réellement passé (valorisé au taux horaire) aux honoraires
convenus. Chaque collaborateur saisit ses temps par mission avec une
phase (cadrage, collecte, controles, restitution, suivi) et une date ;
l'associé consulte le récapitulatif : total d'heures, répartition par
phase et par collaborateur, valorisation au taux horaire fourni.

La lettre de mission ne porte pas d'honoraires structurés dans ce socle
(champ « [à compléter] » du .docx) : la comparaison aux honoraires est
donc omise — seule la valorisation ``total × taux_horaire`` est exposée.

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. Le calcul du récapitulatif est une fonction
pure (:func:`recap_depuis_entrees`) testable sans base.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

PHASES_MISSION: Final = (
    "cadrage",
    "collecte",
    "controles",
    "restitution",
    "suivi",
)


def _fmt(d: Decimal) -> str:
    """Décimal en texte lisible, sans notation scientifique ni zéros finaux."""
    return format(d.normalize(), "f")


class ErreurTempsMission(Exception):
    """Saisie de temps invalide (phase, heures…) — 422 côté route."""


class ErreurTempsIntrouvable(ErreurTempsMission):
    """Mission ou entrée de temps hors périmètre du tenant — 404."""


def _mission_existe(session: Session, mission_id: int) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        is not None
    )


def _valider_heures(heures: Any) -> Decimal:
    """Heures > 0 et <= 24, deux décimales max — sinon 422."""
    try:
        h = Decimal(str(heures))
    except (InvalidOperation, ValueError) as e:
        raise ErreurTempsMission(f"heures invalides « {heures} »") from e
    if not h.is_finite() or h <= 0 or h > 24:
        raise ErreurTempsMission(
            f"heures invalides « {heures} » — attendu : 0 < heures <= 24"
        )
    if -h.as_tuple().exponent > 2:
        raise ErreurTempsMission(
            f"heures invalides « {heures} » — deux décimales maximum"
        )
    return h


def saisir_temps(
    session: Session,
    tenant_id: int,
    mission_id: int,
    collaborateur: str,
    phase: str,
    date_jour: date,
    heures: Any,
    note: str | None = None,
) -> dict[str, Any]:
    """Enregistre une entrée de temps sur la mission — retourne l'entrée.

    La mission doit exister sous RLS (sinon
    :class:`ErreurTempsIntrouvable` → 404). ``phase`` est validée contre
    :data:`PHASES_MISSION` et ``heures`` contre 0 < h <= 24 (sinon
    :class:`ErreurTempsMission` → 422).
    """
    phase = str(phase or "").strip()
    if phase not in PHASES_MISSION:
        raise ErreurTempsMission(
            f"phase invalide « {phase} » — attendues : "
            + ", ".join(PHASES_MISSION)
        )
    collaborateur = str(collaborateur or "").strip()
    if not collaborateur:
        raise ErreurTempsMission("collaborateur obligatoire")
    h = _valider_heures(heures)

    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurTempsIntrouvable(f"mission {mission_id} introuvable")
        row = session.execute(
            text(
                "INSERT INTO temps_mission "
                "(tenant_id, mission_id, collaborateur, phase, date_jour, "
                "heures, note) "
                "VALUES (:t, :m, :c, :p, :d, :h, :n) "
                "RETURNING id, collaborateur, phase, date_jour, heures, "
                "note, saisi_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": collaborateur,
                "p": phase,
                "d": date_jour,
                "h": h,
                "n": (str(note or "").strip() or None),
            },
        ).mappings().one()
    return _serialiser_entree(row)


def supprimer_temps(
    session: Session, tenant_id: int, mission_id: int, temps_id: int
) -> dict[str, Any]:
    """Supprime une entrée de temps (erreur de saisie) — retourne l'entrée.

    Mission ou entrée hors périmètre du tenant →
    :class:`ErreurTempsIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurTempsIntrouvable(f"mission {mission_id} introuvable")
        row = session.execute(
            text(
                "DELETE FROM temps_mission "
                "WHERE id = :i AND mission_id = :m "
                "RETURNING id, collaborateur, phase, date_jour, heures, "
                "note, saisi_le"
            ),
            {"i": temps_id, "m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurTempsIntrouvable(
            f"entrée de temps {temps_id} introuvable pour la mission "
            f"{mission_id}"
        )
    return _serialiser_entree(row)


def _serialiser_entree(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "collaborateur": str(row["collaborateur"]),
        "phase": str(row["phase"]),
        "date_jour": row["date_jour"].isoformat(),
        "heures": _fmt(Decimal(str(row["heures"]))),
        "note": row["note"],
        "saisi_le": row["saisi_le"].isoformat(),
    }


def recap_depuis_entrees(
    entrees: list[dict[str, Any]], taux_horaire: Any = None
) -> dict[str, Any]:
    """Récapitulatif PUR (sans base) des temps d'une mission.

    ``entrees`` : liste sérialisée (:func:`_serialiser_entree`). Retourne
    {entrees (triées date desc puis id desc), total_heures (str),
    par_phase: {phase: heures str}, par_collaborateur: {nom: heures str},
    valorisation: str|None (total × taux_horaire si fourni)} — le pivot
    rentabilité de l'associé : où part le temps, ce qu'il vaut.
    """
    tri = sorted(
        entrees,
        key=lambda e: (str(e["date_jour"]), int(e.get("id") or 0)),
        reverse=True,
    )
    total = Decimal("0")
    par_phase: dict[str, Decimal] = {}
    par_collab: dict[str, Decimal] = {}
    for e in tri:
        h = Decimal(str(e["heures"]))
        total += h
        phase = str(e["phase"])
        collab = str(e["collaborateur"])
        par_phase[phase] = par_phase.get(phase, Decimal("0")) + h
        par_collab[collab] = par_collab.get(collab, Decimal("0")) + h
    valorisation: str | None = None
    if taux_horaire is not None:
        try:
            taux = Decimal(str(taux_horaire))
        except (InvalidOperation, ValueError) as e:
            raise ErreurTempsMission(
                f"taux horaire invalide « {taux_horaire} »"
            ) from e
        if not taux.is_finite() or taux < 0:
            raise ErreurTempsMission(
                f"taux horaire invalide « {taux_horaire} »"
            )
        valorisation = _fmt(total * taux)
    return {
        "entrees": tri,
        "total_heures": _fmt(total),
        "par_phase": {p: _fmt(h) for p, h in par_phase.items()},
        "par_collaborateur": {
            c: _fmt(h) for c, h in par_collab.items()
        },
        "valorisation": valorisation,
    }


def recap_temps(
    session: Session,
    tenant_id: int,
    mission_id: int,
    taux_horaire: Any = None,
) -> dict[str, Any]:
    """Récapitulatif des temps de la mission (lecture + calcul pur).

    Mission hors tenant → :class:`ErreurTempsIntrouvable` (404). Taux
    horaire invalide → :class:`ErreurTempsMission` (422). Le calcul est
    délégué à :func:`recap_depuis_entrees`.
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurTempsIntrouvable(f"mission {mission_id} introuvable")
        rows = session.execute(
            text(
                "SELECT id, collaborateur, phase, date_jour, heures, note, "
                "saisi_le FROM temps_mission WHERE mission_id = :m "
                "ORDER BY date_jour DESC, id DESC"
            ),
            {"m": mission_id},
        ).mappings().all()
    return recap_depuis_entrees(
        [_serialiser_entree(r) for r in rows], taux_horaire
    )
