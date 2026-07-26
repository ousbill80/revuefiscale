"""Objectifs de mission — libellés libres cabinet (hors moteur fiscal)."""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

LIBELLE_MAX: Final = 500
OBJECTIFS_MAX: Final = 50
# Aligné sur missions.STATUT_CADRAGE — pas d'import croisé.
_STATUT_CADRAGE: Final = "cadrage"


class ErreurObjectif(Exception):
    """Echec CRUD objectifs de mission."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    cree = row.get("cree_le")
    maj = row.get("maj_le")
    return {
        "id": int(row["id"]),
        "mission_id": int(row["mission_id"]),
        "ordre": int(row["ordre"]),
        "libelle": str(row["libelle"]),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
        "maj_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
    }


def normaliser_objectifs_entree(valeur: object | None) -> list[str]:
    """Accepte liste de str ou d'objets {libelle} — refuse libellés vides."""
    if valeur is None:
        return []
    if not isinstance(valeur, (list, tuple)):
        raise ErreurObjectif("objectifs doit être une liste")
    if len(valeur) > OBJECTIFS_MAX:
        raise ErreurObjectif(
            f"trop d'objectifs ({len(valeur)}) — max {OBJECTIFS_MAX}"
        )
    libelles: list[str] = []
    for i, brut in enumerate(valeur):
        if isinstance(brut, str):
            lib = brut.strip()
        elif isinstance(brut, dict):
            lib = str(brut.get("libelle") or "").strip()
        else:
            raise ErreurObjectif(
                f"objectif[{i}] invalide — attendu str ou {{libelle}}"
            )
        if not lib:
            raise ErreurObjectif(f"objectif[{i}] : libelle obligatoire")
        if len(lib) > LIBELLE_MAX:
            raise ErreurObjectif(
                f"objectif[{i}] : libelle trop long (max {LIBELLE_MAX})"
            )
        libelles.append(lib)
    return libelles


def lister_objectifs_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> list[dict[str, Any]]:
    """Liste ordonnée des objectifs d'une mission (RLS)."""
    with contexte_tenant(session, tenant_id):
        mid = session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if mid is None:
            raise ErreurObjectif(f"mission {mission_id} introuvable")
        return lister_objectifs_en_contexte(session, mission_id)


def lister_objectifs_en_contexte(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    """Liste objectifs — contexte tenant déjà posé."""
    rows = session.execute(
        text(
            "SELECT id, mission_id, ordre, libelle, cree_le, maj_le "
            "FROM mission_objectif WHERE mission_id = :m "
            "ORDER BY ordre ASC, id ASC"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [_serialiser(dict(r)) for r in rows]


def _exiger_mission_cadrage(
    session: Session, mission_id: int
) -> dict[str, Any]:
    row = session.execute(
        text("SELECT id, statut FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurObjectif(f"mission {mission_id} introuvable")
    statut = str(row["statut"] or _STATUT_CADRAGE).lower()
    if statut != _STATUT_CADRAGE:
        raise ErreurObjectif(
            f"cadrage figé (statut={statut}) — objectifs non modifiables"
        )
    return dict(row)


def remplacer_objectifs_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    objectifs: object | None,
    *,
    verifier_cadrage: bool = True,
) -> list[dict[str, Any]]:
    """Remplace la liste complète des objectifs (transaction RLS).

    ``verifier_cadrage=False`` pour création mission (déjà en cadrage).
    """
    libelles = normaliser_objectifs_entree(objectifs)

    with contexte_tenant(session, tenant_id):
        if verifier_cadrage:
            _exiger_mission_cadrage(session, mission_id)
        else:
            mid = session.execute(
                text("SELECT id FROM mission WHERE id = :m"),
                {"m": mission_id},
            ).scalar_one_or_none()
            if mid is None:
                raise ErreurObjectif(f"mission {mission_id} introuvable")

        session.execute(
            text("DELETE FROM mission_objectif WHERE mission_id = :m"),
            {"m": mission_id},
        )
        for ordre, libelle in enumerate(libelles):
            session.execute(
                text(
                    "INSERT INTO mission_objectif "
                    "(tenant_id, mission_id, ordre, libelle) "
                    "VALUES (:t, :m, :o, :lib)"
                ),
                {
                    "t": tenant_id,
                    "m": mission_id,
                    "o": ordre,
                    "lib": libelle,
                },
            )
        session.flush()
        return lister_objectifs_en_contexte(session, mission_id)
