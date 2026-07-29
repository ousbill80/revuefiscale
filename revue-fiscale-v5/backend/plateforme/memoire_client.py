"""Mémoire client — Data Room phase 1, entrées persistantes du contribuable."""
from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

logger = logging.getLogger(__name__)

TYPES_ENTREE: Final[frozenset[str]] = frozenset(
    {"fait", "contexte", "alerte", "note"}
)
SOURCES_ENTREE: Final[frozenset[str]] = frozenset(
    {"extraction", "mission", "risque", "manuel", "synthese"}
)
CONTENU_MAX: Final[int] = 4000


class ErreurMemoireClient(Exception):
    """Echec CRUD mémoire client."""


def valider_entree_memoire(
    *, type_entree: str, contenu: str, source_type: str
) -> tuple[str, str, str]:
    """Valide et normalise (type_entree, contenu, source_type) — pure."""
    te = (type_entree or "").strip().lower()
    if te not in TYPES_ENTREE:
        raise ErreurMemoireClient(
            f"type_entree invalide {type_entree!r} — attendu : "
            + ", ".join(sorted(TYPES_ENTREE))
        )
    st = (source_type or "").strip().lower()
    if st not in SOURCES_ENTREE:
        raise ErreurMemoireClient(
            f"source_type invalide {source_type!r} — attendu : "
            + ", ".join(sorted(SOURCES_ENTREE))
        )
    texte = (contenu or "").strip()
    if not texte:
        raise ErreurMemoireClient("contenu obligatoire")
    if len(texte) > CONTENU_MAX:
        raise ErreurMemoireClient(
            f"contenu trop long ({len(texte)} caractères — max {CONTENU_MAX})"
        )
    return te, texte, st


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    cree = row.get("cree_le")
    return {
        "id": int(row["id"]),
        "contribuable_id": int(row["contribuable_id"]),
        "type_entree": str(row["type_entree"]),
        "contenu": str(row["contenu"]),
        "source_type": str(row["source_type"]),
        "source_ref": row.get("source_ref"),
        "auteur": row.get("auteur"),
        "actif": bool(row.get("actif", True)),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
    }


def lister_memoire(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    type_entree: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"c": contribuable_id}
    sql = (
        "SELECT id, contribuable_id, type_entree, contenu, source_type, "
        "source_ref, auteur, actif, cree_le FROM memoire_client "
        "WHERE contribuable_id = :c AND actif"
    )
    if type_entree is not None:
        te = (type_entree or "").strip().lower()
        if te not in TYPES_ENTREE:
            raise ErreurMemoireClient(
                f"type_entree invalide {type_entree!r} — attendu : "
                + ", ".join(sorted(TYPES_ENTREE))
            )
        sql += " AND type_entree = :te"
        params["te"] = te
    sql += " ORDER BY cree_le DESC, id DESC"

    with contexte_tenant(session, tenant_id):
        rows = session.execute(text(sql), params).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def ajouter_entree_memoire(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    *,
    type_entree: str,
    contenu: str,
    source_type: str,
    source_ref: str | None = None,
    auteur: str | None = None,
) -> dict[str, Any]:
    te, texte, st = valider_entree_memoire(
        type_entree=type_entree, contenu=contenu, source_type=source_type
    )
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text("SELECT id FROM contribuable WHERE id = :c"),
            {"c": contribuable_id},
        ).scalar_one_or_none()
        if contrib is None:
            raise ErreurMemoireClient(
                f"contribuable {contribuable_id} introuvable"
            )
        row = session.execute(
            text(
                "INSERT INTO memoire_client "
                "(tenant_id, contribuable_id, type_entree, contenu, "
                "source_type, source_ref, auteur) "
                "VALUES (:t, :c, :te, :ct, :st, :ref, :aut) "
                "RETURNING id, contribuable_id, type_entree, contenu, "
                "source_type, source_ref, auteur, actif, cree_le"
            ),
            {
                "t": tenant_id,
                "c": contribuable_id,
                "te": te,
                "ct": texte,
                "st": st,
                "ref": (source_ref or "").strip() or None,
                "aut": (auteur or "").strip() or None,
            },
        ).mappings().one()
        session.flush()
        return _serialiser(dict(row))


def desactiver_entree_memoire(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    entree_id: int,
) -> dict[str, Any]:
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE memoire_client SET actif = false "
                "WHERE id = :id AND contribuable_id = :c AND actif "
                "RETURNING id, contribuable_id, type_entree, contenu, "
                "source_type, source_ref, auteur, actif, cree_le"
            ),
            {"id": entree_id, "c": contribuable_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurMemoireClient(
                f"entrée mémoire {entree_id} introuvable"
            )
        session.flush()
        return _serialiser(dict(row))


def alimenter_memoire(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    *,
    type_entree: str,
    contenu: str,
    source_type: str,
    source_ref: str | None = None,
) -> None:
    """Alimentation automatique best-effort — ne fait jamais échouer l'appelant.

    SAVEPOINT obligatoire : sans lui, un échec SQL avorterait toute la
    transaction de l'opération principale.
    """
    try:
        with session.begin_nested():
            ajouter_entree_memoire(
                session,
                tenant_id,
                contribuable_id,
                type_entree=type_entree,
                contenu=contenu,
                source_type=source_type,
                source_ref=source_ref,
                auteur="systeme",
            )
    except Exception:
        logger.warning(
            "alimentation mémoire client ignorée (contribuable %s, source %s)",
            contribuable_id,
            source_ref or source_type,
            exc_info=True,
        )


def timeline_contribuable(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Evénements du journal d'audit liés au contribuable, ordre desc."""
    lim = max(1, min(int(limite), 200))
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT j.id, j.horodatage, j.acteur, j.action, "
                "j.mission_id, j.charge_utile "
                "FROM journal_audit j "
                "LEFT JOIN mission m ON m.id = j.mission_id "
                "WHERE m.contribuable_id = :c "
                "OR j.charge_utile ->> 'contribuable_id' = :ctxt "
                "ORDER BY j.id DESC LIMIT :lim"
            ),
            {"c": contribuable_id, "ctxt": str(contribuable_id), "lim": lim},
        ).mappings().all()
    from backend.plateforme.journal_cabinet import libelle_action

    evenements: list[dict[str, Any]] = []
    for r in rows:
        quand = r.get("horodatage")
        action = str(r.get("action") or "")
        evenements.append(
            {
                "id": int(r["id"]),
                "horodatage": (
                    quand.isoformat()
                    if hasattr(quand, "isoformat")
                    else quand
                ),
                "acteur": str(r.get("acteur") or ""),
                "action": action,
                "libelle": libelle_action(action),
                "consultation": action.startswith("consultation_"),
                "mission_id": (
                    int(r["mission_id"])
                    if r.get("mission_id") is not None
                    else None
                ),
                "charge_utile": dict(r.get("charge_utile") or {}),
            }
        )
    return evenements
