"""Routes moteur : lancer une execution."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.moteur.service import ErreurMoteur, executer_mission
from backend.plateforme.dependances import UtilisateurDep, session_abonne
from backend.plateforme.rbac import exiger_capacite

router = APIRouter(prefix="/api/v1", tags=["moteur"])


class ExecuterIn(BaseModel):
    reponses: dict[str, Any] = Field(default_factory=dict)


class ConclusionOut(BaseModel):
    regle_version_id: int
    regle_id: str
    declenchee: bool
    montant: Decimal | None
    sens: str | None
    niveau_risque: str
    detail: str | None = None
    inevaluable: bool = False
    statut_brouillon: str | None = None


@router.post("/missions/{mission_id}/executer", response_model=list[ConclusionOut])
def api_executer(
    mission_id: int,
    corps: ExecuterIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[ConclusionOut]:
    from sqlalchemy import text

    from backend.moteur.calcul import statut_brouillon_conclusion
    from backend.plateforme.contexte import contexte_tenant

    exiger_capacite(utilisateur, "executer_mission")
    try:
        conclusions = executer_mission(
            session,
            utilisateur.tenant_id,
            mission_id,
            acteur=utilisateur.email,
            reponses=corps.reponses,
        )
    except ErreurMoteur as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    seuil = None
    with contexte_tenant(session, utilisateur.tenant_id):
        seuil_brut = session.execute(
            text("SELECT seuil_signification FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if seuil_brut is not None:
            seuil = Decimal(str(seuil_brut))

    return [
        ConclusionOut(
            regle_version_id=c.regle_version_id,
            regle_id=c.regle_id,
            declenchee=c.declenchee,
            montant=c.montant,
            sens=c.sens,
            niveau_risque=c.niveau_risque,
            detail=c.detail,
            inevaluable=c.inevaluable,
            statut_brouillon=statut_brouillon_conclusion(c, seuil),
        )
        for c in conclusions
    ]
