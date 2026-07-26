"""Creation de missions avec epinglage de la version publiee."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.provisionnement import derniere_version_publiee
from backend.plateforme.quotas import ErreurQuota, verifier_et_incrementer_quota
from backend.profil.service import ErreurProfil, valider_profil

# Cycle de vie dossier (pas de droit fiscal ici).
STATUT_CADRAGE: Final = "cadrage"
STATUT_EN_COURS: Final = "en_cours"
STATUT_CLOTUREE: Final = "cloturee"

STATUTS_MISSION: Final[frozenset[str]] = frozenset(
    {STATUT_CADRAGE, STATUT_EN_COURS, STATUT_CLOTUREE}
)

# Transitions autorisées (PATCH manuel). L'exécution force cadrage → en_cours.
TRANSITIONS_STATUT: Final[dict[str, frozenset[str]]] = {
    STATUT_CADRAGE: frozenset({STATUT_EN_COURS}),
    STATUT_EN_COURS: frozenset({STATUT_CLOTUREE}),
    STATUT_CLOTUREE: frozenset({STATUT_EN_COURS}),  # réouverture
}

# Contexte d'engagement — UX / rapport, aucune formule fiscale.
TYPES_ENGAGEMENT: Final[frozenset[str]] = frozenset(
    {
        "preventive",
        "cac",
        "due_diligence",
        "assistance_controle",
        "autre",
    }
)

LIBELLES_ENGAGEMENT: Final[dict[str, str]] = {
    "preventive": "Revue préventive",
    "cac": "Commissariat aux comptes",
    "due_diligence": "Due diligence",
    "assistance_controle": "Assistance à contrôle",
    "autre": "Autre",
}

# Taxonomie pivot `impot` (docs/02-format-pivot.md) — pas de barème inventé.
CODES_IMPOT: Final[tuple[str, ...]] = (
    "BIC",
    "TVA",
    "RAS",
    "ITS",
    "CE",
    "IRC",
    "IRVM",
    "PAT",
    "FONC",
    "ENR",
    "TIMBRE",
    "OBL",
    "OBNL",
    "RA",
)
CODES_IMPOT_SET: Final[frozenset[str]] = frozenset(CODES_IMPOT)

# Champs de cadrage gelés dès statut ≠ cadrage.
CHAMPS_CADRAGE_GELES: Final[frozenset[str]] = frozenset(
    {
        "type_engagement",
        "perimetre_impots",
        "exclusions_declarees",
        "seuil_signification",
        "objectifs",
        "objectifs_fiscaux",
    }
)


class ErreurMission(Exception):
    """Echec de creation de mission."""


class QuotaEpuise(ErreurMission):
    """Quota missions atteint — mapped to HTTP 403."""


class ErreurMissionDoublon(ErreurMission):
    """Mission active déjà existante pour ce client / exercice — HTTP 409."""


def valider_type_engagement(valeur: object | None) -> str:
    """Normalise et valide le type d'engagement."""
    if valeur is None:
        return "autre"
    texte = str(valeur).strip().lower()
    if texte not in TYPES_ENGAGEMENT:
        raise ErreurMission(
            f"type_engagement invalide {valeur!r} — attendu : "
            + ", ".join(sorted(TYPES_ENGAGEMENT))
        )
    return texte


def valider_perimetre_impots(valeur: object | None) -> list[str] | None:
    """NULL = tous les impôts ; liste non vide = filtre ; [] refusé."""
    if valeur is None:
        return None
    if not isinstance(valeur, (list, tuple)):
        raise ErreurMission(
            "perimetre_impots doit être null ou une liste de codes impot"
        )
    if len(valeur) == 0:
        raise ErreurMission(
            "perimetre_impots vide [] est ambigu — utilisez null (tous) "
            "ou une liste non vide de codes pivot"
        )
    vus: list[str] = []
    for brut in valeur:
        code = str(brut).strip().upper()
        if code not in CODES_IMPOT_SET:
            raise ErreurMission(
                f"code impot invalide {brut!r} — attendu : "
                + ", ".join(CODES_IMPOT)
            )
        if code not in vus:
            vus.append(code)
    return vus


def valider_seuil_signification(valeur: object | None) -> Decimal | None:
    """Seuil cabinet (FCFA) — NULL autorisé ; jamais un barème CGI."""
    if valeur is None or valeur == "":
        return None
    try:
        montant = Decimal(str(valeur))
    except (InvalidOperation, ValueError) as e:
        raise ErreurMission(
            f"seuil_signification invalide {valeur!r}"
        ) from e
    if montant < 0:
        raise ErreurMission("seuil_signification ne peut pas être négatif")
    return montant


def normaliser_perimetre_lu(brut: object | None) -> list[str] | None:
    """Lit JSONB / liste déjà parsée depuis Postgres (sans rejeter [])."""
    if brut is None:
        return None
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except json.JSONDecodeError:
            return None
    if isinstance(brut, (list, tuple)):
        codes = [str(x).strip().upper() for x in brut if str(x).strip()]
        return codes or None
    return None


def serialiser_mission(
    row: dict[str, Any],
    *,
    objectifs: list[dict[str, Any]] | None = None,
    objectifs_fiscaux: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalise une ligne mission pour l'API."""
    perimetre = normaliser_perimetre_lu(row.get("perimetre_impots"))
    type_eng = str(row.get("type_engagement") or "autre")
    seuil = row.get("seuil_signification")
    out: dict[str, Any] = {
        "id": int(row["id"]),
        "contribuable_id": int(row["contribuable_id"])
        if row.get("contribuable_id") is not None
        else None,
        "exercice": int(row["exercice"]) if row.get("exercice") is not None else None,
        "statut": str(row.get("statut") or STATUT_CADRAGE),
        "version_referentiel_id": (
            int(row["version_referentiel_id"])
            if row.get("version_referentiel_id") is not None
            else None
        ),
        "type_engagement": type_eng,
        "type_engagement_libelle": LIBELLES_ENGAGEMENT.get(type_eng, type_eng),
        "perimetre_impots": perimetre,
        "revue_partielle": perimetre is not None,
        "exclusions_declarees": row.get("exclusions_declarees"),
        "seuil_signification": (
            str(seuil) if seuil is not None else None
        ),
        "objectifs": list(objectifs) if objectifs is not None else [],
        "objectifs_fiscaux": (
            list(objectifs_fiscaux) if objectifs_fiscaux is not None else []
        ),
    }
    if "contribuable_denomination" in row:
        out["contribuable_denomination"] = row["contribuable_denomination"]
    if "cree_le" in row:
        cree = row["cree_le"]
        out["cree_le"] = cree.isoformat() if hasattr(cree, "isoformat") else cree
    if "profil" in row:
        profil = row["profil"]
        if isinstance(profil, str):
            try:
                profil = json.loads(profil)
            except json.JSONDecodeError:
                profil = {}
        out["profil"] = profil if isinstance(profil, dict) else {}
    return out


def creer_mission(
    session: Session,
    tenant_id: int,
    *,
    contribuable_id: int,
    exercice: int,
    profil: dict[str, Any],
    type_engagement: str | None = None,
    perimetre_impots: list[str] | None = None,
    exclusions_declarees: str | None = None,
    seuil_signification: object | None = None,
    objectifs: object | None = None,
) -> int:
    """Cree une mission epinglee sur la derniere version publiee.

    Incremente le quota du mois. Leve QuotaEpuise si epuise.
    Leve ErreurMission s il n existe aucune version publiee.
    """
    from backend.plateforme.objectifs import (
        ErreurObjectif,
        remplacer_objectifs_mission,
    )

    try:
        profil_ok = valider_profil(profil)
    except ErreurProfil as e:
        raise ErreurMission(str(e)) from e

    annee_courante = date.today().year
    if int(exercice) > annee_courante:
        raise ErreurMission(
            f"L'exercice {exercice} n'est pas encore clos — une revue fiscale "
            "porte sur un exercice achevé."
        )

    type_ok = valider_type_engagement(type_engagement)
    perimetre_ok = valider_perimetre_impots(perimetre_impots)
    seuil_ok = valider_seuil_signification(seuil_signification)
    exclusions = (exclusions_declarees or "").strip() or None

    version_id = derniere_version_publiee(session)
    if version_id is None:
        raise ErreurMission(
            "aucune version de referentiel publiee — impossible d epingler la mission"
        )

    with contexte_tenant(session, tenant_id):
        try:
            verifier_et_incrementer_quota(session, tenant_id)
        except ErreurQuota as e:
            raise QuotaEpuise(str(e)) from e

        contrib = session.execute(
            text("SELECT id, denomination FROM contribuable WHERE id = :c"),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contrib is None:
            raise ErreurMission(f"contribuable {contribuable_id} introuvable")
        denomination = str(contrib["denomination"] or f"client #{contribuable_id}")

        doublon = session.execute(
            text(
                "SELECT id FROM mission "
                "WHERE contribuable_id = :c AND exercice = :e AND statut <> :cl "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"c": contribuable_id, "e": exercice, "cl": STATUT_CLOTUREE},
        ).scalar_one_or_none()
        if doublon is not None:
            raise ErreurMissionDoublon(
                f"Une mission existe déjà pour « {denomination} » sur "
                f"l'exercice {exercice} (mission #{doublon}). "
                "Ouvrez-la depuis l'onglet Missions."
            )

        try:
            mission_id = session.execute(
                text(
                    "INSERT INTO mission "
                    "(tenant_id, contribuable_id, exercice, profil, version_referentiel_id, "
                    "statut, type_engagement, perimetre_impots, exclusions_declarees, "
                    "seuil_signification) "
                    "VALUES (:t, :c, :e, CAST(:p AS jsonb), :v, :s, :te, "
                    "CAST(:pi AS jsonb), :ex, :seuil) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "e": exercice,
                    "p": json.dumps(profil_ok, ensure_ascii=False),
                    "v": version_id,
                    "s": STATUT_CADRAGE,
                    "te": type_ok,
                    "pi": json.dumps(perimetre_ok) if perimetre_ok is not None else None,
                    "ex": exclusions,
                    "seuil": seuil_ok,
                },
            ).scalar_one()
        except IntegrityError as e:
            raise ErreurMissionDoublon(
                f"Une mission existe déjà pour « {denomination} » sur "
                f"l'exercice {exercice}. Ouvrez-la depuis l'onglet Missions."
            ) from e
        session.flush()
        mid = int(mission_id)

    if isinstance(objectifs, (list, tuple)):
        objectifs = [
            o
            for o in objectifs
            if isinstance(o, dict) and str(o.get("libelle") or "").strip()
        ]

    if objectifs is not None:
        try:
            remplacer_objectifs_mission(
                session,
                tenant_id,
                mid,
                objectifs,
                verifier_cadrage=False,
            )
        except ErreurObjectif as e:
            raise ErreurMission(str(e)) from e

    from backend.plateforme.objectifs_fiscaux import (
        ErreurObjectifFiscal,
        synchroniser_depuis_perimetre,
    )

    try:
        synchroniser_depuis_perimetre(
            session,
            tenant_id,
            mid,
            perimetre_ok,
            exercice=exercice,
            verifier_cadrage=False,
        )
    except ErreurObjectifFiscal as e:
        raise ErreurMission(str(e)) from e
    return mid


def lire_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> dict[str, Any]:
    """Lecture d'une mission (RLS via contexte tenant)."""
    from backend.plateforme.objectifs import lister_objectifs_en_contexte
    from backend.plateforme.objectifs_fiscaux import (
        lister_objectifs_fiscaux_en_contexte,
    )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.id, m.contribuable_id, m.exercice, m.statut, m.profil, "
                "m.version_referentiel_id, m.cree_le, m.type_engagement, "
                "m.perimetre_impots, m.exclusions_declarees, m.seuil_signification, "
                "c.denomination AS contribuable_denomination "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurMission(f"mission {mission_id} introuvable")
        objectifs = lister_objectifs_en_contexte(session, mission_id)
        objectifs_fiscaux = lister_objectifs_fiscaux_en_contexte(
            session, mission_id
        )
        return serialiser_mission(
            dict(row),
            objectifs=objectifs,
            objectifs_fiscaux=objectifs_fiscaux,
        )


def patcher_cadrage_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    type_engagement: object | None = ...,
    perimetre_impots: object | None = ...,
    exclusions_declarees: object | None = ...,
    seuil_signification: object | None = ...,
    objectifs: object | None = ...,
    objectifs_fiscaux: object | None = ...,
) -> dict[str, Any]:
    """Met à jour les champs de cadrage — uniquement si statut = cadrage.

    Passer ``...`` (Ellipsis) pour ne pas toucher un champ ; ``None`` explicite
    remet perimetre / exclusions / seuil à NULL. ``objectifs=[]`` vide la liste.
    ``objectifs_fiscaux`` dérive ``perimetre_impots`` (source de vérité fiscale).
    """
    from backend.plateforme.objectifs import ErreurObjectif, remplacer_objectifs_mission
    from backend.plateforme.objectifs_fiscaux import (
        ErreurObjectifFiscal,
        remplacer_objectifs_fiscaux,
        synchroniser_depuis_perimetre,
    )

    champs_fournis = {
        "type_engagement": type_engagement is not ...,
        "perimetre_impots": perimetre_impots is not ...,
        "exclusions_declarees": exclusions_declarees is not ...,
        "seuil_signification": seuil_signification is not ...,
        "objectifs": objectifs is not ...,
        "objectifs_fiscaux": objectifs_fiscaux is not ...,
    }
    if not any(champs_fournis.values()):
        raise ErreurMission("aucun champ de cadrage fourni")
    if champs_fournis["perimetre_impots"] and champs_fournis["objectifs_fiscaux"]:
        raise ErreurMission(
            "fournir perimetre_impots OU objectifs_fiscaux, pas les deux"
        )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, statut, type_engagement, perimetre_impots, "
                "exclusions_declarees, seuil_signification, contribuable_id, "
                "exercice, version_referentiel_id, cree_le, profil "
                "FROM mission WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurMission(f"mission {mission_id} introuvable")

        statut = str(row["statut"] or STATUT_CADRAGE).lower()
        if statut != STATUT_CADRAGE:
            geles = ", ".join(sorted(CHAMPS_CADRAGE_GELES))
            raise ErreurMission(
                f"cadrage figé (statut={statut}) — champs non modifiables : {geles}"
            )

        type_ok = (
            valider_type_engagement(type_engagement)
            if champs_fournis["type_engagement"]
            else str(row["type_engagement"] or "autre")
        )
        exercice = int(row["exercice"]) if row.get("exercice") is not None else 0
        if champs_fournis["exclusions_declarees"]:
            if exclusions_declarees is None:
                exclusions = None
            else:
                exclusions = str(exclusions_declarees).strip() or None
        else:
            exclusions = row["exclusions_declarees"]
        seuil_ok = (
            valider_seuil_signification(seuil_signification)
            if champs_fournis["seuil_signification"]
            else row["seuil_signification"]
        )

        perimetre_ok = normaliser_perimetre_lu(row["perimetre_impots"])
        if champs_fournis["objectifs_fiscaux"]:
            try:
                _rows, perimetre_ok = remplacer_objectifs_fiscaux(
                    session,
                    tenant_id,
                    mission_id,
                    objectifs_fiscaux if objectifs_fiscaux is not None else [],
                    verifier_cadrage=False,
                )
            except ErreurObjectifFiscal as e:
                raise ErreurMission(str(e)) from e
        elif champs_fournis["perimetre_impots"]:
            perimetre_ok = valider_perimetre_impots(perimetre_impots)

        session.execute(
            text(
                "UPDATE mission SET "
                "type_engagement = :te, "
                "perimetre_impots = CAST(:pi AS jsonb), "
                "exclusions_declarees = :ex, "
                "seuil_signification = :seuil "
                "WHERE id = :m"
            ),
            {
                "te": type_ok,
                "pi": json.dumps(perimetre_ok) if perimetre_ok is not None else None,
                "ex": exclusions,
                "seuil": seuil_ok,
                "m": mission_id,
            },
        )
        session.flush()

    if champs_fournis["perimetre_impots"] and not champs_fournis["objectifs_fiscaux"]:
        try:
            synchroniser_depuis_perimetre(
                session,
                tenant_id,
                mission_id,
                perimetre_ok,
                exercice=exercice,
                verifier_cadrage=True,
            )
        except ErreurObjectifFiscal as e:
            raise ErreurMission(str(e)) from e

    if champs_fournis["objectifs"]:
        try:
            remplacer_objectifs_mission(
                session,
                tenant_id,
                mission_id,
                objectifs if objectifs is not None else [],
                verifier_cadrage=True,
            )
        except ErreurObjectif as e:
            raise ErreurMission(str(e)) from e

    return lire_mission(session, tenant_id, mission_id)


def changer_statut_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    nouveau_statut: str,
) -> dict[str, Any]:
    """Passe le statut d'une mission selon TRANSITIONS_STATUT.

    Doit être appelé dans un contexte tenant déjà posé (session_abonne)
    ou pose le sien. Retourne id + ancien/nouveau statut.
    """
    cible = (nouveau_statut or "").strip().lower()
    if cible not in STATUTS_MISSION:
        raise ErreurMission(
            f"statut invalide {nouveau_statut!r} — attendu : "
            + ", ".join(sorted(STATUTS_MISSION))
        )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, statut, contribuable_id, exercice "
                "FROM mission WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurMission(f"mission {mission_id} introuvable")

        actuel = str(row["statut"] or STATUT_CADRAGE).lower()
        if actuel == cible:
            return {
                "id": mission_id,
                "statut": actuel,
                "statut_precedent": actuel,
                "inchange": True,
            }

        autorises = TRANSITIONS_STATUT.get(actuel, frozenset())
        if cible not in autorises:
            raise ErreurMission(
                f"transition interdite : {actuel} → {cible} "
                f"(autorisées depuis {actuel} : "
                f"{', '.join(sorted(autorises)) or 'aucune'})"
            )

        if cible == STATUT_CLOTUREE:
            exec_id = session.execute(
                text("SELECT max(id) FROM execution WHERE mission_id = :m"),
                {"m": mission_id},
            ).scalar_one_or_none()
            if exec_id is not None:
                n_non_eval = session.execute(
                    text(
                        "SELECT count(*) FROM conclusion "
                        "WHERE execution_id = :e AND amendee_par IS NULL"
                    ),
                    {"e": exec_id},
                ).scalar_one()
                if int(n_non_eval) > 0:
                    raise ErreurMission(
                        f"Clôture refusée : {n_non_eval} conclusion(s) non "
                        "évaluée(s) — statuez sur chaque contrôle (anomalie, "
                        "conforme, sous seuil ou non vérifiable motivé) avant "
                        "de clôturer."
                    )
                n_anomalies = session.execute(
                    text(
                        "SELECT count(*) FROM conclusion "
                        "WHERE execution_id = :e AND statut = 'anomalie' "
                        "AND valide_par IS NULL"
                    ),
                    {"e": exec_id},
                ).scalar_one()
                if int(n_anomalies) > 0:
                    raise ErreurMission(
                        f"Clôture refusée : {n_anomalies} anomalie(s) non "
                        "validée(s) — faites valider chaque anomalie avant "
                        "clôture."
                    )

        if actuel == STATUT_CLOTUREE and cible != STATUT_CLOTUREE:
            autre = session.execute(
                text(
                    "SELECT id FROM mission "
                    "WHERE contribuable_id = :c AND exercice = :e "
                    "AND statut <> :cl AND id <> :m "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {
                    "c": row["contribuable_id"],
                    "e": row["exercice"],
                    "cl": STATUT_CLOTUREE,
                    "m": mission_id,
                },
            ).scalar_one_or_none()
            if autre is not None:
                raise ErreurMission(
                    f"Réouverture impossible : la mission #{autre} est déjà "
                    f"active pour ce client sur l'exercice {row['exercice']}."
                )

        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": cible, "m": mission_id},
        )
        session.flush()
        result = {
            "id": mission_id,
            "statut": cible,
            "statut_precedent": actuel,
            "inchange": False,
            "points_ouverts_crees": 0,
            "risques_crees": 0,
        }

    if cible == STATUT_CLOTUREE:
        from backend.plateforme.risques import creer_risques_depuis_anomalies

        # R4 : registre `risque` = source N+1 ; plus de création point_ouvert
        nb_r = creer_risques_depuis_anomalies(
            session, tenant_id, mission_id
        )
        result["risques_crees"] = nb_r
        result["points_ouverts_crees"] = 0

        from backend.plateforme.memoire_client import alimenter_memoire

        with contexte_tenant(session, tenant_id):
            fiche = session.execute(
                text(
                    "SELECT contribuable_id, exercice "
                    "FROM mission WHERE id = :m"
                ),
                {"m": mission_id},
            ).mappings().one_or_none()
        if fiche is not None:
            alimenter_memoire(
                session,
                tenant_id,
                int(fiche["contribuable_id"]),
                type_entree="contexte",
                contenu=(
                    f"Mission #{mission_id} (exercice {fiche['exercice']}) "
                    f"clôturée — {nb_r} risque(s) créé(s) depuis les anomalies."
                ),
                source_type="mission",
                source_ref=f"mission:{mission_id}",
            )

    return result


def marquer_en_cours_si_cadrage(
    session: Session,
    mission_id: int,
) -> dict[str, Any]:
    """Passe cadrage → en_cours (idempotent). Appelé hors with contexte
    si le contexte tenant est déjà posé (ex. exécution moteur).

    Retourne ``{"statut": ..., "change": bool}``.
    """
    row = session.execute(
        text("SELECT statut FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurMission(f"mission {mission_id} introuvable")
    actuel = str(row["statut"] or STATUT_CADRAGE).lower()
    if actuel == STATUT_CLOTUREE:
        raise ErreurMission(
            f"mission {mission_id} clôturée — réouvrez-la avant d'exécuter"
        )
    if actuel == STATUT_CADRAGE:
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": STATUT_EN_COURS, "m": mission_id},
        )
        return {"statut": STATUT_EN_COURS, "change": True}
    return {"statut": actuel, "change": False}
