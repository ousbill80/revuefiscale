"""Pièces d'identité contribuable — domaine abonné (RLS).

Upload avant création (session_upload) puis rattachement à contribuable_id.
Aucun calcul fiscal ; stockage local sous var/pieces/{tenant}/c/….
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.socle.stockage_pieces import (
    ecrire_piece_contribuable,
    lire_piece,
    supprimer_fichier,
)

TYPES_PIECE_CONTRIBUABLE = frozenset(
    {"dfe", "rccm", "bail", "cie", "sodeci", "autre"}
)

# Plafond configurable par pièce (200 Mo) — défense en profondeur, l'endpoint
# HTTP applique le même plafond avec un statut 413.
TAILLE_MAX_PIECE_OCTETS = 200 * 1024 * 1024


class ErreurPieceContribuable(Exception):
    """Échec métier pièces contribuable."""


def _row_out(row: Any) -> dict[str, Any]:
    d = dict(row)
    if d.get("cree_le") is not None:
        d["cree_le"] = d["cree_le"].isoformat()
    return d


def deposer_piece(
    session: Session,
    tenant_id: int,
    *,
    type_piece: str,
    nom_fichier: str,
    contenu: bytes,
    content_type: str | None = None,
    contribuable_id: int | None = None,
    session_upload: str | None = None,
    auto_detecter_type: bool = True,
    autoriser_vision_classif: bool = True,
) -> dict[str, Any]:
    """Dépose une pièce (avant ou après création fiche).

    Par défaut : classifie depuis contenu + nom (proposition corrigible).
    ``auto_detecter_type=False`` conserve ``type_piece`` (correction forcée).
    """
    from backend.abonne.classification_piece import classer_piece

    if not contenu:
        raise ErreurPieceContribuable("fichier vide")
    if len(contenu) > TAILLE_MAX_PIECE_OCTETS:
        raise ErreurPieceContribuable("Fichier trop volumineux (max 200 Mo).")

    brut_type = (type_piece or "").strip().lower()
    if brut_type == "auto":
        brut_type = "autre"

    if auto_detecter_type:
        meta_classif = classer_piece(
            nom_fichier,
            contenu,
            type_impose=None,
            autoriser_vision=autoriser_vision_classif,
        )
        tp = str(meta_classif["type_piece"])
    else:
        tp = brut_type if brut_type in TYPES_PIECE_CONTRIBUABLE else "autre"
        meta_classif = {
            "type_piece": tp,
            "type_detecte": tp,
            "type_source": "manuel",
            "type_confiance": 1.0,
            "type_detecte_auto": False,
            "motif": "saisie manuelle forcée",
        }

    if tp not in TYPES_PIECE_CONTRIBUABLE:
        raise ErreurPieceContribuable(f"type_piece invalide : {type_piece}")
    sid = (session_upload or "").strip() or None
    if contribuable_id is None and not sid:
        raise ErreurPieceContribuable(
            "fournir contribuable_id ou session_upload"
        )

    if contribuable_id is not None:
        existe = session.execute(
            text("SELECT 1 FROM contribuable WHERE id = :id"),
            {"id": contribuable_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurPieceContribuable(
                f"contribuable {contribuable_id} introuvable"
            )
        ancre = f"id_{contribuable_id}"
    else:
        ancre = f"session_{sid}"

    chemin = ecrire_piece_contribuable(tenant_id, ancre, nom_fichier, contenu)
    row = session.execute(
        text(
            "INSERT INTO piece_contribuable ("
            "tenant_id, contribuable_id, session_upload, type_piece, "
            "nom_fichier, chemin_stockage, taille_octets, content_type"
            ") VALUES ("
            ":t, :c, :s, :tp, :nom, :chemin, :taille, :ct"
            ") RETURNING id, tenant_id, contribuable_id, session_upload, "
            "type_piece, nom_fichier, chemin_stockage, taille_octets, "
            "content_type, cree_le"
        ),
        {
            "t": tenant_id,
            "c": contribuable_id,
            "s": sid,
            "tp": tp,
            "nom": nom_fichier,
            "chemin": chemin,
            "taille": len(contenu),
            "ct": content_type,
        },
    ).mappings().one()
    session.flush()
    out = _row_out(row)
    out["type_detecte"] = meta_classif.get("type_detecte") or tp
    out["type_source"] = meta_classif.get("type_source")
    out["type_confiance"] = meta_classif.get("type_confiance")
    out["type_detecte_auto"] = bool(meta_classif.get("type_detecte_auto"))
    out["type_motif"] = meta_classif.get("motif")
    return out


def modifier_type_piece(
    session: Session, piece_id: int, type_piece: str
) -> dict[str, Any]:
    """Correction manuelle du type (humain valide / corrige la proposition IA)."""
    tp = (type_piece or "").strip().lower()
    if tp not in TYPES_PIECE_CONTRIBUABLE:
        raise ErreurPieceContribuable(f"type_piece invalide : {type_piece}")
    piece = piece_par_id(session, piece_id)
    if piece is None:
        raise ErreurPieceContribuable(f"pièce {piece_id} introuvable")
    session.execute(
        text(
            "UPDATE piece_contribuable SET type_piece = :tp WHERE id = :id"
        ),
        {"tp": tp, "id": piece_id},
    )
    session.flush()
    out = piece_par_id(session, piece_id)
    assert out is not None
    out["type_detecte"] = tp
    out["type_source"] = "manuel"
    out["type_confiance"] = 1.0
    out["type_detecte_auto"] = False
    out["type_motif"] = "correction manuelle"
    return out


def lister_pieces(
    session: Session,
    *,
    contribuable_id: int | None = None,
    session_upload: str | None = None,
) -> list[dict[str, Any]]:
    if contribuable_id is None and not (session_upload or "").strip():
        raise ErreurPieceContribuable(
            "fournir contribuable_id ou session_upload"
        )
    if contribuable_id is not None:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, contribuable_id, session_upload, "
                "type_piece, nom_fichier, chemin_stockage, taille_octets, "
                "content_type, cree_le "
                "FROM piece_contribuable "
                "WHERE contribuable_id = :c "
                "ORDER BY cree_le, id"
            ),
            {"c": contribuable_id},
        ).mappings().all()
    else:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, contribuable_id, session_upload, "
                "type_piece, nom_fichier, chemin_stockage, taille_octets, "
                "content_type, cree_le "
                "FROM piece_contribuable "
                "WHERE session_upload = :s "
                "ORDER BY cree_le, id"
            ),
            {"s": session_upload.strip()},
        ).mappings().all()
    return [_row_out(r) for r in rows]


def piece_par_id(session: Session, piece_id: int) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT id, tenant_id, contribuable_id, session_upload, "
            "type_piece, nom_fichier, chemin_stockage, taille_octets, "
            "content_type, cree_le "
            "FROM piece_contribuable WHERE id = :id"
        ),
        {"id": piece_id},
    ).mappings().one_or_none()
    return _row_out(row) if row else None


def retirer_piece(session: Session, piece_id: int) -> dict[str, Any]:
    piece = piece_par_id(session, piece_id)
    if piece is None:
        raise ErreurPieceContribuable(f"pièce {piece_id} introuvable")
    session.execute(
        text("DELETE FROM piece_contribuable WHERE id = :id"),
        {"id": piece_id},
    )
    session.flush()
    if piece.get("chemin_stockage"):
        supprimer_fichier(str(piece["chemin_stockage"]))
    return piece


def rattacher_session(
    session: Session,
    *,
    session_upload: str,
    contribuable_id: int,
) -> list[dict[str, Any]]:
    """Lie les pièces orphelines d'une session au contribuable créé."""
    sid = (session_upload or "").strip()
    if not sid:
        raise ErreurPieceContribuable("session_upload vide")
    existe = session.execute(
        text("SELECT 1 FROM contribuable WHERE id = :id"),
        {"id": contribuable_id},
    ).scalar_one_or_none()
    if existe is None:
        raise ErreurPieceContribuable(
            f"contribuable {contribuable_id} introuvable"
        )
    session.execute(
        text(
            "UPDATE piece_contribuable "
            "SET contribuable_id = :c "
            "WHERE session_upload = :s AND contribuable_id IS NULL"
        ),
        {"c": contribuable_id, "s": sid},
    )
    session.flush()
    return lister_pieces(session, contribuable_id=contribuable_id)


def lire_contenu_piece(session: Session, piece_id: int) -> tuple[dict[str, Any], bytes]:
    piece = piece_par_id(session, piece_id)
    if piece is None:
        raise ErreurPieceContribuable(f"pièce {piece_id} introuvable")
    return piece, lire_piece(str(piece["chemin_stockage"]))


def pieces_par_ids(
    session: Session, piece_ids: list[int]
) -> list[dict[str, Any]]:
    if not piece_ids:
        return []
    rows = session.execute(
        text(
            "SELECT id, tenant_id, contribuable_id, session_upload, "
            "type_piece, nom_fichier, chemin_stockage, taille_octets, "
            "content_type, cree_le "
            "FROM piece_contribuable "
            "WHERE id IN :ids "
            "ORDER BY id"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(piece_ids)},
    ).mappings().all()
    return [_row_out(r) for r in rows]


def ttl_session_heures() -> int:
    """TTL configurable — pièces orphelines (contribuable_id IS NULL)."""
    h = int(getattr(config, "pieces_session_ttl_hours", 72) or 72)
    return max(1, min(h, 24 * 30))


def lister_propositions(
    session: Session,
    *,
    contribuable_id: int | None = None,
    session_upload: str | None = None,
    limite: int = 20,
) -> list[dict[str, Any]]:
    """Historique brouillons IA (lecture seule — jamais écrit dans contribuable)."""
    lim = max(1, min(int(limite), 50))
    if contribuable_id is not None:
        rows = session.execute(
            text(
                "SELECT id, contribuable_id, session_upload, piece_ids, "
                "champs_proposes, citations, statut, message, cree_le "
                "FROM proposition_identite "
                "WHERE contribuable_id = :c "
                "ORDER BY cree_le DESC, id DESC "
                "LIMIT :lim"
            ),
            {"c": contribuable_id, "lim": lim},
        ).mappings().all()
    elif (session_upload or "").strip():
        rows = session.execute(
            text(
                "SELECT id, contribuable_id, session_upload, piece_ids, "
                "champs_proposes, citations, statut, message, cree_le "
                "FROM proposition_identite "
                "WHERE session_upload = :s "
                "ORDER BY cree_le DESC, id DESC "
                "LIMIT :lim"
            ),
            {"s": session_upload.strip(), "lim": lim},
        ).mappings().all()
    else:
        raise ErreurPieceContribuable(
            "fournir contribuable_id ou session_upload"
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("cree_le") is not None:
            d["cree_le"] = d["cree_le"].isoformat()
        # Alias API stables
        d["proposition_id"] = d.pop("id")
        d["champs"] = d.pop("champs_proposes") or {}
        out.append(d)
    return out


def abandonner_session(
    session: Session, *, session_upload: str
) -> dict[str, Any]:
    """Supprime immédiatement les pièces orphelines d'une session (UI abandon)."""
    sid = (session_upload or "").strip()
    if not sid:
        raise ErreurPieceContribuable("session_upload vide")
    pieces = session.execute(
        text(
            "SELECT id, chemin_stockage FROM piece_contribuable "
            "WHERE session_upload = :s AND contribuable_id IS NULL"
        ),
        {"s": sid},
    ).mappings().all()
    chemins = [str(p["chemin_stockage"]) for p in pieces if p.get("chemin_stockage")]
    ids = [int(p["id"]) for p in pieces]
    n_prop = session.execute(
        text(
            "DELETE FROM proposition_identite "
            "WHERE session_upload = :s AND contribuable_id IS NULL"
        ),
        {"s": sid},
    ).rowcount
    if ids:
        session.execute(
            text(
                "DELETE FROM piece_contribuable "
                "WHERE id IN :ids AND contribuable_id IS NULL"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
    session.flush()
    for chemin in chemins:
        supprimer_fichier(chemin)
    return {
        "session_upload": sid,
        "pieces_supprimees": len(ids),
        "propositions_supprimees": int(n_prop or 0),
    }


def lister_sessions_orphelines(
    session: Session,
    *,
    plus_vieux_que: timedelta | None = None,
) -> list[dict[str, Any]]:
    """Sessions avec pièces non rattachées, regroupées (contexte tenant requis)."""
    age = plus_vieux_que if plus_vieux_que is not None else timedelta(
        hours=ttl_session_heures()
    )
    seuil = datetime.now(timezone.utc) - age
    rows = session.execute(
        text(
            "SELECT session_upload, "
            "count(*)::int AS nb_pieces, "
            "min(cree_le) AS plus_ancienne, "
            "max(cree_le) AS plus_recente "
            "FROM piece_contribuable "
            "WHERE contribuable_id IS NULL "
            "AND session_upload IS NOT NULL "
            "AND cree_le < :seuil "
            "GROUP BY session_upload "
            "ORDER BY min(cree_le)"
        ),
        {"seuil": seuil},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("plus_ancienne") is not None:
            d["plus_ancienne"] = d["plus_ancienne"].isoformat()
        if d.get("plus_recente") is not None:
            d["plus_recente"] = d["plus_recente"].isoformat()
        out.append(d)
    return out


def purger_orphelines(
    session: Session,
    *,
    plus_vieux_que: timedelta | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Purge pièces + propositions orphelines au-delà du TTL (tenant courant).

    Ne touche jamais aux lignes avec contribuable_id non NULL
    (même si session_upload reste renseigné après rattachement).
    """
    age = plus_vieux_que if plus_vieux_que is not None else timedelta(
        hours=ttl_session_heures()
    )
    sessions = lister_sessions_orphelines(session, plus_vieux_que=age)
    if dry_run:
        return {
            "dry_run": True,
            "ttl_heures": int(age.total_seconds() // 3600),
            "sessions": sessions,
            "pieces_supprimees": 0,
            "propositions_supprimees": 0,
            "sessions_purgées": 0,
        }
    total_pieces = 0
    total_prop = 0
    details: list[dict[str, Any]] = []
    for s in sessions:
        sid = str(s["session_upload"])
        res = abandonner_session(session, session_upload=sid)
        total_pieces += int(res["pieces_supprimees"])
        total_prop += int(res["propositions_supprimees"])
        details.append(res)
    return {
        "dry_run": False,
        "ttl_heures": int(age.total_seconds() // 3600),
        "sessions_purgées": len(details),
        "pieces_supprimees": total_pieces,
        "propositions_supprimees": total_prop,
        "details": details,
    }
