"""Programme de travail par mission (diligences standard par phase).

POURQUOI : les normes d'exercice professionnel imposent qu'une mission
de revue fiscale se déroule selon un programme de travail formalisé —
une liste de diligences par phase (cadrage, collecte, controles,
restitution, suivi) que le collaborateur coche au fur et à mesure de
l'exécution. Le pourcentage d'avancement par phase donne au chef de
mission et à l'associé une lecture immédiate de l'état des travaux, et
complète les visas de supervision (:mod:`backend.plateforme.visas_mission`) :
l'associé vise une phase dont les diligences sont faites.

Le programme standard (:data:`PROGRAMME_STANDARD`) reflète la pratique
d'un cabinet fiscaliste ivoirien : lettre de mission, prise de
connaissance du régime fiscal, collecte des balances/FEC et des
déclarations (TVA, IS/BIC, ITS, patente), exécution du référentiel de
contrôles, rapprochements, restitution et suivi du plan d'actions.

Il est initialisé paresseusement à la première consultation
(:func:`etat_programme`), en insérant uniquement les diligences
manquantes (idempotent, ``ON CONFLICT DO NOTHING``).

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. Le calcul des pourcentages est une fonction
pure (:func:`avancement_pct`, Decimal, 1 décimale) testable sans base.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

PHASES_PROGRAMME: Final[tuple[str, ...]] = (
    "cadrage",
    "collecte",
    "controles",
    "restitution",
    "suivi",
)

# Programme de travail standard d'une revue fiscale : (phase, code, libelle).
PROGRAMME_STANDARD: Final[tuple[tuple[str, str, str], ...]] = (
    ("cadrage", "CAD-01", "Lettre de mission signée et archivée"),
    (
        "cadrage",
        "CAD-02",
        "Prise de connaissance de l'entité et de son régime fiscal",
    ),
    (
        "cadrage",
        "CAD-03",
        "Revue de l'historique des contrôles et risques antérieurs",
    ),
    ("collecte", "COL-01", "Balances et FEC des exercices revus collectés"),
    (
        "collecte",
        "COL-02",
        "Déclarations fiscales de l'exercice rassemblées "
        "(TVA, IS/BIC, ITS, patente)",
    ),
    ("collecte", "COL-03", "Demande de renseignements adressée au client"),
    (
        "controles",
        "CTL-01",
        "Exécution du référentiel de contrôles sur l'exercice",
    ),
    ("controles", "CTL-02", "Revue analytique des postes significatifs"),
    ("controles", "CTL-03", "Rapprochement CA déclaré / comptabilisé"),
    (
        "controles",
        "CTL-04",
        "Réponses client intégrées et re-contrôle lancé",
    ),
    ("restitution", "RES-01", "Projet de rapport revu en interne"),
    ("restitution", "RES-02", "Note de synthèse validée"),
    ("restitution", "RES-03", "Rapport et annexes remis au client"),
    (
        "suivi",
        "SUI-01",
        "Plan d'actions et registre des risques mis à jour",
    ),
    ("suivi", "SUI-02", "Provision pour risques proposée à l'entité"),
)

CODES_STANDARD: Final[frozenset[str]] = frozenset(
    code for _, code, _ in PROGRAMME_STANDARD
)


class ErreurProgrammeTravail(Exception):
    """Diligence invalide (code inconnu…) — 422 côté route."""


class ErreurProgrammeIntrouvable(ErreurProgrammeTravail):
    """Mission hors périmètre du tenant — 404."""


def avancement_pct(faites: int, total: int) -> str:
    """PUR — pourcentage d'avancement, chaîne à 1 décimale (Decimal).

    ``total`` nul → « 0.0 » (aucune diligence : rien à avancer).
    Arrondi commercial (ROUND_HALF_UP).
    """
    if total <= 0:
        return "0.0"
    pct = (Decimal(faites) * Decimal(100) / Decimal(total)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return str(pct)


def _mission_existe(session: Session, mission_id: int) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        is not None
    )


def inserer_diligence(
    session: Session,
    tenant_id: int,
    mission_id: int,
    phase: str,
    code: str,
    libelle: str,
) -> bool:
    """Insère UNE diligence du programme — idempotente, True si créée.

    Point d'entrée UNIQUE de création dans ``diligence_mission``
    (``ON CONFLICT DO NOTHING`` sur (tenant, mission, code)) — réutilisé
    par l'initialisation du programme standard et par l'acceptation des
    diligences proposées (:mod:`backend.plateforme.programme_propose`).
    Le contexte tenant doit déjà être posé par l'appelant.
    """
    if phase not in PHASES_PROGRAMME:
        raise ErreurProgrammeTravail(
            f"phase inconnue « {phase} » — attendu : "
            + ", ".join(PHASES_PROGRAMME)
        )
    cree = session.execute(
        text(
            "INSERT INTO diligence_mission "
            "(tenant_id, mission_id, phase, code, libelle) "
            "VALUES (:t, :m, :p, :c, :l) "
            "ON CONFLICT (tenant_id, mission_id, code) DO NOTHING "
            "RETURNING id"
        ),
        {
            "t": tenant_id,
            "m": mission_id,
            "p": phase,
            "c": code,
            "l": libelle,
        },
    ).scalar_one_or_none()
    return cree is not None


def _inserer_diligences_manquantes(
    session: Session, tenant_id: int, mission_id: int
) -> None:
    for phase, code, libelle in PROGRAMME_STANDARD:
        inserer_diligence(
            session, tenant_id, mission_id, phase, code, libelle
        )


def initialiser_programme(
    session: Session, tenant_id: int, mission_id: int
) -> None:
    """Insère les diligences standard manquantes de la mission (idempotent).

    Appelée paresseusement par :func:`etat_programme` — les missions
    existantes reçoivent leur programme à la première consultation.
    Mission hors tenant → :class:`ErreurProgrammeIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurProgrammeIntrouvable(
                f"mission {mission_id} introuvable"
            )
        _inserer_diligences_manquantes(session, tenant_id, mission_id)


def cocher_diligence(
    session: Session,
    tenant_id: int,
    mission_id: int,
    code: str,
    fait: bool,
    fait_par: str,
) -> dict[str, Any]:
    """Coche (ou décoche) une diligence du programme — retourne la diligence.

    Cocher renseigne ``fait_par`` (email du collaborateur) et ``fait_le``
    (horodatage) ; décocher les remet à NULL. Code hors du programme
    standard ET absent des diligences de la mission (une diligence
    proposée acceptée — préfixe « PRO- » — reste cochable) →
    :class:`ErreurProgrammeTravail` (422) ; mission hors tenant →
    :class:`ErreurProgrammeIntrouvable` (404).
    """
    code = str(code or "").strip()
    fait_par = str(fait_par or "").strip()
    if fait and not fait_par:
        raise ErreurProgrammeTravail("fait_par obligatoire pour cocher")

    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurProgrammeIntrouvable(
                f"mission {mission_id} introuvable"
            )
        # Initialisation paresseuse : on peut cocher avant tout GET.
        _inserer_diligences_manquantes(session, tenant_id, mission_id)
        if code not in CODES_STANDARD:
            existe = session.execute(
                text(
                    "SELECT 1 FROM diligence_mission "
                    "WHERE mission_id = :m AND code = :c"
                ),
                {"m": mission_id, "c": code},
            ).scalar_one_or_none()
            if existe is None:
                raise ErreurProgrammeTravail(
                    f"diligence inconnue « {code} » — codes du "
                    "programme standard : "
                    + ", ".join(sorted(CODES_STANDARD))
                )
        row = session.execute(
            text(
                "UPDATE diligence_mission SET "
                "fait = :f, "
                "fait_par = CASE WHEN :f THEN :par ELSE NULL END, "
                "fait_le  = CASE WHEN :f THEN now() ELSE NULL END "
                "WHERE mission_id = :m AND code = :c "
                "RETURNING phase, code, libelle, fait, fait_par, fait_le"
            ),
            {"f": bool(fait), "par": fait_par, "m": mission_id, "c": code},
        ).mappings().one()
    return _serialiser_diligence(row)


def _serialiser_diligence(row: Any) -> dict[str, Any]:
    return {
        "phase": str(row["phase"]),
        "code": str(row["code"]),
        "libelle": str(row["libelle"]),
        "fait": bool(row["fait"]),
        "fait_par": row["fait_par"],
        "fait_le": (
            row["fait_le"].isoformat() if row["fait_le"] is not None else None
        ),
    }


def etat_programme(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """État du programme de travail de la mission, phase par phase.

    Initialise d'abord le programme standard si nécessaire (paresseux).
    Retourne ``{phases: [{phase, diligences, faites, total,
    avancement_pct}], synthese: {faites, total, avancement_pct}}`` — les
    pourcentages sont des chaînes à 1 décimale (:func:`avancement_pct`).
    Mission hors tenant → :class:`ErreurProgrammeIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurProgrammeIntrouvable(
                f"mission {mission_id} introuvable"
            )
        _inserer_diligences_manquantes(session, tenant_id, mission_id)
        rows = session.execute(
            text(
                "SELECT phase, code, libelle, fait, fait_par, fait_le "
                "FROM diligence_mission WHERE mission_id = :m "
                "ORDER BY code"
            ),
            {"m": mission_id},
        ).mappings().all()

    par_phase: dict[str, list[dict[str, Any]]] = {
        p: [] for p in PHASES_PROGRAMME
    }
    for r in rows:
        par_phase.setdefault(str(r["phase"]), []).append(
            _serialiser_diligence(r)
        )

    phases: list[dict[str, Any]] = []
    faites_total = 0
    total_total = 0
    for phase in PHASES_PROGRAMME:
        diligences = par_phase.get(phase, [])
        faites = sum(1 for d in diligences if d["fait"])
        total = len(diligences)
        faites_total += faites
        total_total += total
        phases.append(
            {
                "phase": phase,
                "diligences": [
                    {k: d[k] for k in
                     ("code", "libelle", "fait", "fait_par", "fait_le")}
                    for d in diligences
                ],
                "faites": faites,
                "total": total,
                "avancement_pct": avancement_pct(faites, total),
            }
        )
    return {
        "phases": phases,
        "synthese": {
            "faites": faites_total,
            "total": total_total,
            "avancement_pct": avancement_pct(faites_total, total_total),
        },
    }
