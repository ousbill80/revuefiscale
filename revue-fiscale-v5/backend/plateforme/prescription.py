"""R5 — évaluation auto-``prescrit`` du registre risques.

Socle **non armé** tant que le référentiel n'expose pas de paramètres de
prescription millésimés et sourcés (visa Lot 5 — ``docs/23``, ``docs/15``).

Interdits (AGENTS.md) :
- aucun délai CGI en dur ;
- aucun calcul de date si le délai / point de départ manque dans le référentiel ;
- pas de lecture Annexe / PDF pour inventer une valeur.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

logger = logging.getLogger(__name__)

# Contrat éditorial futur (Lot 5). Table absente aujourd'hui → auto désarmé.
TABLE_PARAMETRE_PRESCRIPTION: Final[str] = "parametre_prescription"

STATUTS_ELIGIBLES_AUTO: Final[frozenset[str]] = frozenset(
    {"ouvert", "en_traitement"}
)

MOTIF_ATTENTE_VISA: Final[str] = "attente_visa_lot5"
MOTIF_TABLE_ABSENTE: Final[str] = "table_parametre_absente"
MOTIF_PARAMS_ABSENTS: Final[str] = "params_referentiel_absents"
MOTIF_PARAMS_INCOMPLETS: Final[str] = "params_incomplets"
MOTIF_OK: Final[str] = "ok"


@dataclass(frozen=True)
class ParametresPrescription:
    """Paramètres lus **uniquement** depuis le référentiel (jamais inventés)."""

    impot: str
    millesime: int
    delai_annees: int
    point_depart: str
    reference_legale: str


@dataclass
class ResultatEvaluationPrescription:
    """Compte-rendu d'un passage auto-``prescrit`` (souvent no-op)."""

    arme: bool
    motif: str
    examines: int = 0
    passes_prescrit: int = 0
    details: list[str] = field(default_factory=list)


def table_parametre_prescription_existe(session: Session) -> bool:
    """True seulement si la table éditoriale Lot 5 a été migrée."""
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": TABLE_PARAMETRE_PRESCRIPTION},
    ).scalar_one()
    return int(n) > 0


def lire_parametres_prescription(
    session: Session,
    *,
    impot: str,
    millesime: int,
) -> ParametresPrescription | None:
    """Lit un délai millésimé sourcé. Retourne None si absent / incomplet.

    Ne fournit **aucun** défaut applicatif. Colonnes attendues (contrat futur) :
    ``impot``, ``millesime``, ``delai_annees``, ``point_depart``,
    ``reference_legale`` — toutes NOT NULL côté éditorial une fois visées.
    """
    if not table_parametre_prescription_existe(session):
        return None

    code = str(impot or "").strip().upper()
    if not code:
        return None

    # Nom de table = constante Final (pas d'entrée utilisateur).
    row = session.execute(
        text(
            "SELECT impot, millesime, delai_annees, point_depart, "
            "reference_legale FROM parametre_prescription "
            "WHERE upper(impot) = :imp AND millesime = :m "
            "LIMIT 1"
        ),
        {"imp": code, "m": int(millesime)},
    ).mappings().one_or_none()
    if row is None:
        return None

    delai = row.get("delai_annees")
    point = (row.get("point_depart") or "").strip()
    ref = (row.get("reference_legale") or "").strip()
    if delai is None or not point or not ref:
        return None
    try:
        delai_i = int(delai)
    except (TypeError, ValueError):
        return None
    if delai_i <= 0:
        return None

    return ParametresPrescription(
        impot=str(row["impot"]).upper(),
        millesime=int(row["millesime"]),
        delai_annees=delai_i,
        point_depart=point,
        reference_legale=ref,
    )


def _date_limite_si_armee(
    params: ParametresPrescription,
    *,
    exercice_origine: int,
) -> date | None:
    """Calcule une date limite **uniquement** si le point de départ est connu.

    Aujourd'hui : aucun ``point_depart`` n'est reconnu (visa manquant) → None.
    Quand le fiscaliste visera Lot 5, ajouter ici **uniquement** les codes
    sourcés dans le référentiel — jamais une analogie française.
    """
    # Placeholders explicitement refusés tant que non visés.
    _ = (params, exercice_origine)
    return None


def evaluer_prescription_tenant(
    session: Session,
    tenant_id: int,
    *,
    aujourdhui: date | None = None,
    dry_run: bool = False,
) -> ResultatEvaluationPrescription:
    """Passe auto-``prescrit`` pour un tenant. No-op si référentiel non armé."""
    jour = aujourdhui or date.today()

    if not table_parametre_prescription_existe(session):
        msg = (
            "R5 auto-prescrit désarmé — table "
            f"{TABLE_PARAMETRE_PRESCRIPTION!r} absente "
            "(visa Lot 5 / docs/15)."
        )
        logger.info(msg)
        return ResultatEvaluationPrescription(
            arme=False,
            motif=MOTIF_ATTENTE_VISA,
            details=[msg],
        )

    examines = 0
    passes = 0
    details: list[str] = []

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT id, impot, exercice_origine, statut "
                "FROM risque WHERE statut = ANY(:sts) "
                "ORDER BY id"
            ),
            {"sts": list(STATUTS_ELIGIBLES_AUTO)},
        ).mappings().all()

        for row in rows:
            examines += 1
            rid = int(row["id"])
            impot = str(row["impot"])
            exercice = int(row["exercice_origine"])
            params = lire_parametres_prescription(
                session, impot=impot, millesime=exercice
            )
            if params is None:
                details.append(
                    f"risque {rid}: {MOTIF_PARAMS_ABSENTS} "
                    f"(impot={impot} millesime={exercice})"
                )
                continue

            limite = _date_limite_si_armee(
                params, exercice_origine=exercice
            )
            if limite is None:
                details.append(
                    f"risque {rid}: {MOTIF_PARAMS_INCOMPLETS} "
                    f"(point_depart={params.point_depart!r} non armé)"
                )
                continue

            if jour <= limite:
                continue

            if dry_run:
                details.append(
                    f"risque {rid}: serait prescrit (limite={limite.isoformat()})"
                )
                passes += 1
                continue

            session.execute(
                text(
                    "UPDATE risque SET statut = 'prescrit', "
                    "prescrit_le = :pl, maj_le = now() WHERE id = :id "
                    "AND statut = ANY(:sts)"
                ),
                {
                    "id": rid,
                    "pl": datetime.utcnow(),
                    "sts": list(STATUTS_ELIGIBLES_AUTO),
                },
            )
            passes += 1
            details.append(
                f"risque {rid}: prescrit (limite={limite.isoformat()}, "
                f"ref={params.reference_legale})"
            )

    arme = True
    motif = MOTIF_OK if passes or examines == 0 else MOTIF_PARAMS_ABSENTS
    if examines > 0 and passes == 0:
        # Table présente mais aucun passage effectif (délais manquants / point
        # de départ non armé) — toujours « désarmé fonctionnellement ».
        arme = False
        motif = MOTIF_PARAMS_INCOMPLETS

    return ResultatEvaluationPrescription(
        arme=arme,
        motif=motif,
        examines=examines,
        passes_prescrit=passes,
        details=details,
    )


def evaluer_prescription(
    session: Session,
    *,
    tenant_id: int | None = None,
    aujourdhui: date | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Point d'entrée ops / tests.

    Sans ``tenant_id`` : parcourt tous les tenants (SET LOCAL chacun).
    Retourne un dict sérialisable (logs / script).
    """
    if not table_parametre_prescription_existe(session):
        msg = (
            "R5 auto-prescrit désarmé — en attente visa Lot 5 "
            f"(pas de {TABLE_PARAMETRE_PRESCRIPTION})."
        )
        logger.info(msg)
        return {
            "arme": False,
            "motif": MOTIF_ATTENTE_VISA,
            "tenants": 0,
            "examines": 0,
            "passes_prescrit": 0,
            "details": [msg],
            "dry_run": dry_run,
        }

    if tenant_id is not None:
        res = evaluer_prescription_tenant(
            session,
            tenant_id,
            aujourdhui=aujourdhui,
            dry_run=dry_run,
        )
        return {
            "arme": res.arme,
            "motif": res.motif,
            "tenants": 1,
            "examines": res.examines,
            "passes_prescrit": res.passes_prescrit,
            "details": res.details,
            "dry_run": dry_run,
        }

    tenants = session.execute(
        text("SELECT id FROM tenant ORDER BY id")
    ).scalars().all()
    total_ex = 0
    total_pass = 0
    details: list[str] = []
    arme_global = False
    motif = MOTIF_ATTENTE_VISA

    for tid in tenants:
        res = evaluer_prescription_tenant(
            session,
            int(tid),
            aujourdhui=aujourdhui,
            dry_run=dry_run,
        )
        effacer_contexte_tenant(session)
        total_ex += res.examines
        total_pass += res.passes_prescrit
        details.extend(f"tenant {tid}: {d}" for d in res.details)
        if res.arme:
            arme_global = True
            motif = res.motif
        elif motif == MOTIF_ATTENTE_VISA:
            motif = res.motif

    return {
        "arme": arme_global,
        "motif": motif,
        "tenants": len(tenants),
        "examines": total_ex,
        "passes_prescrit": total_pass,
        "details": details,
        "dry_run": dry_run,
    }
