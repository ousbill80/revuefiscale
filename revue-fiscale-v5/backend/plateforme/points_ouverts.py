"""Points ouverts inter-missions — legacy lecture (hors calcul fiscal).

Écritures API coupées (410 → /risques). Les stubs creer/patch lèvent
explicitement pour éviter toute réouverture accidentelle.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

STATUTS_POINT = frozenset({"ouvert", "repris", "clos"})

MSG_ECRITURE_DEPRECATED = (
    "point_ouvert écriture dépréciée après R4 — utiliser /api/v1/risques"
)


class ErreurPointOuvert(Exception):
    """Echec lecture / écriture refusée point ouvert."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    cree = row.get("cree_le")
    maj = row.get("maj_le")
    return {
        "id": int(row["id"]),
        "contribuable_id": int(row["contribuable_id"]),
        "mission_source_id": (
            int(row["mission_source_id"])
            if row.get("mission_source_id") is not None
            else None
        ),
        "conclusion_id": (
            int(row["conclusion_id"])
            if row.get("conclusion_id") is not None
            else None
        ),
        "texte": str(row["texte"]),
        "statut": str(row["statut"]),
        "mission_reprise_id": (
            int(row["mission_reprise_id"])
            if row.get("mission_reprise_id") is not None
            else None
        ),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
        "maj_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
    }


def _lire(
    session: Session, point_id: int
) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT id, contribuable_id, mission_source_id, conclusion_id, "
            "texte, statut, mission_reprise_id, cree_le, maj_le "
            "FROM point_ouvert WHERE id = :id"
        ),
        {"id": point_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurPointOuvert(f"point_ouvert {point_id} introuvable")
    return _serialiser(dict(row))


def lister_points_ouverts(
    session: Session,
    tenant_id: int,
    *,
    contribuable_id: int | None = None,
    statut: str | None = None,
    mission_source_id: int | None = None,
) -> list[dict[str, Any]]:
    clauses = [
        "SELECT id, contribuable_id, mission_source_id, conclusion_id, "
        "texte, statut, mission_reprise_id, cree_le, maj_le "
        "FROM point_ouvert WHERE 1=1"
    ]
    params: dict[str, Any] = {}
    if contribuable_id is not None:
        clauses.append("AND contribuable_id = :c")
        params["c"] = contribuable_id
    if statut is not None:
        st = statut.strip().lower()
        if st not in STATUTS_POINT:
            raise ErreurPointOuvert(
                f"statut filtre invalide {statut!r} — attendu : "
                + ", ".join(sorted(STATUTS_POINT))
            )
        clauses.append("AND statut = :st")
        params["st"] = st
    if mission_source_id is not None:
        clauses.append("AND mission_source_id = :ms")
        params["ms"] = mission_source_id
    clauses.append("ORDER BY id DESC")

    with contexte_tenant(session, tenant_id):
        rows = session.execute(text(" ".join(clauses)), params).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def creer_point_ouvert(
    session: Session,
    tenant_id: int,
    *,
    contribuable_id: int,
    texte: str,
    mission_source_id: int | None = None,
    conclusion_id: int | None = None,
    statut: str = "ouvert",
) -> dict[str, Any]:
    """DEPRECATED — écriture refusée (API 410)."""
    del session, tenant_id, contribuable_id, texte
    del mission_source_id, conclusion_id, statut
    raise ErreurPointOuvert(MSG_ECRITURE_DEPRECATED)


def creer_point_ouvert_depuis_conclusion(
    session: Session,
    tenant_id: int,
    mission_id: int,
    conclusion_id: int,
) -> dict[str, Any]:
    """DEPRECATED — écrire via POST /risques."""
    del session, tenant_id, mission_id, conclusion_id
    raise ErreurPointOuvert(MSG_ECRITURE_DEPRECATED)


def patcher_point_ouvert(
    session: Session,
    tenant_id: int,
    point_id: int,
    *,
    texte: object | None = ...,
    statut: object | None = ...,
    mission_reprise_id: object | None = ...,
) -> dict[str, Any]:
    """DEPRECATED — écriture refusée (API 410)."""
    del session, tenant_id, point_id, texte, statut, mission_reprise_id
    raise ErreurPointOuvert(MSG_ECRITURE_DEPRECATED)
