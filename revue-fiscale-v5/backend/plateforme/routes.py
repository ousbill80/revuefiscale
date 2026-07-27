"""Routes plateforme : provisionnement, auth, sante tenant."""
from __future__ import annotations

import datetime
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import config
from backend.plateforme.auth import (
    emettre_jeton,
    verifier_mot_de_passe,
)
from backend.plateforme.dependances import SessionDep, UtilisateurDep, session_abonne
from backend.plateforme.provisionnement import (
    ErreurProvisionnement,
    provisionner_cabinet,
)
from backend.plateforme.rbac import exiger_capacite

router = APIRouter(prefix="/api/v1", tags=["plateforme"])


class ProvisionnerIn(BaseModel):
    denomination: str = Field(min_length=1, max_length=200)
    type_tenant: Literal["cabinet", "entreprise"] = "cabinet"
    palier: Literal["essentiel", "standard", "premium", "souverain"] = "standard"
    email_admin: str = Field(min_length=3, max_length=200)
    mot_de_passe_admin: str = Field(min_length=8, max_length=200)
    creer_demo: bool = False


class ProvisionnerOut(BaseModel):
    tenant_id: int
    utilisateur_id: int
    email_admin: str
    palier: str
    version_referentiel_id: int | None
    demo_contribuable_id: int | None
    jeton: str
    tenant_denomination: str


class ConnexionIn(BaseModel):
    email: str
    mot_de_passe: str


class ConnexionOut(BaseModel):
    jeton: str
    tenant_id: int
    role: str
    email: str
    tenant_denomination: str


@router.post("/provisionnement", response_model=ProvisionnerOut)
def api_provisionner(corps: ProvisionnerIn, session: SessionDep) -> ProvisionnerOut:
    """Self-service public — ferme hors ENV=dev sauf ALLOW_PUBLIC_PROVISIONING.

    Creation d abonne en production : Admin billing uniquement
    (POST /api/v1/billing/tenants). Voir docs/11-saas-surfaces.md.
    """
    if not config.provisionnement_public_autorise():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Provisionnement public desactive. "
                "Creez l abonne via Admin billing (/billing) "
                "ou activez ALLOW_PUBLIC_PROVISIONING=true (dev uniquement)."
            ),
        )
    try:
        r = provisionner_cabinet(
            session,
            denomination=corps.denomination,
            type_tenant=corps.type_tenant,
            palier=corps.palier,
            email_admin=str(corps.email_admin),
            mot_de_passe_admin=corps.mot_de_passe_admin,
            creer_demo=corps.creer_demo,
        )
    except ErreurProvisionnement as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=r.email_admin,
    )
    return ProvisionnerOut(
        tenant_id=r.tenant_id,
        utilisateur_id=r.utilisateur_id,
        email_admin=r.email_admin,
        palier=r.palier,
        version_referentiel_id=r.version_referentiel_id,
        demo_contribuable_id=r.demo_contribuable_id,
        jeton=jeton,
        tenant_denomination=corps.denomination.strip(),
    )


@router.post("/auth/connexion", response_model=ConnexionOut)
def api_connexion(corps: ConnexionIn, session: SessionDep) -> ConnexionOut:
    """Login via auth_lookup_utilisateur (SECURITY DEFINER) — pas de fuite RLS."""
    row = session.execute(
        text("SELECT * FROM auth_lookup_utilisateur(:e)"),
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

    tenant_id = int(row["tenant_id"])
    # Table tenant sans RLS — lecture denomination pour l UI (pas de donnees missions).
    denom = session.execute(
        text("SELECT denomination FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()

    jeton = emettre_jeton(
        utilisateur_id=int(row["id"]),
        tenant_id=tenant_id,
        role=str(row["role"]),
        email=str(row["email"]),
    )
    return ConnexionOut(
        jeton=jeton,
        tenant_id=tenant_id,
        role=str(row["role"]),
        email=str(row["email"]),
        tenant_denomination=str(denom or f"Cabinet #{tenant_id}"),
    )


@router.get("/moi")
def api_moi(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict[str, object]:
    n = session.execute(text("SELECT count(*) FROM contribuable")).scalar_one()
    denom = session.execute(
        text("SELECT denomination FROM tenant WHERE id = :t"),
        {"t": utilisateur.tenant_id},
    ).scalar_one_or_none()
    return {
        "utilisateur_id": utilisateur.utilisateur_id,
        "tenant_id": utilisateur.tenant_id,
        "role": utilisateur.role,
        "email": utilisateur.email,
        "tenant_denomination": str(denom or f"Cabinet #{utilisateur.tenant_id}"),
        "contribuables_visibles": n,
    }


class ContribuableIn(BaseModel):
    denomination: str = Field(min_length=1, max_length=200)
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


class ContribuableOut(BaseModel):
    id: int
    denomination: str
    ncc: str | None = None
    rccm: str | None = None
    forme: str | None = None
    dfe: str | None = None
    regime_fiscal: str | None = None
    forme_juridique: str | None = None
    siege_social: str | None = None
    commune: str | None = None
    centre_impots: str | None = None
    capital_social: float | None = None
    mois_cloture: int | None = None
    activite_principale: str | None = None
    date_immatriculation: str | None = None
    cree_le: str | None = None
    cree_par: int | None = None
    cree_par_email: str | None = None


@router.post("/contribuables", response_model=ContribuableOut)
def api_creer_contribuable(
    corps: ContribuableIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> ContribuableOut:
    from backend.abonne.contribuable_identite import (
        ErreurIdentiteLegale,
        normaliser_payload,
        valider_identite_legale,
    )
    from backend.abonne.service import ErreurDoublonContribuable, creer_contribuable
    from backend.moteur.journal import append_journal

    exiger_capacite(
        utilisateur,
        "ecrire_contribuable",
        detail="role lecteur : creation de contribuable interdite",
    )
    try:
        payload = normaliser_payload(
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
        valider_identite_legale(payload, strict=True)
    except ErreurIdentiteLegale as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    try:
        fiche = creer_contribuable(
            session,
            tenant_id=utilisateur.tenant_id,
            cree_par=utilisateur.utilisateur_id,
            payload=payload,
        )
    except ErreurDoublonContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="creation_contribuable",
        charge_utile={
            "contribuable_id": fiche["id"],
            "denomination": fiche.get("denomination"),
            "forme": fiche.get("forme"),
            "ncc": fiche.get("ncc"),
        },
    )
    return ContribuableOut(**fiche)  # type: ignore[arg-type]


class MissionObjectifOut(BaseModel):
    id: int
    mission_id: int
    ordre: int
    libelle: str
    cree_le: str | None = None
    maj_le: str | None = None


class MissionObjectifIn(BaseModel):
    libelle: str = Field(min_length=1, max_length=500)
    ordre: int | None = None


class ObjectifFiscalOut(BaseModel):
    id: int
    mission_id: int
    impot: str
    exercices: list[int]
    dans_perimetre: bool
    motif_exclusion: str | None = None


class ObjectifFiscalIn(BaseModel):
    impot: str
    exercices: list[int] = Field(min_length=1)
    dans_perimetre: bool = True
    motif_exclusion: str | None = None


class MissionObjectifsRemplacerIn(BaseModel):
    objectifs: list[MissionObjectifIn] = Field(default_factory=list)


class MissionIn(BaseModel):
    contribuable_id: int
    exercice: int = Field(ge=2000, le=2100)
    profil: dict[str, object]
    type_engagement: (
        Literal["preventive", "cac", "due_diligence", "assistance_controle", "autre"]
        | None
    ) = None
    perimetre_impots: list[str] | None = None
    exclusions_declarees: str | None = None
    seuil_signification: float | None = None
    objectifs: list[MissionObjectifIn] | None = None


class MissionOut(BaseModel):
    id: int
    version_referentiel_id: int
    statut: str = "cadrage"
    type_engagement: str = "autre"
    type_engagement_libelle: str | None = None
    perimetre_impots: list[str] | None = None
    revue_partielle: bool = False
    exclusions_declarees: str | None = None
    seuil_signification: str | None = None
    objectifs: list[MissionObjectifOut] = Field(default_factory=list)
    objectifs_fiscaux: list[ObjectifFiscalOut] = Field(default_factory=list)


class MissionCadrageIn(BaseModel):
    """Champs de cadrage — modifiables uniquement si statut = cadrage."""

    type_engagement: (
        Literal["preventive", "cac", "due_diligence", "assistance_controle", "autre"]
        | None
    ) = None
    perimetre_impots: list[str] | None = None
    exclusions_declarees: str | None = None
    seuil_signification: float | None = None
    objectifs: list[MissionObjectifIn] | None = None
    objectifs_fiscaux: list[ObjectifFiscalIn] | None = None


def _mission_out(detail: dict) -> MissionOut:
    objectifs_brut = detail.get("objectifs") or []
    objectifs = [
        MissionObjectifOut(
            id=int(o["id"]),
            mission_id=int(o["mission_id"]),
            ordre=int(o["ordre"]),
            libelle=str(o["libelle"]),
            cree_le=o.get("cree_le"),
            maj_le=o.get("maj_le"),
        )
        for o in objectifs_brut
        if isinstance(o, dict)
    ]
    fisc_brut = detail.get("objectifs_fiscaux") or []
    fiscaux = [
        ObjectifFiscalOut(
            id=int(o["id"]),
            mission_id=int(o["mission_id"]),
            impot=str(o["impot"]),
            exercices=[int(x) for x in (o.get("exercices") or [])],
            dans_perimetre=bool(o.get("dans_perimetre")),
            motif_exclusion=o.get("motif_exclusion"),
        )
        for o in fisc_brut
        if isinstance(o, dict)
    ]
    return MissionOut(
        id=int(detail["id"]),
        version_referentiel_id=int(detail.get("version_referentiel_id") or 0),
        statut=str(detail.get("statut") or "cadrage"),
        type_engagement=str(detail.get("type_engagement") or "autre"),
        type_engagement_libelle=detail.get("type_engagement_libelle"),
        perimetre_impots=detail.get("perimetre_impots"),
        revue_partielle=bool(detail.get("revue_partielle")),
        exclusions_declarees=detail.get("exclusions_declarees"),
        seuil_signification=detail.get("seuil_signification"),
        objectifs=objectifs,
        objectifs_fiscaux=fiscaux,
    )

class MissionStatutIn(BaseModel):
    statut: Literal["cadrage", "en_cours", "cloturee"]


class MissionStatutOut(BaseModel):
    id: int
    statut: str
    statut_precedent: str
    inchange: bool = False
    risques_crees: int = 0
    # Résumé consultatif du contrôle qualité de pré-clôture (uniquement
    # lors d'un passage à « cloturee ») — jamais bloquant.
    controle_cloture: dict | None = None


@router.post("/missions", response_model=MissionOut)
def api_creer_mission(
    corps: MissionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> MissionOut:
    from backend.moteur.journal import append_journal
    from backend.plateforme.missions import (
        STATUT_CADRAGE,
        ErreurMission,
        ErreurMissionDoublon,
        QuotaEpuise,
        creer_mission,
        lire_mission,
    )

    exiger_capacite(utilisateur, "creer_mission")

    if corps.type_engagement is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Le type d'engagement est requis — choisissez-le à l'étape "
                "Mission (« Autre » reste possible, mais doit être sélectionné "
                "explicitement)."
            ),
        )

    try:
        mid = creer_mission(
            session,
            utilisateur.tenant_id,
            contribuable_id=corps.contribuable_id,
            exercice=corps.exercice,
            profil=dict(corps.profil),
            type_engagement=corps.type_engagement,
            perimetre_impots=corps.perimetre_impots,
            exclusions_declarees=corps.exclusions_declarees,
            seuil_signification=corps.seuil_signification,
            objectifs=(
                [o.model_dump() for o in corps.objectifs]
                if corps.objectifs is not None
                else None
            ),
        )
    except QuotaEpuise as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ErreurMissionDoublon as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ErreurMission as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    detail = lire_mission(session, utilisateur.tenant_id, mid)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mid,
        acteur=utilisateur.email,
        action="creation_mission",
        charge_utile={
            "exercice": corps.exercice,
            "contribuable_id": corps.contribuable_id,
            "version_referentiel_id": detail["version_referentiel_id"],
            "statut": STATUT_CADRAGE,
            "type_engagement": detail["type_engagement"],
            "perimetre_impots": detail["perimetre_impots"],
            "revue_partielle": detail["revue_partielle"],
            "objectifs": [o.get("libelle") for o in (detail.get("objectifs") or [])],
        },
    )
    return _mission_out({**detail, "id": mid, "statut": STATUT_CADRAGE})


@router.get("/missions/{mission_id}", response_model=MissionOut)
def api_lire_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> MissionOut:
    from backend.plateforme.missions import ErreurMission, lire_mission

    try:
        detail = lire_mission(session, utilisateur.tenant_id, mission_id)
    except ErreurMission as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return _mission_out(detail)


@router.get("/missions/{mission_id}/lettre-mission.docx")
def api_lettre_mission_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Livrable Word de cadrage — lettre de mission à personnaliser et signer."""
    from backend.plateforme.lettre_mission import (
        ErreurLettreMission,
        generer_lettre_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier = generer_lettre_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurLettreMission as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


@router.get("/missions/{mission_id}/demande-renseignements.docx")
def api_demande_renseignements_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Livrable Word — demande de renseignements et de documents au client."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.demande_renseignements import (
        ErreurDemandeRenseignements,
        generer_demande_renseignements,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier, stats = generer_demande_renseignements(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurDemandeRenseignements as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="telechargement_demande_renseignements",
        charge_utile=dict(stats),
    )
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


@router.get("/missions/{mission_id}/courrier-relance.docx")
def api_courrier_relance_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Courrier de relance .docx — items du suivi encore en attente.

    404 si mission hors tenant (RLS) ; 409 si aucun item en attente (la
    relance est alors sans objet).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.courrier_relance import (
        ErreurAucunItemEnAttente,
        ErreurCourrierIntrouvable,
        generer_courrier_relance,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier, stats = generer_courrier_relance(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurCourrierIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurAucunItemEnAttente as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="telechargement_courrier_relance",
        charge_utile=dict(stats),
    )
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


@router.get("/missions/{mission_id}/courrier-relance")
def api_courrier_relance_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Courrier de relance texte — items du suivi encore en attente.

    Déterministe et consultatif : le courrier est à relire et adapter
    par le fiscaliste avant envoi. Sans item ouvert, le courrier signale
    qu'aucune relance n'est nécessaire. 404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.courrier_relance import (
        ErreurCourrierIntrouvable,
        courrier_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        resultat = courrier_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurCourrierIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_courrier_relance",
        charge_utile={"nb_items_ouverts": resultat["nb_items_ouverts"]},
    )
    return resultat


@router.get("/missions/{mission_id}/courrier-relance.txt")
def api_courrier_relance_txt(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Courrier de relance texte téléchargeable (.txt, UTF-8).

    Même contenu que ``GET /missions/{id}/courrier-relance`` — 404 si
    mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.courrier_relance import (
        ErreurCourrierIntrouvable,
        courrier_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        resultat = courrier_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurCourrierIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_courrier_relance_txt",
        charge_utile={"nb_items_ouverts": resultat["nb_items_ouverts"]},
    )
    return Response(
        content=resultat["courrier"],
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                "attachment; "
                f'filename="courrier-relance-mission-{mission_id}.txt"'
            )
        },
    )


@router.get("/missions/{mission_id}/courrier-envoi.docx")
def api_courrier_envoi_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Courrier d'envoi du rapport .docx — lettre d'accompagnement client.

    Produit même sans exécution (constats « en cours d'instruction ») :
    seule une mission hors tenant (RLS) renvoie 404.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.courrier_envoi_rapport import (
        ErreurCourrierEnvoiIntrouvable,
        generer_courrier_envoi_complet,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier, stats = generer_courrier_envoi_complet(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurCourrierEnvoiIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="telechargement_courrier_envoi",
        charge_utile=dict(stats),
    )
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


@router.get("/missions/{mission_id}/lettre-affirmation.docx")
def api_lettre_affirmation_docx(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Lettre d'affirmation de la direction .docx — à en-tête du client.

    Toujours produite (les compteurs de risques/anomalies valent 0 sans
    exécution ni risque) : seule une mission hors tenant (RLS) → 404.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.lettre_affirmation import (
        ErreurLettreAffirmationIntrouvable,
        generer_lettre_affirmation_complete,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier, stats = generer_lettre_affirmation_complete(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurLettreAffirmationIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="telechargement_lettre_affirmation",
        charge_utile=dict(stats),
    )
    return Response(
        content=contenu,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


@router.get("/missions/{mission_id}/dossier-travail.zip")
def api_dossier_travail_zip(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Dossier de travail archivable (ZIP) — tous les livrables de la mission.

    Assemblage déterministe (aucun LLM) : chaque pièce est produite par le
    même module que son téléchargement individuel ; une pièce en échec est
    omise et notée dans ``00_sommaire.txt`` — l'archive n'échoue jamais
    pour une pièce manquante. 404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.archive_mission import (
        ErreurArchiveIntrouvable,
        construire_dossier,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        contenu, nom_fichier, stats = construire_dossier(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurArchiveIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="telechargement_dossier_travail",
        charge_utile=dict(stats),
    )
    return Response(
        content=contenu,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{nom_fichier}"'
        },
    )


class SuiviRenseignementPatchIn(BaseModel):
    """Mise à jour du suivi d'un item de la demande de renseignements."""

    statut: Literal["en_attente", "recu", "sans_objet"]
    date_relance: datetime.date | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.get("/missions/{mission_id}/suivi-renseignements")
def api_suivi_renseignements(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Suivi de circularisation : items demandés + statuts + synthèse."""
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviIntrouvable,
        lister_items,
        synthese_depuis_items,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        items = lister_items(session, utilisateur.tenant_id, mission_id)
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return {"items": items, "synthese": synthese_depuis_items(items)}


@router.patch("/missions/{mission_id}/suivi-renseignements/{cle_item}")
def api_patcher_suivi_renseignements(
    mission_id: int,
    cle_item: str,
    corps: SuiviRenseignementPatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Marque un item reçu / en attente / sans objet (relance, note)."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviIntrouvable,
        ErreurSuiviRenseignements,
        lister_items,
        maj_item,
        synthese_depuis_items,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        item = maj_item(
            session,
            utilisateur.tenant_id,
            mission_id,
            cle_item,
            statut=corps.statut,
            date_relance=corps.date_relance,
            note=corps.note,
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurSuiviRenseignements as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="maj_suivi_renseignements",
        charge_utile={
            "cle_item": item["cle_item"],
            "statut": item["statut"],
            "date_relance": item["date_relance"],
            "note_renseignee": bool(item["note"]),
        },
    )
    items = lister_items(session, utilisateur.tenant_id, mission_id)
    return {"item": item, "synthese": synthese_depuis_items(items)}


@router.post("/missions/{mission_id}/suivi-renseignements/depuis-civisme")
def api_ajouter_items_depuis_civisme(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Passerelle civisme → demande : un item par échéance « manquante ».

    Déclenchée par un clic explicite du fiscaliste. Idempotente (aucun
    doublon au second appel) ; mission clôturée → 409 ; mission hors
    tenant → 404 (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviIntrouvable,
        ErreurSuiviMissionCloturee,
        ajouter_items_depuis_civisme,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        resultat = ajouter_items_depuis_civisme(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurSuiviMissionCloturee as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="ajout_items_demande_depuis_civisme",
        charge_utile=dict(resultat),
    )
    return resultat


class PlanifierRelancesIn(BaseModel):
    """Planification groupée des relances des items « en_attente »."""

    date_relance: datetime.date
    remplacer: bool = False


@router.post("/missions/{mission_id}/suivi-renseignements/planifier-relances")
def api_planifier_relances(
    mission_id: int,
    corps: PlanifierRelancesIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Fixe la date de relance de tous les items encore « en_attente ».

    Déclenchée par un clic explicite du fiscaliste. Sans ``remplacer``,
    seuls les items sans date de relance sont planifiés ; date passée →
    422 ; mission clôturée → 409 ; mission hors tenant → 404 (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviDateInvalide,
        ErreurSuiviIntrouvable,
        ErreurSuiviMissionCloturee,
        planifier_relances,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        resultat = planifier_relances(
            session,
            utilisateur.tenant_id,
            mission_id,
            corps.date_relance,
            remplacer=corps.remplacer,
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurSuiviMissionCloturee as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    except ErreurSuiviDateInvalide as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="planification_relances",
        charge_utile={
            **resultat,
            "date_relance": corps.date_relance.isoformat(),
            "remplacer": corps.remplacer,
        },
    )
    return resultat


# Route littérale déclarée AVANT la route paramétrée
# /{cle_item}/relance-effectuee (ordre de résolution FastAPI).
@router.post("/missions/{mission_id}/suivi-renseignements/relances-effectuees")
def api_relances_effectuees_groupees(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Marque en un clic toutes les relances planifiées comme effectuées.

    Déclenchée par un clic explicite du fiscaliste après envoi du
    courrier de relance : trace la date de dernière relance, incrémente
    les compteurs et efface les dates planifiées de tous les items
    « en_attente » avec date. Aucun item planifié → 200 avec
    ``effectuees = 0`` ; mission clôturée → 409 ; hors tenant → 404 (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviIntrouvable,
        ErreurSuiviMissionCloturee,
        relances_effectuees_groupees,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        resultat = relances_effectuees_groupees(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurSuiviMissionCloturee as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="relances_effectuees_groupees",
        charge_utile=dict(resultat),
    )
    return resultat


@router.post(
    "/missions/{mission_id}/suivi-renseignements/{cle_item}/relance-effectuee"
)
def api_relance_effectuee(
    mission_id: int,
    cle_item: str,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Marque la relance d'un item comme effectuée par le fiscaliste.

    Trace la date de dernière relance, incrémente le compteur et efface
    la date planifiée. Item déjà reçu ou mission clôturée → 409 ;
    mission ou item hors tenant → 404 (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviIntrouvable,
        ErreurSuiviItemDejaRecu,
        ErreurSuiviMissionCloturee,
        lister_items,
        relance_effectuee,
        synthese_depuis_items,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        item = relance_effectuee(
            session, utilisateur.tenant_id, mission_id, cle_item
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except (ErreurSuiviMissionCloturee, ErreurSuiviItemDejaRecu) as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="relance_effectuee",
        charge_utile={
            "cle_item": item["cle_item"],
            "derniere_relance_le": item["derniere_relance_le"],
            "nb_relances": item["nb_relances"],
        },
    )
    items = lister_items(session, utilisateur.tenant_id, mission_id)
    return {"item": item, "synthese": synthese_depuis_items(items)}


class ReporterRelanceIn(BaseModel):
    """Report de la relance d'un item à une nouvelle date."""

    date_relance: datetime.date


@router.post(
    "/missions/{mission_id}/suivi-renseignements/{cle_item}/reporter"
)
def api_reporter_relance(
    mission_id: int,
    cle_item: str,
    corps: ReporterRelanceIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Reporte la relance d'un item à une nouvelle date.

    Date passée → 422 ; item déjà reçu ou mission clôturée → 409 ;
    mission ou item hors tenant → 404 (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.suivi_renseignements import (
        ErreurSuiviDateInvalide,
        ErreurSuiviIntrouvable,
        ErreurSuiviItemDejaRecu,
        ErreurSuiviMissionCloturee,
        lister_items,
        reporter_relance,
        synthese_depuis_items,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        item = reporter_relance(
            session,
            utilisateur.tenant_id,
            mission_id,
            cle_item,
            corps.date_relance,
        )
    except ErreurSuiviIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except (ErreurSuiviMissionCloturee, ErreurSuiviItemDejaRecu) as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    except ErreurSuiviDateInvalide as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="report_relance",
        charge_utile={
            "cle_item": item["cle_item"],
            "date_relance": item["date_relance"],
        },
    )
    items = lister_items(session, utilisateur.tenant_id, mission_id)
    return {"item": item, "synthese": synthese_depuis_items(items)}


class ReponseClientIn(BaseModel):
    """Saisie de la réponse client d'un item de circularisation."""

    contenu: str = Field(min_length=1, max_length=10000)
    pieces_recues: str | None = Field(default=None, max_length=4000)


@router.put("/missions/{mission_id}/reponses/{cle_item}")
def api_enregistrer_reponse_client(
    mission_id: int,
    cle_item: str,
    corps: ReponseClientIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Enregistre (UPSERT) la réponse client d'un item — item passé « recu »."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.reponses_client import (
        ErreurReponseClient,
        ErreurReponseIntrouvable,
        enregistrer_reponse,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        reponse = enregistrer_reponse(
            session,
            utilisateur.tenant_id,
            mission_id,
            cle_item,
            contenu=corps.contenu,
            pieces_recues=corps.pieces_recues,
            saisie_par=utilisateur.email,
        )
    except ErreurReponseIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurReponseClient as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="saisie_reponse_client",
        charge_utile={
            "cle_item": reponse["cle_item"],
            "pieces_recues_renseignees": bool(reponse["pieces_recues"]),
        },
    )
    return {"reponse": reponse}


@router.get("/missions/{mission_id}/reponses")
def api_lister_reponses_client(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Réponses client saisies + statut de la règle à la dernière exécution."""
    from backend.plateforme.reponses_client import (
        ErreurReponseIntrouvable,
        lister_reponses,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        reponses = lister_reponses(session, utilisateur.tenant_id, mission_id)
    except ErreurReponseIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return {"reponses": reponses}


class TempsMissionIn(BaseModel):
    """Saisie d'une entrée de temps passé sur la mission."""

    collaborateur: str | None = Field(default=None, max_length=200)
    phase: str = Field(min_length=1, max_length=50)
    date_jour: datetime.date
    heures: float
    note: str | None = Field(default=None, max_length=2000)


@router.post("/missions/{mission_id}/temps")
def api_saisir_temps_mission(
    mission_id: int,
    corps: TempsMissionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Saisit un temps passé (phase, date, heures) — pilotage rentabilité."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.temps_mission import (
        ErreurTempsIntrouvable,
        ErreurTempsMission,
        saisir_temps,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        entree = saisir_temps(
            session,
            utilisateur.tenant_id,
            mission_id,
            collaborateur=(corps.collaborateur or utilisateur.email),
            phase=corps.phase,
            date_jour=corps.date_jour,
            heures=corps.heures,
            note=corps.note,
        )
    except ErreurTempsIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurTempsMission as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="saisie_temps_mission",
        charge_utile={
            "temps_id": entree["id"],
            "collaborateur": entree["collaborateur"],
            "phase": entree["phase"],
            "date_jour": entree["date_jour"],
            "heures": entree["heures"],
        },
    )
    return {"entree": entree}


@router.delete("/missions/{mission_id}/temps/{temps_id}")
def api_supprimer_temps_mission(
    mission_id: int,
    temps_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Supprime une entrée de temps saisie par erreur."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.temps_mission import (
        ErreurTempsIntrouvable,
        supprimer_temps,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        entree = supprimer_temps(
            session, utilisateur.tenant_id, mission_id, temps_id
        )
    except ErreurTempsIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="suppression_temps_mission",
        charge_utile={
            "temps_id": entree["id"],
            "collaborateur": entree["collaborateur"],
            "phase": entree["phase"],
            "heures": entree["heures"],
        },
    )
    return {"entree": entree}


@router.get("/missions/{mission_id}/temps")
def api_recap_temps_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    taux_horaire: float | None = None,
) -> dict:
    """Récap des temps : entrées, total, par phase/collaborateur, valorisation."""
    from backend.plateforme.temps_mission import (
        ErreurTempsIntrouvable,
        ErreurTempsMission,
        recap_temps,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return recap_temps(
            session, utilisateur.tenant_id, mission_id, taux_horaire
        )
    except ErreurTempsIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurTempsMission as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e


class RentabiliteMissionIn(BaseModel):
    """Paramètres de rentabilité : honoraires convenus et taux horaire.

    Champ absent ou ``null`` = paramètre effacé (retour à « non convenu »).
    """

    honoraires: float | None = None
    taux_horaire: float | None = None


@router.put("/missions/{mission_id}/rentabilite")
def api_definir_rentabilite_mission(
    mission_id: int,
    corps: RentabiliteMissionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Définit honoraires et taux horaire, retourne la rentabilité à jour."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.rentabilite_mission import (
        ErreurRentabilite,
        ErreurRentabiliteIntrouvable,
        definir_parametres,
        rentabilite_mission,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        parametres = definir_parametres(
            session,
            utilisateur.tenant_id,
            mission_id,
            honoraires=corps.honoraires,
            taux_horaire=corps.taux_horaire,
        )
    except ErreurRentabiliteIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurRentabilite as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="definition_parametres_rentabilite",
        charge_utile=parametres,
    )
    return rentabilite_mission(session, utilisateur.tenant_id, mission_id)


@router.get("/missions/{mission_id}/rentabilite")
def api_rentabilite_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Rentabilité de la mission : honoraires, taux, coût, marge, taux %."""
    from backend.plateforme.rentabilite_mission import (
        ErreurRentabiliteIntrouvable,
        rentabilite_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return rentabilite_mission(session, utilisateur.tenant_id, mission_id)
    except ErreurRentabiliteIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/missions/{mission_id}/rentabilite.csv")
def api_exporter_rentabilite_csv(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Rentabilité au format CSV Excel FR (« ; ») — annexe du dossier."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.rentabilite_mission import (
        ErreurRentabilite,
        ErreurRentabiliteIntrouvable,
        exporter_rentabilite_csv,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        nom, contenu = exporter_rentabilite_csv(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurRentabiliteIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurRentabilite as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="export_rentabilite_csv",
        charge_utile={"fichier": nom},
    )
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


class VisaMissionIn(BaseModel):
    """Pose d'un visa de supervision (phase, rôle) — vise_par = email connecté."""

    phase: str = Field(min_length=1, max_length=50)
    role: str = Field(min_length=1, max_length=50)
    commentaire: str | None = Field(default=None, max_length=2000)


@router.post("/missions/{mission_id}/visas")
def api_poser_visa_mission(
    mission_id: int,
    corps: VisaMissionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Pose un visa de supervision sur une phase (ordre hiérarchique contrôlé)."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.visas_mission import (
        ErreurVisaIntrouvable,
        ErreurVisaMission,
        poser_visa,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        visa = poser_visa(
            session,
            utilisateur.tenant_id,
            mission_id,
            phase=corps.phase,
            role=corps.role,
            vise_par=utilisateur.email,
            commentaire=corps.commentaire,
        )
    except ErreurVisaIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurVisaMission as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="pose_visa_mission",
        charge_utile={
            "phase": visa["phase"],
            "role": visa["role"],
            "commentaire_renseigne": bool(visa["commentaire"]),
        },
    )
    return {"visa": visa}


@router.delete("/missions/{mission_id}/visas/{phase}/{role}")
def api_revoquer_visa_mission(
    mission_id: int,
    phase: str,
    role: str,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Révoque un visa — refusé si un visa de rang supérieur est présent."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.visas_mission import (
        ErreurVisaIntrouvable,
        ErreurVisaMission,
        revoquer_visa,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        visa = revoquer_visa(
            session, utilisateur.tenant_id, mission_id, phase=phase, role=role
        )
    except ErreurVisaIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurVisaMission as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="revocation_visa_mission",
        charge_utile={
            "phase": visa["phase"],
            "role": visa["role"],
            "vise_par": visa["vise_par"],
        },
    )
    return {"visa": visa}


@router.get("/missions/{mission_id}/visas")
def api_etat_visas_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Registre des visas de supervision : phases, visas posés, complétude."""
    from backend.plateforme.visas_mission import (
        ErreurVisaIntrouvable,
        etat_visas,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return etat_visas(session, utilisateur.tenant_id, mission_id)
    except ErreurVisaIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/missions/{mission_id}/programme")
def api_etat_programme_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Programme de travail : diligences par phase, avancement % et global."""
    from backend.plateforme.programme_travail import (
        ErreurProgrammeIntrouvable,
        etat_programme,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return etat_programme(session, utilisateur.tenant_id, mission_id)
    except ErreurProgrammeIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class DiligenceMissionIn(BaseModel):
    """Coche/décoche d'une diligence — fait_par = email connecté."""

    fait: bool


@router.put("/missions/{mission_id}/programme/{code}")
def api_cocher_diligence_mission(
    mission_id: int,
    code: str,
    corps: DiligenceMissionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Coche ou décoche une diligence du programme de travail standard."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.programme_travail import (
        ErreurProgrammeIntrouvable,
        ErreurProgrammeTravail,
        cocher_diligence,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        diligence = cocher_diligence(
            session,
            utilisateur.tenant_id,
            mission_id,
            code=code,
            fait=corps.fait,
            fait_par=utilisateur.email,
        )
    except ErreurProgrammeIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurProgrammeTravail as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="coche_diligence_programme",
        charge_utile={
            "phase": diligence["phase"],
            "code": diligence["code"],
            "fait": diligence["fait"],
        },
    )
    return {"diligence": diligence}


@router.patch("/missions/{mission_id}/cadrage", response_model=MissionOut)
def api_patcher_cadrage_mission(
    mission_id: int,
    corps: MissionCadrageIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> MissionOut:
    """Met à jour type / périmètre / exclusions / seuil / objectifs — gelé si ≠ cadrage."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.missions import ErreurMission, patcher_cadrage_mission

    exiger_capacite(utilisateur, "creer_mission")
    payload = corps.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aucun champ de cadrage fourni",
        )
    try:
        detail = patcher_cadrage_mission(
            session,
            utilisateur.tenant_id,
            mission_id,
            **payload,
        )
    except ErreurMission as e:
        msg = str(e)
        code = (
            status.HTTP_409_CONFLICT
            if "figé" in msg or "fige" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e

    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="cadrage_mission",
        charge_utile={
            "champs": sorted(payload.keys()),
            "type_engagement": detail["type_engagement"],
            "perimetre_impots": detail["perimetre_impots"],
            "revue_partielle": detail["revue_partielle"],
            "objectifs": [o.get("libelle") for o in (detail.get("objectifs") or [])],
        },
    )
    return _mission_out(detail)


@router.get(
    "/missions/{mission_id}/objectifs",
    response_model=list[MissionObjectifOut],
)
def api_lister_objectifs_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[MissionObjectifOut]:
    from backend.plateforme.objectifs import (
        ErreurObjectif,
        lister_objectifs_mission,
    )

    try:
        rows = lister_objectifs_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurObjectif as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    return [
        MissionObjectifOut(
            id=int(o["id"]),
            mission_id=int(o["mission_id"]),
            ordre=int(o["ordre"]),
            libelle=str(o["libelle"]),
            cree_le=o.get("cree_le"),
            maj_le=o.get("maj_le"),
        )
        for o in rows
    ]


@router.put(
    "/missions/{mission_id}/objectifs",
    response_model=list[MissionObjectifOut],
)
def api_remplacer_objectifs_mission(
    mission_id: int,
    corps: MissionObjectifsRemplacerIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[MissionObjectifOut]:
    """Remplace la liste d'objectifs — gelé si statut ≠ cadrage."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.objectifs import (
        ErreurObjectif,
        remplacer_objectifs_mission,
    )

    exiger_capacite(utilisateur, "creer_mission")
    try:
        rows = remplacer_objectifs_mission(
            session,
            utilisateur.tenant_id,
            mission_id,
            [o.model_dump() for o in corps.objectifs],
            verifier_cadrage=True,
        )
    except ErreurObjectif as e:
        msg = str(e)
        code = (
            status.HTTP_409_CONFLICT
            if "figé" in msg or "fige" in msg
            else status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e

    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="objectifs_mission",
        charge_utile={
            "objectifs": [o.get("libelle") for o in rows],
        },
    )
    return [
        MissionObjectifOut(
            id=int(o["id"]),
            mission_id=int(o["mission_id"]),
            ordre=int(o["ordre"]),
            libelle=str(o["libelle"]),
            cree_le=o.get("cree_le"),
            maj_le=o.get("maj_le"),
        )
        for o in rows
    ]


@router.get(
    "/missions/{mission_id}/objectifs-fiscaux",
    response_model=list[ObjectifFiscalOut],
)
def api_lister_objectifs_fiscaux(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[ObjectifFiscalOut]:
    from backend.plateforme.objectifs_fiscaux import (
        ErreurObjectifFiscal,
        lister_objectifs_fiscaux,
    )

    try:
        rows = lister_objectifs_fiscaux(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurObjectifFiscal as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    return [ObjectifFiscalOut(**o) for o in rows]


class TacheOut(BaseModel):
    id: int
    objectif_id: int
    mission_id: int | None = None
    impot: str | None = None
    regle_version_id: int | None = None
    regle_id: str | None = None
    statut: str
    assignee_a: int | None = None
    bloquee_par: list[int] = Field(default_factory=list)
    piece_attendue: str | None = None
    conclusion_id: int | None = None


class TachePatchIn(BaseModel):
    statut: (
        Literal[
            "a_faire",
            "en_cours",
            "bloquee",
            "sous_seuil",
            "non_verifiable",
            "conforme",
            "anomalie",
            "hors_perimetre",
        ]
        | None
    ) = None
    piece_attendue: str | None = None
    assignee_a: int | None = None


@router.get("/missions/{mission_id}/taches", response_model=list[TacheOut])
def api_lister_taches(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    ouvertes: bool = False,
) -> list[TacheOut]:
    from backend.plateforme.taches import ErreurTache, lister_taches_mission

    try:
        rows = lister_taches_mission(
            session,
            utilisateur.tenant_id,
            mission_id,
            ouvertes_seulement=ouvertes,
        )
    except ErreurTache as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    return [TacheOut(**r) for r in rows]


@router.patch("/missions/{mission_id}/taches/{tache_id}", response_model=TacheOut)
def api_patcher_tache(
    mission_id: int,
    tache_id: int,
    corps: TachePatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> TacheOut:
    from backend.plateforme.taches import ErreurTache, patcher_tache

    exiger_capacite(utilisateur, "executer_mission")
    payload = corps.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aucun champ fourni",
        )
    kwargs: dict = {"acteur": utilisateur.email}
    if "statut" in payload:
        kwargs["statut"] = payload["statut"]
    if "piece_attendue" in payload:
        kwargs["piece_attendue"] = payload["piece_attendue"]
    if "assignee_a" in payload:
        kwargs["assignee_a"] = payload["assignee_a"]
    try:
        row = patcher_tache(
            session,
            utilisateur.tenant_id,
            mission_id,
            tache_id,
            **kwargs,
        )
    except ErreurTache as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    return TacheOut(**row)


@router.patch("/missions/{mission_id}/statut", response_model=MissionStatutOut)
def api_changer_statut_mission(
    mission_id: int,
    corps: MissionStatutIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> MissionStatutOut:
    """Cycle de vie dossier : cadrage → en_cours → cloturee (réouverture possible)."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.missions import ErreurMission, changer_statut_mission

    exiger_capacite(utilisateur, "cloturer_mission")
    try:
        r = changer_statut_mission(
            session,
            utilisateur.tenant_id,
            mission_id,
            corps.statut,
        )
    except ErreurMission as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    if not r.get("inchange"):
        append_journal(
            session,
            tenant_id=utilisateur.tenant_id,
            mission_id=mission_id,
            acteur=utilisateur.email,
            action="changement_statut",
            charge_utile={
                "statut_precedent": r["statut_precedent"],
                "statut": r["statut"],
                "declencheur": "manuel",
            },
        )

    # Passage à « cloturee » : joindre le résumé consultatif du contrôle
    # qualité de pré-clôture (jamais bloquant, best-effort).
    controle: dict | None = None
    if corps.statut == "cloturee":
        from backend.plateforme.controle_cloture import (
            ErreurControleCloture,
            evaluer_cloture,
        )

        try:
            controle = evaluer_cloture(
                session, utilisateur.tenant_id, mission_id
            )
        except ErreurControleCloture:
            controle = None
    return MissionStatutOut(**r, controle_cloture=controle)


@router.get("/missions/{mission_id}/controle-cloture")
def api_controle_cloture(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Contrôle qualité de pré-clôture — déterministe et consultatif.

    Revue des points avant clôture (conclusions instruites, risques
    traités, note de synthèse, réponses client, preuves de résolution).
    Ne bloque jamais la clôture. 404 si mission hors tenant (RLS).
    """
    from backend.plateforme.controle_cloture import (
        ErreurControleCloture,
        evaluer_cloture,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return evaluer_cloture(session, utilisateur.tenant_id, mission_id)
    except ErreurControleCloture as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/missions/{mission_id}/echeancier-fiscal")
def api_echeancier_fiscal_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Échéancier fiscal de l'exercice revu — déterministe (dates CGI CI).

    Calendrier des obligations déclaratives et de paiement du
    contribuable pour l'exercice de la mission (TVA/ITS mensuels,
    résultat et états financiers, fractions BIC/IS, patente, IRC/IRCM),
    selon le régime du profil mission. 404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.echeancier_fiscal import (
        ErreurEcheancierIntrouvable,
        echeancier_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        echeancier = echeancier_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurEcheancierIntrouvable as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_echeancier_fiscal",
        charge_utile={
            "exercice": echeancier["exercice"],
            "regime": echeancier["regime"],
            "total_echeances": echeancier["synthese"]["total"],
        },
    )
    return echeancier


@router.get("/missions/{mission_id}/pilotage")
def api_pilotage_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Pilotage de mission — synthèse transverse (lecture seule).

    Agrège en un appel les synthèses des modules existants : avancement
    du programme de travail, contrôle de pré-clôture, temps passés,
    rentabilité, visas et conclusions de la dernière exécution — la
    lecture d'ensemble du chef de mission. 404 si mission hors tenant.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.pilotage_mission import (
        ErreurPilotageMission,
        pilotage_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        pilotage = pilotage_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurPilotageMission as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_pilotage_mission",
        charge_utile={
            "avancement_pct": pilotage["programme"]["synthese"][
                "avancement_pct"
            ],
            "cloture_recommandee": pilotage["controle_cloture"][
                "cloture_recommandee"
            ],
        },
    )
    return pilotage


@router.get("/missions/{mission_id}/prescription")
def api_prescription_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Analyse de prescription des risques (lecture seule, consultatif).

    Délai de reprise de droit commun (pratique LPF CI) : risques du
    contribuable juridiquement prescrits (à basculer au statut
    « prescrit »), proches de la prescription (12 mois) et exercices
    encore reprenables. 404 si mission hors tenant.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.prescription_risques import (
        ErreurPrescriptionRisques,
        analyse_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        analyse = analyse_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurPrescriptionRisques as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_prescription_risques",
        charge_utile={
            "prescrits_a_basculer": analyse["synthese"][
                "prescrits_a_basculer"
            ],
            "exposition_prescrite": analyse["synthese"][
                "exposition_prescrite"
            ],
        },
    )
    return analyse


@router.get("/missions/{mission_id}/civisme-fiscal")
def api_civisme_fiscal_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Civisme fiscal — rapprochement échéancier / pièces collectées.

    Pour chaque échéance théorique de l'exercice revu : couverte par une
    pièce de la data room, en attente (future) ou manquante (passée non
    couverte). Consultatif et déterministe — l'application ne stocke pas
    les déclarations déposées. 404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.civisme_fiscal import (
        ErreurCivismeFiscal,
        analyse_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        analyse = analyse_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurCivismeFiscal as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_civisme_fiscal",
        charge_utile={
            "taux_civisme": analyse["synthese"]["taux_civisme"],
            "manquantes": analyse["synthese"]["manquantes"],
        },
    )
    return analyse


@router.get("/missions/{mission_id}/plan-actions")
def api_plan_actions_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Plan d'actions post-revue (lecture seule, consultatif).

    Pour chaque risque non clos du contribuable de la mission : une
    action suggérée déterministe (déclaration rectificative, provision à
    documenter, justificatif à collecter, point à discuter) avec
    priorité (haute si exposition élevée ou prescription proche) et
    synthèse. Le fiscaliste décide. 404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.plan_actions import (
        ErreurPlanActions,
        analyse_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        analyse = analyse_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurPlanActions as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_plan_actions",
        charge_utile={
            "total_actions": analyse["synthese"]["total_actions"],
            "priorite_haute": analyse["synthese"]["par_priorite"]["haute"],
            "exposition_totale": analyse["synthese"]["exposition_totale"],
        },
    )
    return analyse


class DeciderActionIn(BaseModel):
    """Décision du fiscaliste sur une action du plan d'actions."""

    decision: str
    note: str | None = None


@router.post(
    "/missions/{mission_id}/plan-actions/{cle_action}/decision"
)
def api_decider_action_plan(
    mission_id: int,
    cle_action: str,
    corps: DeciderActionIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Marque une action du plan « retenue », « écartée » ou « faite ».

    Décision HUMAINE persistée par-dessus le plan dérivé consultatif —
    clic explicite du fiscaliste, upsert (une nouvelle décision remplace
    la précédente). Décision invalide → 422 ; action inconnue du plan ou
    mission hors tenant → 404 (RLS) ; mission clôturée → 409.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.plan_actions import (
        ErreurPlanActionsDecisionInvalide,
        ErreurPlanActionsIntrouvable,
        ErreurPlanActionsMissionCloturee,
        analyse_mission,
        decider_action,
    )

    exiger_capacite(utilisateur, "executer_mission")
    try:
        action = decider_action(
            session,
            utilisateur.tenant_id,
            mission_id,
            cle_action,
            corps.decision,
            note=corps.note,
        )
    except ErreurPlanActionsIntrouvable as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ErreurPlanActionsMissionCloturee as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from e
    except ErreurPlanActionsDecisionInvalide as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="decision_plan_action",
        charge_utile={
            "cle_action": action["cle_action"],
            "decision": action["decision"],
            "type_action": action["type_action"],
            "risque_id": action["risque_id"],
        },
    )
    analyse = analyse_mission(session, utilisateur.tenant_id, mission_id)
    return {
        "action": action,
        "synthese": analyse["synthese"],
    }


@router.get("/missions/{mission_id}/bilan-cloture")
def api_bilan_cloture_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Bilan de pré-clôture (lecture seule, consultatif).

    Agrège les signaux existants de la mission (visas, temps saisis,
    demande de renseignements, note de synthèse, data room, risques
    ouverts) en points « ok » / « attention ». Jamais bloquant : la
    clôture reste à l'appréciation du fiscaliste. 404 si mission hors
    tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.bilan_cloture import (
        ErreurBilanCloture,
        bilan_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        bilan = bilan_mission(session, utilisateur.tenant_id, mission_id)
    except ErreurBilanCloture as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="consultation_bilan_cloture",
        charge_utile={
            "points_ok": bilan["synthese"]["points_ok"],
            "points_attention": bilan["synthese"]["points_attention"],
            "pret": bilan["synthese"]["pret"],
        },
    )
    return bilan


# ── Conclusions (validation humaine) ───────────────────────────────


class ConclusionPatchIn(BaseModel):
    statut: (
        Literal[
            "conforme",
            "anomalie",
            "sous_seuil",
            "non_verifiable",
            "hors_perimetre",
        ]
        | None
    ) = None
    piece_mission_id: int | None = None


def _http_erreur_conclusion(e: Exception) -> HTTPException:
    msg = str(e)
    code = (
        status.HTTP_404_NOT_FOUND
        if "introuvable" in msg
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=msg)


@router.get("/missions/{mission_id}/conclusions/{conclusion_id}")
def api_lire_conclusion(
    mission_id: int,
    conclusion_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Lecture d'une conclusion (tous rôles cabinet, y compris lecteur)."""
    from backend.plateforme.conclusions import ErreurConclusion, lire_conclusion

    try:
        return lire_conclusion(
            session,
            utilisateur.tenant_id,
            mission_id,
            conclusion_id,
        )
    except ErreurConclusion as e:
        raise _http_erreur_conclusion(e) from e


@router.patch("/missions/{mission_id}/conclusions/{conclusion_id}")
def api_patcher_conclusion(
    mission_id: int,
    conclusion_id: int,
    corps: ConclusionPatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Amendement humain : statut + rattachement pièce dossier."""
    from backend.plateforme.conclusions import ErreurConclusion, patcher_conclusion

    exiger_capacite(utilisateur, "executer_mission")
    payload = corps.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aucun champ fourni (statut ou piece_mission_id)",
        )
    try:
        return patcher_conclusion(
            session,
            utilisateur.tenant_id,
            mission_id,
            conclusion_id,
            acteur=utilisateur.email,
            **payload,
        )
    except ErreurConclusion as e:
        raise _http_erreur_conclusion(e) from e


@router.post("/missions/{mission_id}/conclusions/{conclusion_id}/validation")
def api_valider_conclusion(
    mission_id: int,
    conclusion_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Validation « 4 yeux » — second regard sur une conclusion évaluée."""
    from backend.plateforme.conclusions import ErreurConclusion, valider_conclusion

    exiger_capacite(utilisateur, "executer_mission")
    try:
        return valider_conclusion(
            session,
            utilisateur.tenant_id,
            mission_id,
            conclusion_id,
            validateur=utilisateur.email,
        )
    except ErreurConclusion as e:
        raise _http_erreur_conclusion(e) from e


MSG_POINT_OUVERT_GONE = (
    "point_ouvert écriture dépréciée après R4 — utiliser /api/v1/risques"
)


@router.post(
    "/missions/{mission_id}/conclusions/{conclusion_id}/point-ouvert",
    status_code=status.HTTP_410_GONE,
)
def api_point_ouvert_depuis_conclusion(
    mission_id: int,
    conclusion_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> None:
    """Gone — créer un risque via POST /risques (R4)."""
    del mission_id, conclusion_id, utilisateur, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=MSG_POINT_OUVERT_GONE,
    )


# ── Points ouverts (legacy lecture — hors calcul fiscal) ───────────
# GET encore consommé par le frontend ; POST/PATCH gardés en 410 pour
# signaler la migration vers /risques aux clients API existants.


@router.get("/points-ouverts")
def api_lister_points_ouverts(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    contribuable_id: int | None = None,
    statut: str | None = None,
    mission_source_id: int | None = None,
) -> list[dict]:
    """Lecture legacy `point_ouvert` (table conservée, RLS intacte)."""
    from backend.plateforme.points_ouverts import (
        ErreurPointOuvert,
        lister_points_ouverts,
    )

    try:
        return lister_points_ouverts(
            session,
            utilisateur.tenant_id,
            contribuable_id=contribuable_id,
            statut=statut,
            mission_source_id=mission_source_id,
        )
    except ErreurPointOuvert as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/points-ouverts", status_code=status.HTTP_410_GONE)
def api_creer_point_ouvert(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> None:
    """Gone — utiliser POST /api/v1/risques."""
    del utilisateur, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=MSG_POINT_OUVERT_GONE,
    )


@router.patch("/points-ouverts/{point_id}", status_code=status.HTTP_410_GONE)
def api_patcher_point_ouvert(
    point_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> None:
    """Gone — utiliser PATCH /api/v1/risques/{id}."""
    del point_id, utilisateur, session
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=MSG_POINT_OUVERT_GONE,
    )


# ── Registre risques (docs/25) ─────────────────────────────────────


class RisqueIn(BaseModel):
    contribuable_id: int
    impot: str
    libelle: str = Field(min_length=1, max_length=2000)
    exercice_origine: int = Field(ge=2000, le=2100)
    probabilite: Literal["probable", "possible", "faible"] = "possible"
    reference_legale: str | None = None
    montant_estime: float | None = None
    penalites_estimees: float | None = None
    origine_conclusion_id: int | None = None
    origine_mission_id: int | None = None
    origine_tache_id: int | None = None


class RisquePatchIn(BaseModel):
    statut: (
        Literal["ouvert", "en_traitement", "resolu", "accepte", "prescrit"]
        | None
    ) = None
    probabilite: Literal["probable", "possible", "faible"] | None = None
    motif_acceptation: str | None = None
    montant_estime: float | None = None
    penalites_estimees: float | None = None
    derniere_revue: str | None = None
    libelle: str | None = Field(default=None, min_length=1, max_length=2000)


@router.get("/risques")
def api_lister_risques(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    contribuable_id: int | None = None,
    statut: str | None = None,
    impot: str | None = None,
) -> list[dict]:
    from backend.plateforme.risques import ErreurRisque, lister_risques

    try:
        return lister_risques(
            session,
            utilisateur.tenant_id,
            contribuable_id=contribuable_id,
            statut=statut,
            impot=impot,
        )
    except ErreurRisque as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/contribuables/{contribuable_id}/risques")
def api_lister_risques_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    statut: str | None = None,
) -> list[dict]:
    from backend.plateforme.risques import ErreurRisque, lister_risques

    try:
        return lister_risques(
            session,
            utilisateur.tenant_id,
            contribuable_id=contribuable_id,
            statut=statut,
        )
    except ErreurRisque as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/contribuables/{contribuable_id}/risques/export.csv")
def api_exporter_risques_csv(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Registre des risques au format CSV Excel FR (UTF-8 BOM, « ; »)."""
    from backend.plateforme.risques import ErreurRisque, exporter_risques_csv

    try:
        nom, contenu = exporter_risques_csv(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurRisque as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/contribuables/{contribuable_id}/risques/rapport.pdf")
def api_rapport_risques_pdf(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Synthèse PDF des risques fiscaux du contribuable (tous exercices)."""
    from backend.plateforme.rapport_risques import (
        ErreurRapportRisques,
        exporter_rapport_risques_pdf,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        nom, contenu = exporter_rapport_risques_pdf(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurRapportRisques as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    return Response(
        content=contenu,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/contribuables/{contribuable_id}/risques/resume")
def api_resume_risques_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.risques import resume_risques_contribuable

    return resume_risques_contribuable(
        session, utilisateur.tenant_id, contribuable_id
    )


@router.get("/contribuables/{contribuable_id}/risques/score")
def api_score_risque_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.risques import score_risque_contribuable

    return score_risque_contribuable(
        session, utilisateur.tenant_id, contribuable_id
    )


@router.get("/contribuables/{contribuable_id}/provision-risques")
def api_provision_risques_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Provision pour risques fiscaux proposée (déterministe, SYSCOHADA).

    Risques ouverts « probables » provisionnés pénalités incluses ;
    « possibles » listés en passifs éventuels. Proposition indicative à
    valider par l'expert-comptable. 404 si fiche hors tenant (RLS).
    """
    from backend.plateforme.provision_risques import (
        ErreurProvisionRisques,
        calculer_provision,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return calculer_provision(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurProvisionRisques as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/contribuables/{contribuable_id}/historique")
def api_historique_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Vision pluriannuelle du contribuable (récurrence, prescription).

    Pour chaque exercice/mission : statut, exécutions, répartition des
    conclusions de la dernière exécution, montant des anomalies et
    tendance vs exercice précédent — plus les risques encore ouverts.
    Déterministe, lecture seule. 404 si fiche hors tenant (RLS).
    """
    from backend.plateforme.historique_contribuable import (
        ErreurHistoriqueContribuable,
        construire_historique,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return construire_historique(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurHistoriqueContribuable as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/contribuables/{contribuable_id}/comparaison-exercices")
def api_comparaison_exercices_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Comparaison inter-exercices N vs N-1 (registre des risques).

    Deux missions les plus récentes sur deux exercices distincts :
    risques encore ouverts nés de chaque mission, exposition par impôt,
    deltas et tendance (amélioration / dégradation / stable). Sans deux
    exercices revus : ``disponible = false`` avec la raison. Consultatif
    et déterministe. 404 si fiche hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.comparaison_exercices import (
        ErreurComparaisonExercices,
        comparaison_contribuable,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        comparaison = comparaison_contribuable(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurComparaisonExercices as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_comparaison_exercices",
        charge_utile={
            "contribuable_id": contribuable_id,
            "disponible": comparaison["disponible"],
            "tendance": (
                comparaison["synthese"]["tendance"]
                if comparaison["disponible"]
                else None
            ),
        },
    )
    return comparaison


# ── Data Room : mémoire client + timeline ──────────────────────────


class MemoireEntreeIn(BaseModel):
    type_entree: Literal["fait", "contexte", "alerte", "note"]
    contenu: str = Field(min_length=1, max_length=4000)


@router.get("/contribuables/{contribuable_id}/memoire")
def api_lister_memoire_client(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    type_entree: str | None = None,
) -> list[dict]:
    from backend.plateforme.memoire_client import (
        ErreurMemoireClient,
        lister_memoire,
    )

    try:
        return lister_memoire(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            type_entree=type_entree,
        )
    except ErreurMemoireClient as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post(
    "/contribuables/{contribuable_id}/memoire",
    status_code=status.HTTP_201_CREATED,
)
def api_ajouter_memoire_client(
    contribuable_id: int,
    corps: MemoireEntreeIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.moteur.journal import append_journal
    from backend.plateforme.memoire_client import (
        ErreurMemoireClient,
        ajouter_entree_memoire,
    )

    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        entree = ajouter_entree_memoire(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            type_entree=corps.type_entree,
            contenu=corps.contenu,
            source_type="manuel",
            auteur=utilisateur.email,
        )
    except ErreurMemoireClient as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="ajout_memoire_client",
        charge_utile={
            "contribuable_id": contribuable_id,
            "entree_id": entree["id"],
            "type_entree": entree["type_entree"],
        },
    )
    return entree


@router.delete("/contribuables/{contribuable_id}/memoire/{entree_id}")
def api_desactiver_memoire_client(
    contribuable_id: int,
    entree_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.moteur.journal import append_journal
    from backend.plateforme.memoire_client import (
        ErreurMemoireClient,
        desactiver_entree_memoire,
    )

    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        entree = desactiver_entree_memoire(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            entree_id,
        )
    except ErreurMemoireClient as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="retrait_memoire_client",
        charge_utile={
            "contribuable_id": contribuable_id,
            "entree_id": entree_id,
        },
    )
    return entree


@router.get("/contribuables/{contribuable_id}/timeline")
def api_timeline_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    limite: int = 50,
) -> list[dict]:
    from backend.plateforme.memoire_client import timeline_contribuable

    return timeline_contribuable(
        session, utilisateur.tenant_id, contribuable_id, limite=limite
    )


# ── Échéancier déclaratif indicatif (par régime fiscal) ────────────


@router.get("/contribuables/{contribuable_id}/echeancier")
def api_echeancier_contribuable(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Échéancier déclaratif indicatif du contribuable (90 jours).

    Référentiel indicatif (pratique usuelle CI) — ne remplace pas le
    calendrier officiel DGI. 404 si fiche hors tenant (RLS).
    """
    from datetime import date as _date

    from backend.abonne.service import ErreurAbonne, lire_contribuable
    from backend.plateforme.echeancier_fiscal import (
        HORIZON_JOURS_DEFAUT,
        prochaines_echeances,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        fiche = lire_contribuable(session, contribuable_id)
    except ErreurAbonne as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e

    regime = fiche.get("regime_fiscal")
    mois_cloture = fiche.get("mois_cloture")
    reference = _date.today()
    return {
        "contribuable_id": contribuable_id,
        "regime": regime,
        "mois_cloture": mois_cloture,
        "reference": reference.isoformat(),
        "horizon_jours": HORIZON_JOURS_DEFAUT,
        "indicatif": True,
        "echeances": prochaines_echeances(
            regime,
            reference,
            horizon_jours=HORIZON_JOURS_DEFAUT,
            mois_cloture=mois_cloture,
        ),
    }


# ── Data Room : synthèse IA client ─────────────────────────────────


@router.post(
    "/contribuables/{contribuable_id}/syntheses",
    status_code=status.HTTP_201_CREATED,
)
def api_generer_synthese_client(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.moteur.journal import append_journal
    from backend.plateforme.memoire_client import alimenter_memoire
    from backend.plateforme.synthese_client import (
        ErreurSyntheseClient,
        generer_synthese,
    )

    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        synthese = generer_synthese(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            auteur=utilisateur.email,
        )
    except ErreurSyntheseClient as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="generation_synthese_client",
        charge_utile={
            "contribuable_id": contribuable_id,
            "synthese_id": synthese["id"],
            "version": synthese["version"],
            "statut": synthese["statut"],
        },
    )
    if synthese["statut"] == "disponible":
        resume = str((synthese.get("contenu") or {}).get("resume") or "")
        contenu_memoire = (
            f"Synthèse IA v{synthese['version']} générée"
            + (f" — {resume}" if resume else "")
        )[:4000]
        alimenter_memoire(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            type_entree="contexte",
            contenu=contenu_memoire,
            source_type="synthese",
            source_ref=f"synthese:{synthese['id']}",
        )
    return synthese


@router.get("/contribuables/{contribuable_id}/syntheses")
def api_lister_syntheses_client(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.synthese_client import lister_syntheses

    return lister_syntheses(
        session, utilisateur.tenant_id, contribuable_id
    )


@router.get("/contribuables/{contribuable_id}/syntheses/{synthese_id}")
def api_obtenir_synthese_client(
    contribuable_id: int,
    synthese_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.synthese_client import (
        ErreurSyntheseClient,
        obtenir_synthese,
    )

    try:
        return obtenir_synthese(
            session,
            utilisateur.tenant_id,
            contribuable_id,
            synthese_id,
        )
    except ErreurSyntheseClient as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# ── Note de synthèse de mission (executive summary IA) ────────────


@router.post(
    "/missions/{mission_id}/note-synthese",
    status_code=status.HTTP_201_CREATED,
)
def api_generer_note_synthese(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Génère une nouvelle version de la note de synthèse de mission.

    Anti-rafale : refusée (409) si une génération est déjà en cours.
    404 si mission hors tenant (RLS).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.note_synthese import (
        ErreurNoteSynthese,
        generer_note,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        note = generer_note(
            session,
            utilisateur.tenant_id,
            mission_id,
            auteur=utilisateur.email,
        )
    except ErreurNoteSynthese as e:
        msg = str(e)
        if "introuvable" in msg:
            code = status.HTTP_404_NOT_FOUND
        elif "déjà en cours" in msg:
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="generation_note_synthese",
        charge_utile={
            "note_id": note["id"],
            "version": note["version"],
            "statut": note["statut"],
        },
    )
    return note


@router.get("/missions/{mission_id}/notes-synthese")
def api_lister_notes_synthese(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.note_synthese import (
        ErreurNoteSynthese,
        lister_notes,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return lister_notes(session, utilisateur.tenant_id, mission_id)
    except ErreurNoteSynthese as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/missions/{mission_id}/notes-synthese/{version}")
def api_obtenir_note_synthese(
    mission_id: int,
    version: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.note_synthese import (
        ErreurNoteSynthese,
        obtenir_note,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return obtenir_note(
            session, utilisateur.tenant_id, mission_id, version
        )
    except ErreurNoteSynthese as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


# ── Comparatif entre deux exécutions d'une mission ─────────────────


@router.get("/missions/{mission_id}/comparatif-executions")
def api_comparatif_executions(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    execution_a: int | None = None,
    execution_b: int | None = None,
) -> dict:
    """Comparatif déterministe entre deux exécutions (défaut : N-1 → N).

    404 si mission hors tenant (RLS) ou exécution inconnue de la mission ;
    409 si la mission compte moins de deux exécutions.
    """
    from backend.plateforme.comparatif_executions import (
        ErreurComparatifExecutions,
        comparer_executions,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return comparer_executions(
            session,
            utilisateur.tenant_id,
            mission_id,
            execution_a=execution_a,
            execution_b=execution_b,
        )
    except ErreurComparatifExecutions as e:
        msg = str(e)
        if "introuvable" in msg:
            code = status.HTTP_404_NOT_FOUND
        elif "au moins deux exécutions" in msg:
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from e


# ── Commentaire IA de revue analytique ─────────────────────────────


@router.post(
    "/missions/{mission_id}/commentaire-analytique",
    status_code=status.HTTP_201_CREATED,
)
def api_generer_commentaire_analytique(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Génère une nouvelle version du commentaire de revue analytique.

    Anti-rafale : refusée (409) si une génération est déjà en cours.
    404 si mission hors tenant (RLS) ; 400 si revue indisponible.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.commentaire_analytique import (
        ErreurCommentaireAnalytique,
        generer_commentaire,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        commentaire = generer_commentaire(
            session,
            utilisateur.tenant_id,
            mission_id,
            auteur=utilisateur.email,
        )
    except ErreurCommentaireAnalytique as e:
        msg = str(e)
        if "introuvable" in msg:
            code = status.HTTP_404_NOT_FOUND
        elif "déjà en cours" in msg:
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="generation_commentaire_analytique",
        charge_utile={
            "commentaire_id": commentaire["id"],
            "version": commentaire["version"],
            "statut": commentaire["statut"],
        },
    )
    return commentaire


@router.get("/missions/{mission_id}/commentaires-analytiques")
def api_lister_commentaires_analytiques(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.commentaire_analytique import (
        ErreurCommentaireAnalytique,
        lister_commentaires,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return lister_commentaires(session, utilisateur.tenant_id, mission_id)
    except ErreurCommentaireAnalytique as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/missions/{mission_id}/commentaires-analytiques/{version}")
def api_obtenir_commentaire_analytique(
    mission_id: int,
    version: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.commentaire_analytique import (
        ErreurCommentaireAnalytique,
        obtenir_commentaire,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return obtenir_commentaire(
            session, utilisateur.tenant_id, mission_id, version
        )
    except ErreurCommentaireAnalytique as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.post("/risques", status_code=status.HTTP_201_CREATED)
def api_creer_risque(
    corps: RisqueIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from decimal import Decimal

    from backend.plateforme.risques import ErreurRisque, creer_risque

    exiger_capacite(utilisateur, "creer_mission")
    try:
        return creer_risque(
            session,
            utilisateur.tenant_id,
            contribuable_id=corps.contribuable_id,
            impot=corps.impot,
            libelle=corps.libelle,
            exercice_origine=corps.exercice_origine,
            probabilite=corps.probabilite,
            reference_legale=corps.reference_legale,
            montant_estime=(
                Decimal(str(corps.montant_estime))
                if corps.montant_estime is not None
                else None
            ),
            penalites_estimees=(
                Decimal(str(corps.penalites_estimees))
                if corps.penalites_estimees is not None
                else None
            ),
            origine_conclusion_id=corps.origine_conclusion_id,
            origine_mission_id=corps.origine_mission_id,
            origine_tache_id=corps.origine_tache_id,
        )
    except ErreurRisque as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/risques/{risque_id}")
def api_lire_risque(
    risque_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.risques import ErreurRisque, lire_risque

    try:
        return lire_risque(session, utilisateur.tenant_id, risque_id)
    except ErreurRisque as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.patch("/risques/{risque_id}")
def api_patcher_risque(
    risque_id: int,
    corps: RisquePatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.risques import ErreurRisque, patcher_risque

    exiger_capacite(utilisateur, "creer_mission")
    payload = corps.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aucun champ fourni",
        )
    try:
        return patcher_risque(
            session,
            utilisateur.tenant_id,
            risque_id,
            acteur=utilisateur.email,
            **payload,
        )
    except ErreurRisque as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e


# ── Preuves de résolution des risques (verdict IA consultatif) ─────


class ResolutionRisqueIn(BaseModel):
    preuve_id: int
    motif_forcage: str | None = Field(default=None, max_length=2000)


@router.post(
    "/risques/{risque_id}/preuves",
    status_code=status.HTTP_201_CREATED,
)
async def api_deposer_preuve_resolution(
    risque_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    fichier: Annotated[UploadFile, File(...)],
) -> dict:
    """Dépose le justificatif puis l'analyse (synchrone, consultatif)."""
    from backend.moteur.journal import append_journal
    from backend.plateforme.preuve_resolution import (
        ErreurPreuveResolution,
        analyser_preuve,
        enregistrer_preuve,
    )

    exiger_capacite(utilisateur, "ecrire_contribuable")
    brut = await fichier.read()
    try:
        preuve = enregistrer_preuve(
            session,
            utilisateur.tenant_id,
            risque_id,
            nom_fichier=fichier.filename or "preuve",
            content_type=fichier.content_type,
            brut=brut,
            auteur=utilisateur.email,
        )
    except ErreurPreuveResolution as e:
        msg = str(e)
        if "introuvable" in msg:
            code = status.HTTP_404_NOT_FOUND
        elif "volumineux" in msg:
            code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from e
    preuve = analyser_preuve(
        session, utilisateur.tenant_id, int(preuve["id"])
    )
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="depot_preuve_resolution",
        charge_utile={
            "risque_id": risque_id,
            "preuve_id": preuve["id"],
            "verdict_ia": preuve.get("verdict_ia"),
        },
    )
    return preuve


@router.get("/risques/{risque_id}/preuves")
def api_lister_preuves_resolution(
    risque_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.preuve_resolution import (
        ErreurPreuveResolution,
        lister_preuves,
    )

    try:
        return lister_preuves(session, utilisateur.tenant_id, risque_id)
    except ErreurPreuveResolution as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/risques/{risque_id}/resolution")
def api_resoudre_risque_avec_preuve(
    risque_id: int,
    corps: ResolutionRisqueIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.moteur.journal import append_journal
    from backend.plateforme.preuve_resolution import (
        ErreurPreuveResolution,
        resoudre_risque_avec_preuve,
    )
    from backend.plateforme.risques import ErreurRisque

    exiger_capacite(utilisateur, "ecrire_contribuable")
    try:
        resultat = resoudre_risque_avec_preuve(
            session,
            utilisateur.tenant_id,
            risque_id,
            preuve_id=corps.preuve_id,
            acteur=utilisateur.email,
            motif_forcage=corps.motif_forcage,
        )
    except (ErreurPreuveResolution, ErreurRisque) as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="resolution_risque_avec_preuve",
        charge_utile={
            "risque_id": risque_id,
            "preuve_id": corps.preuve_id,
            "verdict_ia": (resultat.get("preuve") or {}).get("verdict_ia"),
            "decision": (resultat.get("preuve") or {}).get("decision"),
        },
    )
    return resultat


class ActionRisqueIn(BaseModel):
    nature: Literal["corrective", "preventive"]
    libelle: str = Field(min_length=1, max_length=2000)
    responsable_user_id: int | None = None
    responsable_label: str | None = None
    echeance: str | None = None


class ActionRisquePatchIn(BaseModel):
    statut: (
        Literal[
            "proposee",
            "acceptee",
            "refusee",
            "en_cours",
            "preuve_deposee",
            "verifiee",
            "close",
            "abandonnee",
        ]
        | None
    ) = None
    motif_refus: str | None = None
    preuve_piece_id: int | None = None
    preuve_uri: str | None = None
    responsable_user_id: int | None = None
    responsable_label: str | None = None
    echeance: str | None = None
    libelle: str | None = Field(default=None, min_length=1, max_length=2000)


@router.get("/risques/{risque_id}/actions")
def api_lister_actions_risque(
    risque_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.actions_risque import (
        ErreurActionRisque,
        lister_actions_risque,
    )

    try:
        return lister_actions_risque(
            session, utilisateur.tenant_id, risque_id
        )
    except ErreurActionRisque as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/risques/{risque_id}/actions",
    status_code=status.HTTP_201_CREATED,
)
def api_creer_action_risque(
    risque_id: int,
    corps: ActionRisqueIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from datetime import date

    from backend.plateforme.actions_risque import (
        ErreurActionRisque,
        creer_action_risque,
    )

    exiger_capacite(utilisateur, "creer_mission")
    ech = None
    if corps.echeance:
        ech = date.fromisoformat(corps.echeance[:10])
    try:
        return creer_action_risque(
            session,
            utilisateur.tenant_id,
            risque_id,
            nature=corps.nature,
            libelle=corps.libelle,
            responsable_user_id=corps.responsable_user_id,
            responsable_label=corps.responsable_label,
            echeance=ech,
        )
    except ErreurActionRisque as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/actions-risque/retards")
def api_lister_actions_retards(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.actions_risque import lister_actions_en_retard

    return lister_actions_en_retard(session, utilisateur.tenant_id)


@router.patch("/actions-risque/{action_id}")
def api_patcher_action_risque(
    action_id: int,
    corps: ActionRisquePatchIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.plateforme.actions_risque import (
        ErreurActionRisque,
        patcher_action_risque,
    )

    exiger_capacite(utilisateur, "creer_mission")
    payload = corps.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="aucun champ fourni",
        )
    try:
        return patcher_action_risque(
            session,
            utilisateur.tenant_id,
            action_id,
            acteur=utilisateur.email,
            **payload,
        )
    except ErreurActionRisque as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e


# ── Pont Data Room → mission : source active depuis une pièce ──────


@router.get("/contribuables/{contribuable_id}/pieces-tabulaires")
def api_lister_pieces_tabulaires(
    contribuable_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> list[dict]:
    from backend.plateforme.source_depuis_piece import (
        ErreurSourceDepuisPiece,
        lister_pieces_tabulaires,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return lister_pieces_tabulaires(
            session, utilisateur.tenant_id, contribuable_id
        )
    except ErreurSourceDepuisPiece as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


class SourceDepuisPieceIn(BaseModel):
    piece_id: int = Field(ge=1)
    type_piece: (
        Literal["balance", "etats_financiers", "grand_livre", "fec"] | None
    ) = None
    confirmer: bool = False


@router.post("/missions/{mission_id}/source-depuis-piece")
def api_source_depuis_piece(
    mission_id: int,
    corps: SourceDepuisPieceIn,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    from backend.moteur.journal import append_journal
    from backend.plateforme.memoire_client import alimenter_memoire
    from backend.plateforme.source_depuis_piece import (
        ErreurSourceDepuisPiece,
        importer_source_depuis_piece,
    )
    from backend.socle.erreurs import (
        ErreurFiabilisation,
        ErreurLectureBalance,
        ErreurPiece,
    )

    exiger_capacite(utilisateur, "importer_balance")
    try:
        piece, out = importer_source_depuis_piece(
            session,
            utilisateur.tenant_id,
            mission_id,
            piece_id=corps.piece_id,
            type_piece=corps.type_piece,
            confirmer=corps.confirmer,
        )
    except ErreurSourceDepuisPiece as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "introuvable" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from e
    except ErreurFiabilisation as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    except ErreurLectureBalance as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except ErreurPiece as e:
        code = (
            status.HTTP_409_CONFLICT
            if "déjà définie" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(e)) from e

    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=mission_id,
        acteur=utilisateur.email,
        action="source_mission_depuis_piece",
        charge_utile={
            "piece_id": corps.piece_id,
            "nom_fichier": piece["nom_fichier"],
            "type_piece": out.piece.type_piece if out.piece else corps.type_piece,
            "statut": out.rapport.statut,
            "nb_comptes": out.rapport.nb_comptes,
        },
    )
    if out.rapport.statut == "ok":
        alimenter_memoire(
            session,
            utilisateur.tenant_id,
            int(piece["contribuable_id"]),
            type_entree="contexte",
            contenu=(
                f"Source comptable de la mission #{mission_id} alimentée "
                f"depuis la pièce « {piece['nom_fichier']} » du Data Room"
            ),
            source_type="mission",
            source_ref=f"mission:{mission_id}:piece:{corps.piece_id}",
        )
    return out.model_dump(mode="json")


@router.get("/missions/{mission_id}/revue-analytique")
def api_revue_analytique_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Revue analytique N / N-1 — comparaison des soldes avec l'exercice
    précédent du même contribuable (lecture seule, jamais bloquant).

    disponible=false si pas de mission N-1 ou pas de soldes comparables.
    """
    from backend.plateforme.revue_analytique import (
        ErreurRevueAnalytique,
        revue_analytique_mission,
    )

    exiger_capacite(utilisateur, "lire")
    try:
        return revue_analytique_mission(
            session, utilisateur.tenant_id, mission_id
        )
    except ErreurRevueAnalytique as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.get("/missions/{mission_id}/controles-fec")
def api_controles_fec_mission(
    mission_id: int,
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Contrôles de vraisemblance FEC de la source active (informationnels).

    Dernier jeu enregistré au moment de l'import — jamais bloquant.
    disponible=false si la mission n'a pas de source FEC contrôlée.
    """
    from backend.plateforme.contexte import contexte_tenant
    from backend.socle import depot

    exiger_capacite(utilisateur, "lire")
    with contexte_tenant(session, utilisateur.tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"mission {mission_id} introuvable pour ce tenant",
            )
        dernier = depot.derniers_controles_fec(session, mission_id)
    if dernier is None:
        return {"disponible": False, "controles": [], "cree_le": None}
    return {
        "disponible": True,
        "exercice": int(dernier["exercice"]),
        "controles": dernier["controles"],
        "cree_le": dernier["cree_le"].isoformat()
        if dernier["cree_le"] is not None
        else None,
    }


@router.get("/pilotage")
def api_pilotage_portefeuille(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Cockpit associé — pilotage du portefeuille (lecture seule).

    Quatre volets : exposition ouverte par client, missions en cours
    inactives > 30 jours, alertes fiabilité des sources FEC et risques
    en retard de traitement. Tout est calculé sous contexte_tenant.
    """
    from backend.plateforme.pilotage import pilotage_portefeuille

    exiger_capacite(utilisateur, "lire")
    return pilotage_portefeuille(session, utilisateur.tenant_id)


@router.get("/pilotage/supervision")
def api_supervision_cabinet(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Supervision transverse des missions actives (lecture seule).

    Pour chaque mission non clôturée du tenant : temps cumulés, visas
    de supervision (phases complètes, restitution), circularisation en
    attente / à relancer et alertes courtes — plus une synthèse cabinet.
    """
    from backend.plateforme.supervision_cabinet import construire_supervision

    exiger_capacite(utilisateur, "lire")
    return construire_supervision(session, utilisateur.tenant_id)


@router.get("/cabinet/agenda-fiscal")
def api_agenda_fiscal_cabinet(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    jours: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict:
    """Agenda fiscal du cabinet — échéances à venir des missions actives.

    Vue transverse pour le fiscaliste : sur toutes les missions non
    clôturées du tenant, les échéances fiscales dont la date limite
    tombe dans la fenêtre à venir (``jours``, 1 à 90, défaut 30),
    marquées « couverte » (une pièce de la data room correspond) ou
    « à préparer ». Consultatif et déterministe — trié par date limite.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.agenda_cabinet import agenda_cabinet

    exiger_capacite(utilisateur, "lire")
    agenda = agenda_cabinet(session, utilisateur.tenant_id, jours=jours)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_agenda_cabinet",
        charge_utile={
            "jours": agenda["jours"],
            "total": agenda["synthese"]["total"],
            "a_preparer": agenda["synthese"]["a_preparer"],
        },
    )
    return agenda


@router.get("/cabinet/agenda-fiscal.ics")
def api_agenda_fiscal_cabinet_ics(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    jours: Annotated[int, Query(ge=1, le=90)] = 30,
) -> Response:
    """Export iCalendar (RFC 5545) de l'agenda fiscal du cabinet.

    Mêmes échéances que ``GET /cabinet/agenda-fiscal`` (fenêtre
    ``jours``, 1 à 90, défaut 30) au format ``text/calendar`` : un
    événement journée entière par échéance, importable dans tout
    agenda (Outlook, Google Agenda…). Déterministe — UID stables.
    """
    from datetime import date as _date

    from backend.moteur.journal import append_journal
    from backend.plateforme.agenda_cabinet import agenda_cabinet, generer_ics

    exiger_capacite(utilisateur, "lire")
    agenda = agenda_cabinet(session, utilisateur.tenant_id, jours=jours)
    contenu = generer_ics(
        agenda["echeances"], _date.fromisoformat(agenda["aujourd_hui"])
    )
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_agenda_cabinet_ics",
        charge_utile={
            "jours": agenda["jours"],
            "total": agenda["synthese"]["total"],
        },
    )
    return Response(
        content=contenu,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="agenda-fiscal.ics"'
        },
    )


@router.get("/cabinet/agenda-fiscal.csv")
def api_agenda_fiscal_cabinet_csv(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
    jours: Annotated[int, Query(ge=1, le=90)] = 30,
) -> Response:
    """Export CSV (Excel FR, séparateur « ; ») de l'agenda fiscal.

    Mêmes échéances que ``GET /cabinet/agenda-fiscal`` (fenêtre
    ``jours``, 1 à 90, défaut 30) au format ``text/csv`` : une ligne
    par échéance, encodage UTF-8 précédé d'un BOM pour une ouverture
    directe dans Excel. Déterministe — même tri que l'agenda.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.agenda_cabinet import agenda_cabinet, generer_csv

    exiger_capacite(utilisateur, "lire")
    agenda = agenda_cabinet(session, utilisateur.tenant_id, jours=jours)
    contenu = "\ufeff" + generer_csv(agenda)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_agenda_cabinet_csv",
        charge_utile={
            "jours": agenda["jours"],
            "total": agenda["synthese"]["total"],
        },
    )
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="agenda-fiscal.csv"'
        },
    )


@router.get("/cabinet/relances")
def api_relances_cabinet(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Relances à faire du cabinet — items du suivi échus, tous clients.

    Vue transverse pour le fiscaliste : sur toutes les missions non
    clôturées du tenant, les items du suivi de la demande de
    renseignements « à relancer » (statut ``en_attente`` et date de
    relance échue). Consultatif et déterministe — trié par date de
    relance croissante puis client.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.relances_cabinet import relances_cabinet

    exiger_capacite(utilisateur, "lire")
    relances = relances_cabinet(session, utilisateur.tenant_id)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_relances_cabinet",
        charge_utile={
            "total": relances["total"],
            "clients": relances["synthese"]["clients"],
        },
    )
    return relances


@router.get("/cabinet/relances.csv")
def api_relances_cabinet_csv(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Export CSV (Excel FR, séparateur « ; ») des relances à faire.

    Mêmes items que ``GET /cabinet/relances`` au format ``text/csv`` :
    une ligne par relance échue, encodage UTF-8 précédé d'un BOM pour
    une ouverture directe dans Excel. Déterministe — même tri que la
    liste des relances.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.relances_cabinet import (
        generer_csv,
        relances_cabinet,
    )

    exiger_capacite(utilisateur, "lire")
    relances = relances_cabinet(session, utilisateur.tenant_id)
    contenu = "\ufeff" + generer_csv(relances)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_relances_cabinet_csv",
        charge_utile={
            "total": relances["total"],
            "clients": relances["synthese"]["clients"],
        },
    )
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="relances.csv"'
        },
    )


@router.get("/cabinet/actions-retenues")
def api_actions_retenues_cabinet(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> dict:
    """Actions à mettre en œuvre du cabinet — retenues, tous clients.

    Vue transverse pour le fiscaliste : sur toutes les missions du
    tenant, les actions du plan d'actions marquées « retenue » (non
    encore faites ni écartées), avec le risque d'origine et l'exposition
    totale en jeu. Consultatif et déterministe — trié par exposition
    décroissante puis client.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.actions_cabinet import actions_retenues_cabinet

    exiger_capacite(utilisateur, "lire")
    actions = actions_retenues_cabinet(session, utilisateur.tenant_id)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_actions_retenues_cabinet",
        charge_utile={
            "total": actions["total"],
            "clients": actions["synthese"]["clients"],
            "exposition_totale": actions["synthese"]["exposition_totale"],
        },
    )
    return actions


@router.get("/cabinet/actions-retenues.csv")
def api_actions_retenues_cabinet_csv(
    utilisateur: UtilisateurDep,
    session: Annotated[Session, Depends(session_abonne)],
) -> Response:
    """Export CSV (Excel FR, séparateur « ; ») des actions retenues.

    Mêmes items que ``GET /cabinet/actions-retenues`` au format
    ``text/csv`` : une ligne par action retenue à mettre en œuvre,
    encodage UTF-8 précédé d'un BOM pour une ouverture directe dans
    Excel. Déterministe — même tri que la liste des actions.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.actions_cabinet import (
        actions_retenues_cabinet,
        generer_csv,
    )

    exiger_capacite(utilisateur, "lire")
    actions = actions_retenues_cabinet(session, utilisateur.tenant_id)
    contenu = "\ufeff" + generer_csv(actions)
    append_journal(
        session,
        tenant_id=utilisateur.tenant_id,
        mission_id=None,
        acteur=utilisateur.email,
        action="consultation_actions_retenues_cabinet_csv",
        charge_utile={
            "total": actions["total"],
            "clients": actions["synthese"]["clients"],
            "exposition_totale": actions["synthese"]["exposition_totale"],
        },
    )
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="actions-retenues.csv"'
            )
        },
    )
