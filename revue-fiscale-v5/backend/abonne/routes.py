"""Routes espace abonne et portail client."""
from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.abonne.abonnement import (
    creer_demande_palier,
    lire_compte,
    patcher_compte,
    resume_abonnement,
)
from backend.abonne.extraction_identite import (
    ErreurExtractionIdentite,
    marquer_proposition_appliquee,
    proposer_identite,
    verifier_conformite,
)
from backend.abonne.facturation import (
    instructions_virement,
    lire_facture_tenant,
    lister_factures_tenant,
    pdf_facture_tenant,
    signaler_paiement,
)
from backend.abonne.paystack import (
    ErreurPaystack,
    initialiser_paiement,
)
from backend.abonne.paystack import (
    config_publique as paystack_config_publique,
)
from backend.abonne.pieces_contribuable_service import (
    TYPES_PIECE_CONTRIBUABLE,
    ErreurPieceContribuable,
    abandonner_session,
    deposer_piece,
    lire_contenu_piece,
    lister_pieces,
    lister_propositions,
    modifier_type_piece,
    purger_orphelines,
    rattacher_session,
    retirer_piece,
    ttl_session_heures,
)
from backend.abonne.service import (
    ErreurAbonne,
    ErreurDoublonContribuable,
    accepter_invitation,
    creer_invitation,
    creer_lien_acces,
    lire_contribuable,
    lister_contribuables,
    lister_invitations,
    lister_missions,
    lister_utilisateurs,
    modifier_role_utilisateur,
    patcher_contribuable,
    resoudre_lien_client,
    revoquer_invitation,
)
from backend.plateforme.dependances import SessionDep, UtilisateurDep, session_abonne
from backend.plateforme.quotas import lire_quota_periode
from backend.plateforme.rbac import exiger_capacite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["abonne"])
router_client = APIRouter(prefix="/api/v1/client", tags=["portail-client"])

# ─── Upload pièces : plafond taille + whitelist formats (magic bytes) ─────

# Plafond configurable par fichier uploadé (25 Mo).
TAILLE_MAX_PIECE_OCTETS = 25 * 1024 * 1024

MESSAGE_FICHIER_TROP_VOLUMINEUX = "Fichier trop volumineux (max 25 Mo)."
MESSAGE_FORMAT_NON_SUPPORTE = (
    "Format non pris en charge : PDF ou image (PNG/JPEG) uniquement."
)

# Signatures binaires acceptées (whitelist stricte).
_MAGIC_FORMATS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
)
_FORMATS_PAR_EXTENSION: dict[str, str] = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}
_FORMATS_PAR_CONTENT_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/webp": "webp",
}


def _format_reel_piece(brut: bytes) -> str | None:
    """Format détecté depuis les magic bytes — None si hors whitelist."""
    for magic, fmt in _MAGIC_FORMATS:
        if brut.startswith(magic):
            return fmt
    # WEBP : conteneur RIFF avec tag WEBP à l'offset 8
    if brut[:4] == b"RIFF" and brut[8:12] == b"WEBP":
        return "webp"
    return None


def _verifier_format_piece(
    nom_fichier: str, content_type: str | None, brut: bytes
) -> None:
    """Refuse tout contenu hors whitelist ou incohérent avec nom/content-type."""
    fmt = _format_reel_piece(brut)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MESSAGE_FORMAT_NON_SUPPORTE,
        )
    ext = Path(nom_fichier or "").suffix.lower()
    if ext:
        attendu = _FORMATS_PAR_EXTENSION.get(ext)
        if attendu is None or attendu != fmt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=MESSAGE_FORMAT_NON_SUPPORTE,
            )
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct and ct != "application/octet-stream":
        attendu_ct = _FORMATS_PAR_CONTENT_TYPE.get(ct)
        if attendu_ct is None or attendu_ct != fmt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=MESSAGE_FORMAT_NON_SUPPORTE,
            )


class ContribuablePatchIn(BaseModel):
    denomination: str | None = Field(default=None, min_length=1, max_length=200)
    ncc: str | None = None
    rccm: str | None = None
    forme: Literal["pm", "pp"] | None = None
    dfe: str | None = None
    regime_fiscal: str | None = None
    forme_juridique: str | None = None
    siege_social: str | None = None
    commune: str | None = None
    centre_impots: str | None = None
    capital_social: float | None = None
    mois_cloture: int | None = Field(default=None, ge=1, le=12)
    activite_principale: str | None = None
    date_immatriculation: str | None = None


@router.get("/contribuables")
def api_lister_contribuables(
    _utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    return lister_contribuables(session)


@router.get("/contribuables/{contribuable_id}")
def api_lire_contribuable(
    contribuable_id: int,
    _utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    try:
        fiche = lire_contribuable(session, contribuable_id)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    missions = lister_missions(session, contribuable_id=contribuable_id)
    return {**fiche, "missions": missions, "nb_missions": len(missions)}


@router.patch("/contribuables/{contribuable_id}")
def api_patch_contribuable(
    contribuable_id: int,
    corps: ContribuablePatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return patcher_contribuable(
            session,
            contribuable_id,
            denomination=corps.denomination,
            ncc=corps.ncc,
            rccm=corps.rccm,
            forme=corps.forme,
            dfe=corps.dfe,
            regime_fiscal=corps.regime_fiscal,
            forme_juridique=corps.forme_juridique,
            siege_social=corps.siege_social,
            commune=corps.commune,
            centre_impots=corps.centre_impots,
            capital_social=corps.capital_social,
            mois_cloture=corps.mois_cloture,
            activite_principale=corps.activite_principale,
            date_immatriculation=corps.date_immatriculation,
        )
    except ErreurDoublonContribuable as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# ─── Pièces contribuable + extraction IA (brouillon) ─────────────────────


class RattacherPiecesIn(BaseModel):
    session_upload: str = Field(min_length=8, max_length=80)
    contribuable_id: int = Field(ge=1)


class ProposerIdentiteIn(BaseModel):
    piece_ids: list[int] | None = None
    session_upload: str | None = None
    contribuable_id: int | None = None


class VerifierConformiteIn(BaseModel):
    champs: dict[str, Any]
    piece_ids: list[int] | None = None
    session_upload: str | None = None
    contribuable_id: int | None = None


class AppliquerPropositionIn(BaseModel):
    """Marque le brouillon comme appliqué — n'écrit pas dans contribuable."""

    proposition_id: int = Field(ge=1)


class AbandonnerSessionIn(BaseModel):
    session_upload: str = Field(min_length=8, max_length=80)


class PurgerOrphelinesIn(BaseModel):
    """Purge TTL des sessions upload sans fiche (tenant courant uniquement)."""

    dry_run: bool = False
    ttl_heures: int | None = Field(default=None, ge=1, le=24 * 30)


@router.get("/pieces-contribuable")
def api_lister_pieces_contribuable(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    contribuable_id: int | None = Query(default=None, ge=1),
    session_upload: str | None = Query(default=None, min_length=8, max_length=80),
) -> list[dict]:
    exiger_capacite(utilisateur, "lire")
    try:
        return lister_pieces(
            session,
            contribuable_id=contribuable_id,
            session_upload=session_upload,
        )
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.get("/pieces-contribuable/propositions")
def api_lister_propositions_identite(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    contribuable_id: int | None = Query(default=None, ge=1),
    session_upload: str | None = Query(default=None, min_length=8, max_length=80),
    limite: int = Query(default=20, ge=1, le=50),
) -> dict:
    """Historique des brouillons IA — lecture seule, jamais appliqué au moteur."""
    exiger_capacite(utilisateur, "lire")
    try:
        items = lister_propositions(
            session,
            contribuable_id=contribuable_id,
            session_upload=session_upload,
            limite=limite,
        )
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return {"items": items, "ttl_session_heures": ttl_session_heures()}


class ModifierTypePieceIn(BaseModel):
    """Correction manuelle du type détecté — humain valide."""

    type_piece: str = Field(min_length=2, max_length=20)


@router.post("/pieces-contribuable", status_code=status.HTTP_201_CREATED)
async def api_deposer_piece_contribuable(
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    type_piece: str = Query("auto"),
    contribuable_id: int | None = Query(default=None, ge=1),
    session_upload: str | None = Query(default=None, min_length=8, max_length=80),
) -> dict:
    """Upload multipart (champ fichier). Type détecté auto si auto/autre/vide.

    Avant création : session_upload obligatoire. L'humain peut corriger le type
    via PATCH …/type.
    """
    exiger_capacite(utilisateur, "ecrire_contribuable")
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier multipart (champ fichier)",
        )
    form = await request.form()
    tp = str(form.get("type_piece") or type_piece).strip().lower() or "auto"
    # auto = détection ; autre/types connus = ok ; sinon refuse
    if tp not in TYPES_PIECE_CONTRIBUABLE and tp != "auto":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type_piece invalide : {tp}",
        )
    cid_raw = form.get("contribuable_id")
    sid_raw = form.get("session_upload")
    cid = contribuable_id
    if cid is None and cid_raw not in (None, ""):
        try:
            cid = int(str(cid_raw))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contribuable_id invalide",
            ) from e
    sid = session_upload or (
        str(sid_raw).strip() if sid_raw not in (None, "") else None
    )
    fichier = form.get("fichier")
    if not isinstance(fichier, StarletteUploadFile) or not fichier.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier (champ fichier)",
        )
    brut = await fichier.read()
    if len(brut) > TAILLE_MAX_PIECE_OCTETS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=MESSAGE_FICHIER_TROP_VOLUMINEUX,
        )
    _verifier_format_piece(fichier.filename, fichier.content_type, brut)
    # forcer_type=1 : conserve la saisie manuelle même si « autre »
    forcer = str(form.get("forcer_type") or "").strip().lower() in {
        "1",
        "true",
        "oui",
        "yes",
    }
    try:
        piece = deposer_piece(
            session,
            utilisateur.tenant_id,
            type_piece=tp if tp != "auto" else "autre",
            nom_fichier=fichier.filename,
            contenu=brut,
            content_type=fichier.content_type,
            contribuable_id=cid,
            session_upload=sid,
            auto_detecter_type=not forcer,
            autoriser_vision_classif=True,
        )
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    if piece.get("contribuable_id") is not None:
        from backend.moteur.journal import append_journal
        from backend.plateforme.memoire_client import alimenter_memoire

        contribuable_ref = int(piece["contribuable_id"])
        try:
            with session.begin_nested():
                append_journal(
                    session,
                    tenant_id=utilisateur.tenant_id,
                    mission_id=None,
                    acteur=utilisateur.email,
                    action="depot_piece_contribuable",
                    charge_utile={
                        "contribuable_id": contribuable_ref,
                        "piece_id": piece["id"],
                        "type_piece": piece["type_piece"],
                        "nom_fichier": piece["nom_fichier"],
                    },
                )
        except Exception:
            logger.warning(
                "journalisation dépôt pièce ignorée (pièce %s)",
                piece["id"],
                exc_info=True,
            )
        alimenter_memoire(
            session,
            utilisateur.tenant_id,
            contribuable_ref,
            type_entree="fait",
            contenu=(
                f"Pièce « {piece['nom_fichier']} » déposée au coffre "
                f"documentaire (type : {piece['type_piece']})."
            ),
            source_type="extraction",
            source_ref=f"piece:{piece['id']}",
        )
    return piece


@router.patch("/pieces-contribuable/{piece_id}/type")
def api_modifier_type_piece(
    piece_id: int,
    corps: ModifierTypePieceIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Corrige le type détecté (IA propose, humain valide)."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return modifier_type_piece(session, piece_id, corps.type_piece)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.delete("/pieces-contribuable/{piece_id}")
def api_retirer_piece_contribuable(
    piece_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return retirer_piece(session, piece_id)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


def _content_disposition_inline(nom_fichier: str) -> str:
    """Disposition inline pour aperçu navigateur (PDF / image)."""
    nom = (nom_fichier or "piece").replace("\r", "").replace("\n", "").strip()
    if not nom:
        nom = "piece"
    ascii_safe = re.sub(r"[^\x20-\x7E]", "_", nom).replace('"', "'")
    return (
        f'inline; filename="{ascii_safe}"; '
        f"filename*=UTF-8''{quote(nom, safe='')}"
    )


def _media_type_piece(content_type: str | None, nom_fichier: str) -> str:
    ct = (content_type or "").strip().split(";")[0].strip().lower()
    if ct and ct != "application/octet-stream":
        return ct
    guess, _ = mimetypes.guess_type(nom_fichier or "")
    return guess or "application/octet-stream"


@router.get("/pieces-contribuable/{piece_id}/contenu")
def api_contenu_piece_contribuable(
    piece_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Stream le fichier (RLS tenant) — Content-Disposition inline pour aperçu."""
    exiger_capacite(utilisateur, "lire")
    try:
        piece, brut = lire_contenu_piece(session, piece_id)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    except (OSError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="fichier pièce introuvable",
        ) from e
    nom = str(piece.get("nom_fichier") or "piece")
    media = _media_type_piece(
        str(piece.get("content_type") or "") or None, nom
    )
    return Response(
        content=brut,
        media_type=media,
        headers={
            "Content-Disposition": _content_disposition_inline(nom),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/pieces-contribuable/rattacher")
def api_rattacher_pieces(
    corps: RattacherPiecesIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    """Après POST /contribuables : lie la session d'upload au client créé."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return rattacher_session(
            session,
            session_upload=corps.session_upload,
            contribuable_id=corps.contribuable_id,
        )
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.post("/pieces-contribuable/proposer-identite")
def api_proposer_identite(
    corps: ProposerIdentiteIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """IA propose un brouillon — jamais de création silencieuse du contribuable."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return proposer_identite(
            session,
            utilisateur.tenant_id,
            piece_ids=corps.piece_ids,
            session_upload=corps.session_upload,
            contribuable_id=corps.contribuable_id,
        )
    except ErreurExtractionIdentite as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.post("/pieces-contribuable/verifier-conformite")
def api_verifier_conformite(
    corps: VerifierConformiteIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Compare saisie ↔ pièces. Résultat informatif, non bloquant moteur."""
    exiger_capacite(utilisateur, "lire")
    try:
        return verifier_conformite(
            session,
            utilisateur.tenant_id,
            champs_saisis=corps.champs,
            piece_ids=corps.piece_ids,
            session_upload=corps.session_upload,
            contribuable_id=corps.contribuable_id,
        )
    except ErreurExtractionIdentite as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.post("/pieces-contribuable/marquer-applique")
def api_marquer_proposition_appliquee(
    corps: AppliquerPropositionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Trace UI « Appliquer au formulaire » — n'écrit pas la fiche."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        marquer_proposition_appliquee(session, corps.proposition_id)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    try:
        from sqlalchemy import text as sql_text

        from backend.plateforme.memoire_client import alimenter_memoire

        with session.begin_nested():
            prop = session.execute(
                sql_text(
                    "SELECT contribuable_id, champs_proposes "
                    "FROM proposition_identite WHERE id = :id"
                ),
                {"id": corps.proposition_id},
            ).mappings().one_or_none()
        if prop is not None and prop["contribuable_id"] is not None:
            champs = sorted((prop["champs_proposes"] or {}).keys())
            alimenter_memoire(
                session,
                utilisateur.tenant_id,
                int(prop["contribuable_id"]),
                type_entree="fait",
                contenu=(
                    "Identité extraite appliquée au formulaire — champs : "
                    + (", ".join(champs) if champs else "aucun")
                    + "."
                ),
                source_type="extraction",
                source_ref=f"proposition:{corps.proposition_id}",
            )
    except Exception:
        logger.warning(
            "alimentation mémoire client ignorée (proposition %s)",
            corps.proposition_id,
            exc_info=True,
        )
    return {"ok": True, "proposition_id": corps.proposition_id, "statut": "applique"}


@router.post("/pieces-contribuable/abandonner-session")
def api_abandonner_session_upload(
    corps: AbandonnerSessionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Supprime immédiatement les pièces orphelines d'une session d'upload."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        return abandonner_session(session, session_upload=corps.session_upload)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.post("/pieces-contribuable/purger-orphelines")
def api_purger_sessions_orphelines(
    corps: PurgerOrphelinesIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Purge TTL des uploads sans fiche — isolé au tenant (SET LOCAL)."""
    exiger_capacite(utilisateur, "ecrire_contribuable")
    from datetime import timedelta

    age = (
        timedelta(hours=corps.ttl_heures)
        if corps.ttl_heures is not None
        else None
    )
    try:
        return purger_orphelines(session, plus_vieux_que=age, dry_run=corps.dry_run)
    except ErreurPieceContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.get("/missions")
def api_lister_missions(
    _utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    statut: str | None = Query(default=None),
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    contribuable_id: int | None = Query(default=None, ge=1),
) -> list[dict]:
    return lister_missions(
        session,
        statut=statut,
        exercice=exercice,
        contribuable_id=contribuable_id,
    )


@router.get("/quota")
def api_quota_resume(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    resume = lire_quota_periode(session, utilisateur.tenant_id)
    if resume is None:
        return {
            "periode": None,
            "missions_incluses": 0,
            "missions_utilisees": 0,
            "ratio": 0.0,
            "alerte_80": False,
            "bloque": True,
        }
    return resume.vers_dict()


# ─── Facturation abonné (lecture + signalement, jamais marquer_payee) ─


@router.get("/factures")
def api_abonne_lister_factures(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    exiger_capacite(utilisateur, "lire")
    ps = paystack_config_publique()
    return {
        "factures": lister_factures_tenant(session, utilisateur.tenant_id),
        "virement": instructions_virement(session),
        "paystack": {"disponible": bool(ps["disponible"])},
    }


@router.get("/factures/paystack-config")
def api_abonne_paystack_config(
    utilisateur: UtilisateurDep,
) -> dict[str, Any]:
    """Clé publique + disponibilité — jamais la secret key."""
    exiger_capacite(utilisateur, "lire")
    return paystack_config_publique()


@router.get("/factures/{facture_id}")
def api_abonne_lire_facture(
    facture_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    exiger_capacite(utilisateur, "lire")
    try:
        facture = lire_facture_tenant(session, utilisateur.tenant_id, facture_id)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return {
        "facture": facture,
        "virement": instructions_virement(session),
        "paystack": {"disponible": bool(paystack_config_publique()["disponible"])},
    }


@router.get("/factures/{facture_id}/pdf")
def api_abonne_facture_pdf(
    facture_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    exiger_capacite(utilisateur, "lire")
    try:
        pdf, numero = pdf_facture_tenant(session, utilisateur.tenant_id, facture_id)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="facture-{numero}.pdf"'
        },
    )


class SignalerPaiementIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/factures/{facture_id}/payer-paystack", status_code=status.HTTP_201_CREATED)
def api_abonne_payer_paystack(
    facture_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    callback_url: str | None = Query(default=None, max_length=2000),
) -> dict[str, Any]:
    """Initialise un checkout Paystack — n'appelle JAMAIS marquer_payee."""
    exiger_capacite(utilisateur, "gerer_abonnement")
    try:
        return initialiser_paiement(
            session,
            tenant_id=utilisateur.tenant_id,
            facture_id=facture_id,
            email=utilisateur.email,
            callback_url=callback_url,
        )
    except ErreurPaystack as e:
        msg = str(e)
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "indisponible" in msg.lower() or "absent" in msg.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=msg) from e
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/factures/{facture_id}/signaler-paiement", status_code=status.HTTP_201_CREATED)
def api_abonne_signaler_paiement(
    facture_id: int,
    corps: SignalerPaiementIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    """Rapprochement demandé — n'appelle JAMAIS marquer_payee."""
    exiger_capacite(utilisateur, "gerer_abonnement")
    try:
        return signaler_paiement(
            session,
            tenant_id=utilisateur.tenant_id,
            facture_id=facture_id,
            cree_par=utilisateur.utilisateur_id,
            note=corps.note,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# ─── Compte cabinet + abonnement / demande palier ─────────────────


@router.get("/compte")
def api_lire_compte(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    exiger_capacite(utilisateur, "lire")
    try:
        return lire_compte(
            session,
            tenant_id=utilisateur.tenant_id,
            utilisateur_id=utilisateur.utilisateur_id,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class ComptePatchIn(BaseModel):
    denomination: str | None = Field(default=None, min_length=1, max_length=200)
    telephone: str | None = Field(default=None, max_length=40)
    ncc: str | None = Field(default=None, max_length=64)
    rccm: str | None = Field(default=None, max_length=80)
    dfe: str | None = Field(default=None, max_length=80)
    forme_juridique: str | None = Field(default=None, max_length=40)
    siege_social: str | None = Field(default=None, max_length=500)
    commune: str | None = Field(default=None, max_length=120)
    centre_impots: str | None = Field(default=None, max_length=200)
    capital_social: float | None = None


@router.patch("/compte")
def api_patch_compte(
    corps: ComptePatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    exiger_capacite(utilisateur, "gerer_abonnement")
    champs = corps.model_dump(exclude_unset=True)
    try:
        return patcher_compte(
            session,
            tenant_id=utilisateur.tenant_id,
            utilisateur_id=utilisateur.utilisateur_id,
            **champs,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/abonnement")
def api_resume_abonnement(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    exiger_capacite(utilisateur, "lire")
    try:
        return resume_abonnement(session, utilisateur.tenant_id)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class DemandePalierIn(BaseModel):
    palier_cible: Literal["essentiel", "standard", "premium", "souverain"]
    motif: str | None = Field(default=None, max_length=2000)


@router.post("/abonnement/demande-palier", status_code=status.HTTP_201_CREATED)
def api_demande_palier(
    corps: DemandePalierIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    """Demande file staff — ne mute PAS le palier (patcher_tenant staff only)."""
    exiger_capacite(utilisateur, "gerer_abonnement")
    try:
        return creer_demande_palier(
            session,
            tenant_id=utilisateur.tenant_id,
            cree_par=utilisateur.utilisateur_id,
            palier_cible=corps.palier_cible,
            motif=corps.motif,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


class InvitationIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: Literal["admin", "reviseur", "lecteur"] = "lecteur"


class AccepterInvitationIn(BaseModel):
    token: str = Field(min_length=10)
    mot_de_passe: str = Field(min_length=8, max_length=200)


@router.get("/utilisateurs")
def api_lister_utilisateurs(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    exiger_capacite(utilisateur, "gerer_equipe")
    return lister_utilisateurs(session)


@router.get("/collaborateurs")
def api_lister_collaborateurs(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    """Liste allégée (id, email, actif) pour assignation de tâches.

    Accessible aux rôles qui peuvent créer / instruire une mission —
    distinct de gerer_equipe (admin seul).
    """
    exiger_capacite(utilisateur, "creer_mission")
    rows = lister_utilisateurs(session)
    return [
        {"id": int(r["id"]), "email": str(r["email"]), "actif": bool(r["actif"])}
        for r in rows
        if r.get("actif") is not False
    ]


class UtilisateurRoleIn(BaseModel):
    role: Literal["admin", "reviseur", "lecteur"]


@router.patch("/utilisateurs/{utilisateur_id}")
def api_modifier_role_utilisateur(
    utilisateur_id: int,
    corps: UtilisateurRoleIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "gerer_equipe")
    try:
        return modifier_role_utilisateur(
            session,
            utilisateur_id=utilisateur_id,
            role=corps.role,
            acteur_id=utilisateur.utilisateur_id,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/invitations")
def api_lister_invitations(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    exiger_capacite(utilisateur, "inviter")
    return lister_invitations(session)


@router.post("/invitations/{invitation_id}/revoquer")
def api_revoquer_invitation(
    invitation_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "inviter")
    try:
        return revoquer_invitation(session, invitation_id)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def api_creer_invitation(
    corps: InvitationIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "inviter")
    try:
        return creer_invitation(
            session,
            utilisateur.tenant_id,
            email=corps.email,
            role=corps.role,
            invitee_par=utilisateur.utilisateur_id,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/email-outbox")
def api_email_outbox_abonne(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    limit: int = 30,
) -> dict:
    """Outbox du cabinet — emails simulés / échecs Resend visibles sans clé."""
    exiger_capacite(utilisateur, "inviter")
    from backend.plateforme.email_outbox import lister_outbox, statut_resend

    resend = statut_resend()
    lignes = lister_outbox(
        session, tenant_id=utilisateur.tenant_id, limit=limit
    )
    return {
        "resend": resend,
        "total": len(lignes),
        "lignes": lignes,
        "note_ui": (
            "Sans RESEND_API_KEY : consultez ici le dernier email simulé "
            "(statut simule_dev) et utilisez le jeton affiché à la création."
        ),
    }


@router.post("/invitations/accepter")
def api_accepter_invitation(corps: AccepterInvitationIn, session: SessionDep) -> dict:
    """Acceptation publique (token magique) — pas de JWT tenant requis."""
    try:
        return accepter_invitation(
            session, token=corps.token, mot_de_passe=corps.mot_de_passe
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


class LienAccesIn(BaseModel):
    mission_id: int
    email_contact: str | None = None
    ttl_jours: int = Field(default=30, ge=1, le=90)


@router.post("/liens-acces", status_code=status.HTTP_201_CREATED)
def api_creer_lien(
    corps: LienAccesIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    exiger_capacite(utilisateur, "lien_client")
    try:
        return creer_lien_acces(
            session,
            utilisateur.tenant_id,
            mission_id=corps.mission_id,
            email_contact=corps.email_contact,
            cree_par=utilisateur.utilisateur_id,
            ttl_jours=corps.ttl_jours,
        )
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router_client.get("/{token}/restitution")
def api_client_restitution(token: str, session: SessionDep) -> dict:
    """Restitution lecture seule via token magique — isolation par lien.

    Si la mission n'a pas encore d'execution : 200 + empty state (pas 404 brut).
    Token invalide / expire : 404.
    """
    try:
        lien = resoudre_lien_client(session, token)
    except ErreurAbonne as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
    from backend.restitution.service import (
        ErreurRestitution,
        produire_restitution,
        restitution_vers_dict,
    )

    tenant_id = int(lien["tenant_id"])
    mission_id = int(lien["mission_id"])
    try:
        with contexte_tenant(session, tenant_id):
            r = produire_restitution(session, tenant_id, mission_id)
    except ErreurRestitution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    finally:
        effacer_contexte_tenant(session)

    if r.execution_id is None:
        return {
            "lecture_seule": True,
            "mission_id": mission_id,
            "email_contact": lien.get("email_contact"),
            "sans_restitution": True,
            "message": (
                "Cette mission n'a pas encore été exécutée. "
                "Aucune restitution n'est disponible pour le moment. "
                "Contactez votre cabinet."
            ),
            "restitution": None,
        }

    return {
        "lecture_seule": True,
        "mission_id": mission_id,
        "email_contact": lien.get("email_contact"),
        "sans_restitution": False,
        "restitution": restitution_vers_dict(r),
    }
