"""Routes socle : import balance, etats financiers, grand livre, FEC, pièces."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.plateforme.dependances import UtilisateurDep, session_abonne
from backend.plateforme.rbac import exiger_capacite
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
    BalanceJson,
    DesigneSourceActiveOut,
    EtatsFinanciersJson,
    PieceOut,
    RapportFiab,
)
from backend.socle.pieces_service import (
    deposer_annexe,
    designer_source_active,
    enregistrer_source_apres_import,
    lister_pieces_mission,
    retirer_annexe,
)
from backend.socle.service import (
    fiabiliser_balance,
    fiabiliser_etats_financiers,
    fiabiliser_fec,
    fiabiliser_grand_livre,
)

router = APIRouter(prefix="/api/v1", tags=["socle"])


def _parser_fichier_balance(nom: str | None, brut: bytes):
    nom_l = (nom or "").lower()
    if nom_l.endswith((".xlsx", ".xlsm")):
        return parser_balance_xlsx(brut)
    return parser_balance(brut)


def _remap_depuis_yaml(remap_yaml: str | None) -> dict[str, str] | None:
    if not remap_yaml:
        return None
    import yaml

    data = yaml.safe_load(remap_yaml)
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return None


async def _fichier_et_remap(request: Request) -> tuple[bytes | None, str | None, str | None]:
    """Lit multipart : (contenu, nom_fichier, remap_yaml)."""
    form = await request.form()
    remap = form.get("remap_yaml")
    remap_s = str(remap) if remap is not None else None
    fichier = form.get("fichier")
    if isinstance(fichier, StarletteUploadFile) and fichier.filename:
        brut = await fichier.read()
        return brut, fichier.filename, remap_s
    return None, None, remap_s


@router.post(
    "/missions/{mission_id}/balance",
    response_model=RapportFiab,
)
async def api_importer_balance(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> RapportFiab:
    """Importe une balance (JSON application/json ou multipart CSV/XLSX)."""
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()
    remap = None

    if "application/json" in content_type:
        try:
            corps = BalanceJson.model_validate(await request.json())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"JSON balance invalide : {e}",
            ) from e
        lignes = corps.lignes
    elif "multipart/form-data" in content_type:
        brut, nom, remap_yaml = await _fichier_et_remap(request)
        if brut is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fournir un fichier ou un corps JSON {lignes: [...]}",
            )
        try:
            lignes = _parser_fichier_balance(nom, brut)
        except ErreurLectureBalance as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            ) from e
        remap = _remap_depuis_yaml(remap_yaml)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier ou un corps JSON {lignes: [...]}",
        )

    try:
        rapport = fiabiliser_balance(
            session,
            utilisateur.tenant_id,
            mission_id,
            lignes,
            remap=remap,
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    from backend.moteur.journal import append_journal

    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="import_balance",
        charge_utile={
            "statut": rapport.statut,
            "nb_comptes": rapport.nb_comptes,
            "rapport_id": rapport.rapport_id,
            "nb_anomalies": len(rapport.anomalies or []),
        },
    )
    return rapport


@router.post(
    "/missions/{mission_id}/etats-financiers",
    response_model=RapportFiab,
)
async def api_importer_etats_financiers(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> RapportFiab:
    """Importe des etats financiers (CSV/JSON) et derive des soldes."""
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()
    remap = None

    if "application/json" in content_type:
        try:
            corps = EtatsFinanciersJson.model_validate(await request.json())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"JSON etats financiers invalide : {e}",
            ) from e
        lignes = corps.lignes
    elif "multipart/form-data" in content_type:
        brut, _nom, remap_yaml = await _fichier_et_remap(request)
        if brut is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fournir un fichier ou un corps JSON {lignes: [...]}",
            )
        try:
            lignes = parser_etats_financiers(brut)
        except ErreurLectureBalance as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            ) from e
        remap = _remap_depuis_yaml(remap_yaml)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier ou un corps JSON {lignes: [...]}",
        )

    try:
        return fiabiliser_etats_financiers(
            session,
            utilisateur.tenant_id,
            mission_id,
            lignes,
            remap=remap,
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/missions/{mission_id}/grand-livre",
    response_model=RapportFiab,
)
async def api_importer_grand_livre(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> RapportFiab:
    """Importe un grand livre CSV, agrege par compte vers solde_compte."""
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier CSV grand livre",
        )
    brut, nom, remap_yaml = await _fichier_et_remap(request)
    if brut is None or not nom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier CSV grand livre",
        )
    try:
        ecritures = parser_grand_livre(brut)
    except ErreurLectureBalance as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        return fiabiliser_grand_livre(
            session,
            utilisateur.tenant_id,
            mission_id,
            ecritures,
            remap=_remap_depuis_yaml(remap_yaml),
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/missions/{mission_id}/fec",
    response_model=RapportFiab,
)
async def api_importer_fec(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> RapportFiab:
    """Importe un FEC-like (| / tab / csv), agrege par CompteNum vers solde_compte."""
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier FEC",
        )
    brut, nom, remap_yaml = await _fichier_et_remap(request)
    if brut is None or not nom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier FEC",
        )
    try:
        ecritures = parser_fec(brut)
    except ErreurLectureBalance as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        return fiabiliser_fec(
            session,
            utilisateur.tenant_id,
            mission_id,
            ecritures,
            remap=_remap_depuis_yaml(remap_yaml),
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# ── Pièces mission : source active vs annexes ───────────────────────

_TYPES_PIECE = {
    "balance",
    "etats_financiers",
    "grand_livre",
    "fec",
    "autre",
}


def _bool_form(valeur: object | None) -> bool:
    if valeur is None:
        return False
    return str(valeur).strip().lower() in {"1", "true", "oui", "yes"}


@router.get(
    "/missions/{mission_id}/pieces",
    response_model=list[PieceOut],
)
async def api_lister_pieces(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[PieceOut]:
    """Liste les pièces du dossier (source active + annexes)."""
    exiger_capacite(utilisateur, "lire")
    try:
        return lister_pieces_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/missions/{mission_id}/pieces",
    response_model=PieceOut,
    status_code=status.HTTP_201_CREATED,
)
async def api_deposer_annexe(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    type_piece: str = Query("autre"),
) -> PieceOut:
    """Dépose une annexe (multipart). N'écrase jamais solde_compte."""
    exiger_capacite(utilisateur, "importer_balance")
    if type_piece not in _TYPES_PIECE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type_piece invalide : {type_piece}",
        )
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier multipart (champ fichier)",
        )
    form = await request.form()
    tp = str(form.get("type_piece") or type_piece)
    if tp not in _TYPES_PIECE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type_piece invalide : {tp}",
        )
    fichier = form.get("fichier")
    if not isinstance(fichier, StarletteUploadFile) or not fichier.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier (champ fichier)",
        )
    brut = await fichier.read()
    try:
        return deposer_annexe(
            session,
            utilisateur.tenant_id,
            mission_id,
            type_piece=tp,
            nom_fichier=fichier.filename,
            contenu=brut,
            content_type=fichier.content_type,
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurPiece as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post(
    "/missions/{mission_id}/source-active",
    response_model=DesigneSourceActiveOut,
)
async def api_designer_source_active(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    type_piece: str = Query("balance"),
    confirmer: bool = Query(False),
) -> DesigneSourceActiveOut:
    """Désigne la source active : importe dans solde_compte + métadonnée pièce.

    Remplacement d'une source déjà définie : confirmer=true obligatoire.
    L'ancienne source_active passe en annexe (pas de fusion silencieuse).
    """
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        if type_piece != "balance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON supporté uniquement pour type_piece=balance",
            )
        try:
            corps = BalanceJson.model_validate(await request.json())
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"JSON balance invalide : {e}",
            ) from e
        import json as _json

        brut = _json.dumps(
            {"lignes": [ligne.model_dump(mode="json") for ligne in corps.lignes]},
            ensure_ascii=False,
        ).encode("utf-8")
        nom = "balance.json"
        ct = "application/json"
        conf = confirmer
        remap = None
        tp = "balance"
    elif "multipart/form-data" in content_type:
        form = await request.form()
        tp = str(form.get("type_piece") or type_piece)
        conf = confirmer or _bool_form(form.get("confirmer"))
        remap = _remap_depuis_yaml(
            str(form["remap_yaml"]) if form.get("remap_yaml") is not None else None
        )
        fichier = form.get("fichier")
        if not isinstance(fichier, StarletteUploadFile) or not fichier.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fournir un fichier (champ fichier)",
            )
        brut = await fichier.read()
        nom = fichier.filename
        ct = fichier.content_type
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir JSON balance ou multipart fichier",
        )

    try:
        return designer_source_active(
            session,
            utilisateur.tenant_id,
            mission_id,
            type_piece=tp,
            nom_fichier=nom,
            contenu=brut,
            content_type=ct,
            confirmer=conf,
            remap=remap,
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurLectureBalance as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ErreurPiece as e:
        # 409 si source déjà définie sans confirmation
        code = (
            status.HTTP_409_CONFLICT
            if "déjà définie" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.post(
    "/missions/{mission_id}/pieces/enregistrer-source",
    response_model=PieceOut,
    status_code=status.HTTP_201_CREATED,
)
async def api_enregistrer_source_meta(
    mission_id: int,
    request: Request,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    type_piece: str = Query("balance"),
    confirmer: bool = Query(False),
) -> PieceOut:
    """Enregistre métadonnée + fichier source_active sans ré-importer les soldes.

    Utile après un import JSON déjà réussi via /balance.
    """
    exiger_capacite(utilisateur, "importer_balance")
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier multipart",
        )
    form = await request.form()
    tp = str(form.get("type_piece") or type_piece)
    conf = confirmer or _bool_form(form.get("confirmer"))
    fichier = form.get("fichier")
    if not isinstance(fichier, StarletteUploadFile) or not fichier.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fournir un fichier (champ fichier)",
        )
    brut = await fichier.read()
    try:
        return enregistrer_source_apres_import(
            session,
            utilisateur.tenant_id,
            mission_id,
            type_piece=tp,
            nom_fichier=fichier.filename,
            contenu=brut,
            content_type=fichier.content_type,
            confirmer=conf,
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurPiece as e:
        code = (
            status.HTTP_409_CONFLICT
            if "déjà définie" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.delete(
    "/missions/{mission_id}/pieces/{piece_id}",
    response_model=PieceOut,
)
async def api_retirer_annexe(
    mission_id: int,
    piece_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> PieceOut:
    """Retire une annexe. Refuse la source active."""
    exiger_capacite(utilisateur, "importer_balance")
    try:
        return retirer_annexe(
            session, utilisateur.tenant_id, mission_id, piece_id
        )
    except ErreurFiabilisation as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurPiece as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
