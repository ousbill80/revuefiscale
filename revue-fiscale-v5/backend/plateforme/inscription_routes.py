"""Routes inscription OTP + finalisation + onboarding."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import config
from backend.plateforme.auth import emettre_jeton
from backend.plateforme.dependances import SessionDep, UtilisateurDep, session_abonne
from backend.plateforme.email_otp import (
    ErreurOtp,
    consommer_jeton_inscription,
    demarrer_otp,
    supprimer_pending,
    verifier_otp,
)
from backend.plateforme.onboarding import (
    ErreurOnboarding,
    lire_onboarding,
    marquer_etape,
)
from backend.plateforme.provisionnement import (
    ErreurProvisionnement,
    provisionner_cabinet,
)
from backend.plateforme.telephone import ErreurTelephone, normaliser_e164

router_inscription = APIRouter(prefix="/api/v1/inscription", tags=["inscription"])
router_onboarding = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


class DemarrerIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class DemarrerOut(BaseModel):
    email: str
    expire_le: str
    renvoye: bool
    otp_debug: str | None = None


class VerifierIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    code: str = Field(min_length=6, max_length=12)


class VerifierOut(BaseModel):
    email: str
    jeton_inscription: str


class FinaliserIn(BaseModel):
    jeton_inscription: str = Field(min_length=16, max_length=200)
    denomination: str = Field(min_length=1, max_length=200)
    type_tenant: Literal["cabinet", "entreprise"] = "cabinet"
    palier: Literal["essentiel", "standard", "premium", "souverain"] = "standard"
    mot_de_passe: str = Field(min_length=8, max_length=200)
    telephone: str = Field(min_length=6, max_length=32)
    creer_demo: bool = False


class FinaliserOut(BaseModel):
    tenant_id: int
    utilisateur_id: int
    email_admin: str
    palier: str
    jeton: str
    tenant_denomination: str
    telephone: str


@router_inscription.post("/demarrer", response_model=DemarrerOut)
def api_inscription_demarrer(corps: DemarrerIn, session: SessionDep) -> DemarrerOut:
    if not config.provisionnement_public_autorise():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inscription publique désactivée.",
        )
    if config.env != "dev" and not config.resend_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service email non configuré (RESEND_API_KEY).",
        )
    try:
        r = demarrer_otp(session, corps.email)
    except ErreurOtp as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return DemarrerOut(
        email=r.email,
        expire_le=r.expire_le.isoformat(),
        renvoye=r.renvoye,
        otp_debug=r.otp_debug,
    )


@router_inscription.post("/verifier-otp", response_model=VerifierOut)
def api_inscription_verifier(corps: VerifierIn, session: SessionDep) -> VerifierOut:
    if not config.provisionnement_public_autorise():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inscription publique désactivée.",
        )
    try:
        r = verifier_otp(session, corps.email, corps.code)
    except ErreurOtp as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return VerifierOut(email=r.email, jeton_inscription=r.jeton_inscription)


@router_inscription.post("/finaliser", response_model=FinaliserOut)
def api_inscription_finaliser(corps: FinaliserIn, session: SessionDep) -> FinaliserOut:
    if not config.provisionnement_public_autorise():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inscription publique désactivée.",
        )
    try:
        email = consommer_jeton_inscription(session, corps.jeton_inscription)
        tel = normaliser_e164(corps.telephone)
        r = provisionner_cabinet(
            session,
            denomination=corps.denomination,
            type_tenant=corps.type_tenant,
            palier=corps.palier,
            email_admin=email,
            mot_de_passe_admin=corps.mot_de_passe,
            creer_demo=corps.creer_demo,
            telephone=tel,
        )
        supprimer_pending(session, email)
    except (ErreurOtp, ErreurTelephone, ErreurProvisionnement) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=r.email_admin,
    )
    return FinaliserOut(
        tenant_id=r.tenant_id,
        utilisateur_id=r.utilisateur_id,
        email_admin=r.email_admin,
        palier=r.palier,
        jeton=jeton,
        tenant_denomination=corps.denomination.strip(),
        telephone=tel,
    )


@router_onboarding.get("")
def api_onboarding_lire(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    return lire_onboarding(session, utilisateur.tenant_id)


@router_onboarding.post("/etape/{etape_id}")
def api_onboarding_etape(
    etape_id: str,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    try:
        return marquer_etape(session, utilisateur.tenant_id, etape_id)
    except ErreurOnboarding as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
