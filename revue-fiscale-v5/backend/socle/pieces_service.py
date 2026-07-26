"""Pièces de mission — source active (solde_compte) vs annexes (traçabilité)."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.socle import depot
from backend.socle.controles_fec import controles_vraisemblance_fec
from backend.socle.erreurs import (
    ErreurFiabilisation,
    ErreurLectureBalance,
    ErreurPiece,
)
from backend.socle.lecteurs.balance import parser_balance
from backend.socle.lecteurs.balance_xlsx import parser_balance_xlsx
from backend.socle.lecteurs.etats_financiers import parser_etats_financiers
from backend.socle.lecteurs.fec import parser_fec
from backend.socle.lecteurs.grand_livre import parser_grand_livre
from backend.socle.modeles import (
    DesigneSourceActiveOut,
    PieceOut,
    RapportFiab,
)
from backend.socle.service import (
    fiabiliser_balance,
    fiabiliser_etats_financiers,
    fiabiliser_fec,
    fiabiliser_grand_livre,
)
from backend.socle.stockage_pieces import ecrire_piece, supprimer_fichier

TYPES_IMPORTABLES = frozenset(
    {"balance", "etats_financiers", "grand_livre", "fec"}
)

_journal = logging.getLogger(__name__)


def _piece_out(row: dict) -> PieceOut:
    return PieceOut.model_validate(row)


def lister_pieces_mission(
    session: Session, tenant_id: int, mission_id: int
) -> list[PieceOut]:
    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        return [_piece_out(r) for r in depot.lister_pieces(session, mission_id)]


def deposer_annexe(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    type_piece: str,
    nom_fichier: str,
    contenu: bytes,
    content_type: str | None = None,
) -> PieceOut:
    """Dépose une annexe — n'écrit jamais dans solde_compte."""
    if type_piece not in {
        "balance",
        "etats_financiers",
        "grand_livre",
        "fec",
        "autre",
    }:
        raise ErreurPiece(f"type_piece invalide : {type_piece}")
    if not contenu:
        raise ErreurPiece("fichier vide")

    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        chemin = ecrire_piece(tenant_id, mission_id, nom_fichier, contenu)
        row = depot.inserer_piece(
            session,
            tenant_id,
            mission_id,
            type_piece=type_piece,
            role="annexe",
            nom_fichier=nom_fichier,
            chemin_stockage=chemin,
            taille_octets=len(contenu),
            content_type=content_type,
        )
        session.flush()
        return _piece_out(row)


def _parser_et_fiabiliser(
    session: Session,
    tenant_id: int,
    mission_id: int,
    type_piece: str,
    nom: str | None,
    brut: bytes,
    remap: dict[str, str] | None,
) -> tuple[RapportFiab, list | None]:
    """Retourne (rapport, écritures FEC parsées ou None).

    Les écritures FEC sont renvoyées pour les contrôles de vraisemblance
    (informationnels) — jamais pour bloquer l'import.
    """
    if type_piece == "balance":
        nom_l = (nom or "").lower()
        if nom_l.endswith((".xlsx", ".xlsm")):
            lignes = parser_balance_xlsx(brut)
        else:
            # JSON (éditeur / balance.json) ou CSV/TSV.
            texte = brut.decode("utf-8-sig").lstrip()
            if texte.startswith("{") or texte.startswith("["):
                from backend.socle.modeles import BalanceJson

                try:
                    corps = BalanceJson.model_validate_json(
                        brut.decode("utf-8-sig")
                    )
                except Exception as e:
                    raise ErreurLectureBalance(
                        f"JSON balance invalide : {e}"
                    ) from e
                lignes = corps.lignes
            else:
                lignes = parser_balance(brut)
        return (
            fiabiliser_balance(
                session, tenant_id, mission_id, lignes, remap=remap
            ),
            None,
        )
    if type_piece == "etats_financiers":
        lignes = parser_etats_financiers(brut)
        return (
            fiabiliser_etats_financiers(
                session, tenant_id, mission_id, lignes, remap=remap
            ),
            None,
        )
    if type_piece == "grand_livre":
        ecritures = parser_grand_livre(brut)
        return (
            fiabiliser_grand_livre(
                session, tenant_id, mission_id, ecritures, remap=remap
            ),
            None,
        )
    if type_piece == "fec":
        ecritures = parser_fec(brut)
        return (
            fiabiliser_fec(
                session, tenant_id, mission_id, ecritures, remap=remap
            ),
            ecritures,
        )
    raise ErreurPiece(
        f"type_piece « {type_piece} » ne peut pas alimenter solde_compte"
    )


def designer_source_active(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    type_piece: str,
    nom_fichier: str,
    contenu: bytes,
    content_type: str | None = None,
    confirmer: bool = False,
    remap: dict[str, str] | None = None,
) -> DesigneSourceActiveOut:
    """Importe dans solde_compte et enregistre la pièce en source_active.

    Si une source active existe déjà, exige confirmer=True : l'ancienne
    passe en annexe (traçabilité), les soldes sont remplacés.
    """
    if type_piece not in TYPES_IMPORTABLES:
        raise ErreurPiece(
            f"type_piece « {type_piece} » non importable en source active"
        )
    if not contenu:
        raise ErreurPiece("fichier vide")

    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        precedente = depot.source_active_existante(session, mission_id)
        if precedente and not confirmer:
            raise ErreurPiece(
                "Une source active est déjà définie "
                f"(« {precedente['nom_fichier']} », {precedente['type_piece']}). "
                "Confirmez le remplacement explicite (confirmer=true) — "
                "pas de fusion multi-sources."
            )

    try:
        rapport, ecritures_fec = _parser_et_fiabiliser(
            session,
            tenant_id,
            mission_id,
            type_piece,
            nom_fichier,
            contenu,
            remap,
        )
    except ErreurLectureBalance:
        raise

    # Contrôles de vraisemblance FEC — informationnels, jamais bloquants.
    if ecritures_fec is not None:
        try:
            # SAVEPOINT : un échec ici n'invalide pas l'import en cours.
            with session.begin_nested(), contexte_tenant(session, tenant_id):
                exercice = depot.exercice_mission(session, mission_id)
                if exercice is not None:
                    controles = controles_vraisemblance_fec(
                        ecritures_fec, exercice
                    )
                    depot.inserer_controles_fec(
                        session, tenant_id, mission_id, exercice, controles
                    )
        except Exception:  # noqa: BLE001 — l'import ne doit jamais échouer ici
            _journal.warning(
                "controles vraisemblance FEC non persistés (mission %s)",
                mission_id,
                exc_info=True,
            )

    if rapport.statut != "ok":
        # Pas de bascule de pièce si l'import est refusé (soldes conservés).
        return DesigneSourceActiveOut(
            piece=None,
            rapport=rapport,
            source_precedente_degradee=False,
        )

    with contexte_tenant(session, tenant_id):
        degradee = False
        if precedente:
            depot.degrad_sources_actives_en_annexes(session, mission_id)
            degradee = True
        chemin = ecrire_piece(tenant_id, mission_id, nom_fichier, contenu)
        row = depot.inserer_piece(
            session,
            tenant_id,
            mission_id,
            type_piece=type_piece,
            role="source_active",
            nom_fichier=nom_fichier,
            chemin_stockage=chemin,
            taille_octets=len(contenu),
            content_type=content_type,
        )
        session.flush()
        return DesigneSourceActiveOut(
            piece=_piece_out(row),
            rapport=rapport,
            source_precedente_degradee=degradee,
        )


def enregistrer_source_apres_import(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    type_piece: str,
    nom_fichier: str,
    contenu: bytes,
    content_type: str | None = None,
    confirmer: bool = False,
) -> PieceOut:
    """Enregistre la métadonnée source_active après un import déjà réussi.

    N'écrit pas dans solde_compte. Utilisé par le wizard après /balance JSON.
    """
    if type_piece not in TYPES_IMPORTABLES:
        raise ErreurPiece(
            f"type_piece « {type_piece} » non importable en source active"
        )

    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        precedente = depot.source_active_existante(session, mission_id)
        if precedente and not confirmer:
            raise ErreurPiece(
                "Une source active est déjà définie. "
                "Confirmez le remplacement (confirmer=true)."
            )
        if precedente:
            depot.degrad_sources_actives_en_annexes(session, mission_id)
        chemin = ecrire_piece(tenant_id, mission_id, nom_fichier, contenu)
        row = depot.inserer_piece(
            session,
            tenant_id,
            mission_id,
            type_piece=type_piece,
            role="source_active",
            nom_fichier=nom_fichier,
            chemin_stockage=chemin,
            taille_octets=len(contenu),
            content_type=content_type,
        )
        session.flush()
        return _piece_out(row)


def retirer_annexe(
    session: Session, tenant_id: int, mission_id: int, piece_id: int
) -> PieceOut:
    """Retire une annexe (fichier + métadonnée). Refuse la source_active."""
    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(
                f"mission {mission_id} introuvable pour ce tenant"
            )
        piece = depot.piece_par_id(session, piece_id)
        if piece is None or int(piece["mission_id"]) != mission_id:
            raise ErreurPiece(f"pièce {piece_id} introuvable")
        if piece["role"] == "source_active":
            raise ErreurPiece(
                "Impossible de retirer la source active — "
                "désignez une nouvelle source (remplacement explicite)."
            )
        suppr = depot.supprimer_piece(session, piece_id)
        session.flush()
    if suppr and suppr.get("chemin_stockage"):
        supprimer_fichier(str(suppr["chemin_stockage"]))
    return _piece_out(piece)
