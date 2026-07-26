"""Routes Admin billing — /api/v1/billing/*."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.billing.auth import emettre_jeton_staff
from backend.billing.config_editeur import (
    ecrire_grille_paliers,
    ecrire_mentions_facture,
    lire_mentions_facture,
    resume_parametres_editeur,
    resume_tarifs_mentions_lecture_seule,
)
from backend.billing.demandes import (
    ErreurDemande,
    accepter_demande_paiement,
    accepter_demande_palier,
    lister_demandes_paiement,
    lister_demandes_palier,
    refuser_demande_paiement,
    refuser_demande_palier,
)
from backend.billing.dependances import StaffBillingDep
from backend.billing.factures import (
    ErreurFacture,
    annuler_facture,
    creer_facture_brouillon,
    emettre_facture,
    export_factures_csv,
    lire_facture,
    lister_factures,
    marquer_payee,
    rendre_facture_pdf,
)
from backend.billing.service import (
    ErreurBilling,
    PatchTenant,
    creer_tenant,
    lister_tenants,
    patcher_tenant,
    quotas_tenant,
    resume_usage_tenants,
)
from backend.plateforme.auth import verifier_mot_de_passe
from backend.plateforme.dependances import SessionDep
from backend.plateforme.email_outbox import lister_outbox, statut_resend

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class ConnexionStaffIn(BaseModel):
    email: str
    mot_de_passe: str


class ConnexionStaffOut(BaseModel):
    jeton: str
    staff_id: int
    role: str
    email: str


class TenantCreerIn(BaseModel):
    denomination: str = Field(min_length=1, max_length=200)
    type_tenant: Literal["cabinet", "entreprise"] = "cabinet"
    palier: Literal["essentiel", "standard", "premium", "souverain"] = "standard"
    email_admin: str = Field(min_length=3, max_length=200)
    mot_de_passe_admin: str = Field(min_length=8, max_length=200)
    creer_demo: bool = False
    note: str | None = None


class TenantCreerOut(BaseModel):
    tenant_id: int
    utilisateur_id: int
    email_admin: str
    palier: str
    version_referentiel_id: int | None
    demo_contribuable_id: int | None


class TenantPatchIn(BaseModel):
    statut: Literal["actif", "suspendu", "resilie"] | None = None
    palier: Literal["essentiel", "standard", "premium", "souverain"] | None = None
    note: str | None = None


@router.post("/auth/connexion", response_model=ConnexionStaffOut)
def api_connexion_staff(corps: ConnexionStaffIn, session: SessionDep) -> ConnexionStaffOut:
    """Login staff via auth_lookup_staff (SECURITY DEFINER) — pas de JWT tenant."""
    row = session.execute(
        text("SELECT * FROM auth_lookup_staff(:e)"),
        {"e": str(corps.email).strip().lower()},
    ).mappings().one_or_none()
    if row is None or not row["password_hash"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="identifiants invalides"
        )
    if not verifier_mot_de_passe(corps.mot_de_passe, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="identifiants invalides"
        )
    if not row["actif"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="compte inactif")

    jeton = emettre_jeton_staff(
        staff_id=int(row["id"]),
        role=str(row["role"]),
        email=str(row["email"]),
    )
    return ConnexionStaffOut(
        jeton=jeton,
        staff_id=int(row["id"]),
        role=str(row["role"]),
        email=str(row["email"]),
    )


@router.get("/tenants")
def api_lister_tenants(
    _staff: StaffBillingDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    return lister_tenants(session)


@router.post("/tenants", response_model=TenantCreerOut, status_code=status.HTTP_201_CREATED)
def api_creer_tenant(
    corps: TenantCreerIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> TenantCreerOut:
    try:
        r = creer_tenant(
            session,
            denomination=corps.denomination,
            type_tenant=corps.type_tenant,
            palier=corps.palier,
            email_admin=str(corps.email_admin),
            mot_de_passe_admin=corps.mot_de_passe_admin,
            creer_demo=corps.creer_demo,
            note=corps.note,
        )
    except ErreurBilling as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return TenantCreerOut(
        tenant_id=r.tenant_id,
        utilisateur_id=r.utilisateur_id,
        email_admin=r.email_admin,
        palier=r.palier,
        version_referentiel_id=r.version_referentiel_id,
        demo_contribuable_id=r.demo_contribuable_id,
    )


@router.patch("/tenants/{tenant_id}")
def api_patch_tenant(
    tenant_id: int,
    corps: TenantPatchIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return patcher_tenant(
            session,
            tenant_id,
            PatchTenant(statut=corps.statut, palier=corps.palier, note=corps.note),
        )
    except ErreurBilling as e:
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.get("/tenants/{tenant_id}/quotas")
def api_quotas_tenant(
    tenant_id: int,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    existe = session.execute(
        text("SELECT 1 FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()
    if not existe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant introuvable")
    return quotas_tenant(session, tenant_id)


@router.get("/usage")
def api_usage_dashboard(
    _staff: StaffBillingDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    """Dashboard usage : missions + metrage IA agrege (pas de donnees mission)."""
    return resume_usage_tenants(session)


class FactureCreerIn(BaseModel):
    tenant_id: int
    note: str | None = None


@router.get("/factures")
def api_lister_factures(
    _staff: StaffBillingDep,
    session: SessionDep,
    tenant_id: int | None = None,
) -> list[dict[str, Any]]:
    return lister_factures(session, tenant_id)


@router.post("/factures", status_code=status.HTTP_201_CREATED)
def api_creer_facture(
    corps: FactureCreerIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        f = creer_facture_brouillon(session, corps.tenant_id, note=corps.note)
    except ErreurFacture as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {
        "id": f.id,
        "numero": f.numero,
        "montant": str(f.montant),
        "statut": f.statut,
        "avertissement": "Montant commercial provisoire — À CONFIRMER",
    }


@router.post("/factures/{facture_id}/emettre")
def api_emettre_facture(
    facture_id: int,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return emettre_facture(session, facture_id)
    except ErreurFacture as e:
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.post("/factures/{facture_id}/payer")
def api_payer_facture(
    facture_id: int,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return marquer_payee(session, facture_id)
    except ErreurFacture as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/factures/{facture_id}/annuler")
def api_annuler_facture(
    facture_id: int,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return annuler_facture(session, facture_id)
    except ErreurFacture as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/factures/export.csv")
def api_export_factures_csv(
    _staff: StaffBillingDep,
    session: SessionDep,
    tenant_id: int | None = None,
) -> PlainTextResponse:
    lignes = lister_factures(session, tenant_id)
    csv = export_factures_csv(lignes)
    return PlainTextResponse(
        content=csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=factures.csv"},
    )


@router.get("/factures/{facture_id}/pdf")
def api_facture_pdf(
    facture_id: int,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> Response:
    """PDF commercial minimal (reportlab) — montants abonnement, pas fiscaux."""
    try:
        facture = lire_facture(session, facture_id)
    except ErreurFacture as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    mentions = lire_mentions_facture(session)["effectif"]
    pdf = rendre_facture_pdf(facture, mentions=mentions)
    numero = str(facture.get("numero") or facture_id).replace("/", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="facture-{numero}.pdf"'
        },
    )


class PaliersIn(BaseModel):
    """Saisie éditeur — montants / quotas. Vides = À CONFIRMER (provisoire technique)."""

    prix_mensuel_xof: dict[str, str | int | float | None] = Field(default_factory=dict)
    missions_par_palier: dict[str, int | None] = Field(default_factory=dict)


class MentionsFactureIn(BaseModel):
    raison_sociale: str | None = None
    siege: str | None = None
    rccm: str | None = None
    idu: str | None = None
    compte_bancaire: str | None = None
    regime_tva: str | None = None
    taux_tva: str | None = None


@router.get("/paliers")
def api_paliers(_staff: StaffBillingDep, session: SessionDep) -> dict[str, Any]:
    """Grille paliers — saisie éditeur si présente, sinon provisoire technique."""
    return resume_parametres_editeur(session)["paliers"]


@router.get("/tarifs-a-confirmer")
def api_tarifs_a_confirmer(
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Lecture seule : paliers, quotas, prix provisoires et mentions facture a_confirmer.

    Aucune écriture. Montants provisoires ≠ grille commerciale officielle.
    """
    return resume_tarifs_mentions_lecture_seule(session)


@router.get("/parametres")
def api_parametres_editeur(
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Paramètres éditeur : paliers, mentions facture, statut Resend (pas la clé)."""
    return resume_parametres_editeur(session)


@router.put("/parametres/paliers")
def api_sauver_paliers(
    corps: PaliersIn,
    staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Écrase le provisoire technique par la saisie éditeur (responsabilité 2AàZ)."""
    try:
        return ecrire_grille_paliers(
            session,
            prix_mensuel_xof=corps.prix_mensuel_xof,
            missions_par_palier=corps.missions_par_palier,
            par=staff.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/parametres/mentions-facture")
def api_sauver_mentions(
    corps: MentionsFactureIn,
    staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Mentions légales facture — laisser vide / À CONFIRMER si non fourni."""
    return ecrire_mentions_facture(
        session,
        corps.model_dump(),
        par=staff.email,
    )


@router.get("/email-outbox")
def api_email_outbox(
    _staff: StaffBillingDep,
    session: SessionDep,
    limit: int = 50,
) -> dict[str, Any]:
    """Outbox emails (invitations…) — visible surtout sans RESEND_API_KEY."""
    resend = statut_resend()
    lignes = lister_outbox(session, limit=limit)
    return {
        "resend": resend,
        "total": len(lignes),
        "lignes": lignes,
    }


class DemandeNoteIn(BaseModel):
    note_staff: str | None = Field(default=None, max_length=2000)


class AccepterPaiementIn(BaseModel):
    note_staff: str | None = Field(default=None, max_length=2000)
    marquer_facture_payee: bool = True


@router.get("/demandes-paiement")
def api_lister_demandes_paiement(
    _staff: StaffBillingDep,
    session: SessionDep,
    statut: str | None = None,
) -> list[dict[str, Any]]:
    return lister_demandes_paiement(session, statut)


@router.post("/demandes-paiement/{demande_id}/accepter")
def api_accepter_demande_paiement(
    demande_id: int,
    corps: AccepterPaiementIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Rapprochement staff — peut marquer la facture payée (jamais côté abonné)."""
    try:
        return accepter_demande_paiement(
            session,
            demande_id,
            note_staff=corps.note_staff,
            marquer_facture_payee=corps.marquer_facture_payee,
        )
    except ErreurDemande as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/demandes-paiement/{demande_id}/refuser")
def api_refuser_demande_paiement(
    demande_id: int,
    corps: DemandeNoteIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return refuser_demande_paiement(
            session, demande_id, note_staff=corps.note_staff
        )
    except ErreurDemande as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/demandes-palier")
def api_lister_demandes_palier(
    _staff: StaffBillingDep,
    session: SessionDep,
    statut: str | None = None,
) -> list[dict[str, Any]]:
    return lister_demandes_palier(session, statut)


@router.post("/demandes-palier/{demande_id}/accepter")
def api_accepter_demande_palier(
    demande_id: int,
    corps: DemandeNoteIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Accepte via patcher_tenant — seul le staff mute le palier."""
    try:
        return accepter_demande_palier(
            session, demande_id, note_staff=corps.note_staff
        )
    except ErreurDemande as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/demandes-palier/{demande_id}/refuser")
def api_refuser_demande_palier(
    demande_id: int,
    corps: DemandeNoteIn,
    _staff: StaffBillingDep,
    session: SessionDep,
) -> dict[str, Any]:
    try:
        return refuser_demande_palier(
            session, demande_id, note_staff=corps.note_staff
        )
    except ErreurDemande as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
