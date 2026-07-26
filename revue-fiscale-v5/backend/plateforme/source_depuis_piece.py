"""Pont Data Room → mission : une pièce tabulaire du coffre client alimente
la source active (solde_compte) via le pipeline d'import existant."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.abonne.formats_piece import detecter_format_tabulaire
from backend.abonne.pieces_contribuable_service import piece_par_id
from backend.plateforme.contexte import contexte_tenant
from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.modeles import DesigneSourceActiveOut
from backend.socle.pieces_service import designer_source_active
from backend.socle.stockage_pieces import chemin_absolu

_EXTENSIONS_CANDIDATES = {".csv", ".txt", ".fec", ".xlsx"}


class ErreurSourceDepuisPiece(Exception):
    """Échec métier du pont Data Room → source de mission."""


def _format_piece_stockee(nom_fichier: str, chemin_stockage: str) -> str | None:
    if Path(nom_fichier or "").suffix.lower() not in _EXTENSIONS_CANDIDATES:
        return None
    try:
        with open(chemin_absolu(chemin_stockage), "rb") as f:
            entete = f.read(65536)
    except OSError:
        return None
    return detecter_format_tabulaire(nom_fichier, entete)


def lister_pieces_tabulaires(
    session: Session, tenant_id: int, contribuable_id: int
) -> list[dict[str, Any]]:
    """Pièces du Data Room dont le format détecté est fec/csv/xlsx."""
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT 1 FROM contribuable WHERE id = :c"),
            {"c": contribuable_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurSourceDepuisPiece(
                f"contribuable {contribuable_id} introuvable"
            )
        rows = session.execute(
            text(
                "SELECT id, nom_fichier, chemin_stockage, taille_octets, "
                "cree_le FROM piece_contribuable "
                "WHERE contribuable_id = :c ORDER BY cree_le DESC, id DESC"
            ),
            {"c": contribuable_id},
        ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        fmt = _format_piece_stockee(
            str(r["nom_fichier"]), str(r["chemin_stockage"])
        )
        if fmt is None:
            continue
        out.append(
            {
                "id": int(r["id"]),
                "nom_fichier": str(r["nom_fichier"]),
                "format": fmt,
                "taille_octets": int(r["taille_octets"] or 0),
                "cree_le": r["cree_le"].isoformat()
                if r["cree_le"] is not None
                else None,
            }
        )
    return out


def importer_source_depuis_piece(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    piece_id: int,
    type_piece: str | None = None,
    confirmer: bool = False,
) -> tuple[dict[str, Any], DesigneSourceActiveOut]:
    """Lit la pièce du Data Room et la passe au MÊME pipeline que l'upload
    direct (designer_source_active → lecteurs FEC/CSV/XLSX → solde_compte)."""
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text("SELECT id, contribuable_id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurSourceDepuisPiece(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        piece = piece_par_id(session, piece_id)
    if piece is None or piece.get("contribuable_id") is None:
        raise ErreurSourceDepuisPiece(
            f"pièce {piece_id} introuvable au Data Room"
        )
    if int(piece["contribuable_id"]) != int(mission["contribuable_id"]):
        raise ErreurSourceDepuisPiece(
            "Cette pièce appartient à un autre client que celui de la mission."
        )
    try:
        brut = chemin_absolu(str(piece["chemin_stockage"])).read_bytes()
    except OSError as e:
        raise ErreurSourceDepuisPiece(
            f"Contenu de la pièce « {piece['nom_fichier']} » illisible "
            "(fichier stocké absent ou corrompu)."
        ) from e
    fmt = detecter_format_tabulaire(str(piece["nom_fichier"]), brut)
    if fmt is None:
        raise ErreurSourceDepuisPiece(
            f"La pièce « {piece['nom_fichier']} » n'est pas un fichier "
            "comptable tabulaire (FEC, CSV ou XLSX)."
        )
    tp = (type_piece or "").strip() or ("fec" if fmt == "fec" else "balance")
    if fmt == "xlsx" and tp != "balance":
        raise ErreurSourceDepuisPiece(
            "Classeur Excel pris en charge uniquement comme Balance — "
            "convertissez-le en CSV ou choisissez la source Balance."
        )
    try:
        out = designer_source_active(
            session,
            tenant_id,
            mission_id,
            type_piece=tp,
            nom_fichier=str(piece["nom_fichier"]),
            contenu=brut,
            content_type=piece.get("content_type"),
            confirmer=confirmer,
        )
    except UnicodeDecodeError as e:
        raise ErreurLectureBalance(
            f"Contenu de la pièce « {piece['nom_fichier']} » illisible — "
            "encodage non pris en charge (UTF-8 attendu)."
        ) from e
    return piece, out
