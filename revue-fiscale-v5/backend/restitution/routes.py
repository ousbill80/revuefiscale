"""Routes restitution — rapport de mission + exports + audit."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.plateforme.dependances import UtilisateurDep, session_abonne
from backend.restitution.rapport_docx import rendre_rapport_docx
from backend.restitution.rapport_pdf import rendre_rapport_pdf
from backend.restitution.service import (
    ErreurRestitution,
    lire_audit,
    produire_audit,
    produire_restitution,
    restitution_vers_dict,
)

router = APIRouter(prefix="/api/v1", tags=["restitution"])


@router.get("/missions/{mission_id}/restitution")
def api_restitution(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, Any]:
    try:
        r = produire_restitution(session, utilisateur.tenant_id, mission_id)
    except ErreurRestitution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return restitution_vers_dict(r)


def _export_meta(session: Session, tenant_id: int, mission_id: int) -> dict[str, Any]:
    from sqlalchemy import text

    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, m.version_referentiel_id, "
                "c.denomination AS contribuable_denomination, c.ncc AS contribuable_ncc "
                "FROM mission m JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurRestitution(f"mission {mission_id} introuvable")
    return dict(row)


def _meta_export_complet(
    session: Session, tenant_id: int, mission_id: int, r: Any
) -> dict[str, Any]:
    """Meta export = identification restitution (périmètre) + clés fichier."""
    base = _export_meta(session, tenant_id, mission_id)
    ident = getattr(r, "identification", None) or {}
    if isinstance(ident, dict):
        return {**base, **ident}
    return base


@router.get("/missions/{mission_id}/restitution/rapport.docx")
def api_rapport_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    try:
        r = produire_restitution(session, utilisateur.tenant_id, mission_id)
        meta = _meta_export_complet(session, utilisateur.tenant_id, mission_id, r)
        audit = lire_audit(session, utilisateur.tenant_id, mission_id, limite=20)
    except ErreurRestitution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    contenu = rendre_rapport_docx(
        meta=meta,
        passage=r.passage,
        conclusions=r.conclusions,
        score=r.score_risque,
        extrait_audit=audit,
    )
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="rapport-mission-{mission_id}.docx"'
            )
        },
    )


@router.get("/missions/{mission_id}/restitution/rapport.pdf")
def api_rapport_pdf(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    try:
        r = produire_restitution(session, utilisateur.tenant_id, mission_id)
        meta = _meta_export_complet(session, utilisateur.tenant_id, mission_id, r)
        audit = lire_audit(session, utilisateur.tenant_id, mission_id, limite=20)
    except ErreurRestitution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    contenu = rendre_rapport_pdf(
        meta=meta,
        passage=r.passage,
        conclusions=r.conclusions,
        score=r.score_risque,
        extrait_audit=audit,
    )
    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="rapport-mission-{mission_id}.pdf"'
            )
        },
    )


@router.get("/missions/{mission_id}/audit")
def api_audit(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    limite: int = 50,
) -> dict[str, Any]:
    """Journal d'audit mission — lecture seule, synthèse par action."""
    try:
        return produire_audit(
            session, utilisateur.tenant_id, mission_id, limite=limite
        )
    except ErreurRestitution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
