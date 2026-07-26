"""Routes plateforme : provisionnement, auth, sante tenant."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
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
    points_ouverts_crees: int = 0
    risques_crees: int = 0


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
    return MissionStatutOut(**r)


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
