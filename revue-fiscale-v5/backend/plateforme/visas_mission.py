"""Visas de supervision par mission et par phase.

POURQUOI : les normes d'exercice professionnel exigent une supervision
hiérarchique formalisée des travaux — le préparateur atteste son travail,
le réviseur le revoit, l'associé signe. Chaque phase de la mission
(cadrage, collecte, controles, restitution) porte donc jusqu'à trois
visas ordonnés : ``preparateur`` < ``reviseur`` < ``associe``.

Règles d'ordre :
- un visa « reviseur » exige un visa « preparateur » préalable sur la
  même phase, et « associe » exige « reviseur » ;
- un visa ne peut être révoqué que s'il n'existe pas de visa de rang
  supérieur sur la phase (on ne retire pas l'attestation d'un travail
  déjà revu au rang supérieur).

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. La validation d'ordre est portée par des
fonctions pures (:func:`role_manquant_pour_poser`,
:func:`roles_superieurs_presents`) testables sans base.
"""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

PHASES_VISA: Final[tuple[str, ...]] = (
    "cadrage",
    "collecte",
    "controles",
    "restitution",
)

# Ordre hiérarchique des visas — l'index donne le rang (0 = premier).
ORDRE_ROLES: Final[tuple[str, ...]] = ("preparateur", "reviseur", "associe")


class ErreurVisaMission(Exception):
    """Visa invalide (phase, rôle, ordre, doublon…) — 422 côté route."""


class ErreurVisaIntrouvable(ErreurVisaMission):
    """Mission ou visa hors périmètre du tenant — 404."""


def role_manquant_pour_poser(
    role: str, roles_presents: set[str] | frozenset[str]
) -> str | None:
    """PUR — rôle immédiatement inférieur manquant pour poser ``role``.

    Retourne ``None`` si l'ordre hiérarchique est respecté (le rang
    inférieur est déjà visé, ou ``role`` est le premier rang), sinon le
    rôle prérequis absent. ``role`` doit appartenir à
    :data:`ORDRE_ROLES` (sinon ``ValueError``).
    """
    rang = ORDRE_ROLES.index(role)
    if rang == 0:
        return None
    prerequis = ORDRE_ROLES[rang - 1]
    return None if prerequis in roles_presents else prerequis


def roles_superieurs_presents(
    role: str, roles_presents: set[str] | frozenset[str]
) -> list[str]:
    """PUR — rôles de rang supérieur à ``role`` déjà visés sur la phase.

    Une liste non vide interdit la révocation du visa ``role``.
    """
    rang = ORDRE_ROLES.index(role)
    return [r for r in ORDRE_ROLES[rang + 1:] if r in roles_presents]


def _mission_existe(session: Session, mission_id: int) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        is not None
    )


def _valider_phase_role(phase: str, role: str) -> tuple[str, str]:
    phase = str(phase or "").strip()
    role = str(role or "").strip()
    if phase not in PHASES_VISA:
        raise ErreurVisaMission(
            f"phase invalide « {phase} » — attendues : "
            + ", ".join(PHASES_VISA)
        )
    if role not in ORDRE_ROLES:
        raise ErreurVisaMission(
            f"rôle invalide « {role} » — attendus : "
            + ", ".join(ORDRE_ROLES)
        )
    return phase, role


def _roles_presents(
    session: Session, mission_id: int, phase: str
) -> set[str]:
    rows = session.execute(
        text(
            "SELECT role FROM visa_mission "
            "WHERE mission_id = :m AND phase = :p"
        ),
        {"m": mission_id, "p": phase},
    ).scalars().all()
    return {str(r) for r in rows}


def _serialiser_visa(row: Any) -> dict[str, Any]:
    return {
        "role": str(row["role"]),
        "vise_par": str(row["vise_par"]),
        "vise_le": row["vise_le"].isoformat(),
        "commentaire": row["commentaire"],
    }


def poser_visa(
    session: Session,
    tenant_id: int,
    mission_id: int,
    phase: str,
    role: str,
    vise_par: str,
    commentaire: str | None = None,
) -> dict[str, Any]:
    """Pose un visa de supervision sur une phase — retourne le visa.

    La mission doit exister sous RLS (sinon
    :class:`ErreurVisaIntrouvable` → 404). Phase/rôle invalides, ordre
    hiérarchique non respecté ou visa déjà posé (même phase + rôle) →
    :class:`ErreurVisaMission` (422).
    """
    phase, role = _valider_phase_role(phase, role)
    vise_par = str(vise_par or "").strip()
    if not vise_par:
        raise ErreurVisaMission("vise_par obligatoire")

    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurVisaIntrouvable(f"mission {mission_id} introuvable")
        presents = _roles_presents(session, mission_id, phase)
        if role in presents:
            raise ErreurVisaMission(
                f"phase « {phase} » déjà visée au rôle « {role} »"
            )
        manquant = role_manquant_pour_poser(role, presents)
        if manquant is not None:
            raise ErreurVisaMission(
                f"ordre de supervision non respecté : le visa « {role} » "
                f"exige un visa « {manquant} » préalable sur la phase "
                f"« {phase} »"
            )
        row = session.execute(
            text(
                "INSERT INTO visa_mission "
                "(tenant_id, mission_id, phase, role, vise_par, "
                "commentaire) "
                "VALUES (:t, :m, :p, :r, :v, :c) "
                "RETURNING phase, role, vise_par, vise_le, commentaire"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "p": phase,
                "r": role,
                "v": vise_par,
                "c": (str(commentaire or "").strip() or None),
            },
        ).mappings().one()
    return {"phase": str(row["phase"]), **_serialiser_visa(row)}


def revoquer_visa(
    session: Session,
    tenant_id: int,
    mission_id: int,
    phase: str,
    role: str,
) -> dict[str, Any]:
    """Révoque (supprime) un visa — retourne le visa révoqué.

    Mission ou visa hors périmètre → :class:`ErreurVisaIntrouvable`
    (404). Présence d'un visa de rang supérieur sur la phase →
    :class:`ErreurVisaMission` (422) : on révoque du haut vers le bas.
    """
    phase, role = _valider_phase_role(phase, role)
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurVisaIntrouvable(f"mission {mission_id} introuvable")
        presents = _roles_presents(session, mission_id, phase)
        if role not in presents:
            raise ErreurVisaIntrouvable(
                f"visa « {role} » introuvable sur la phase « {phase} » "
                f"de la mission {mission_id}"
            )
        superieurs = roles_superieurs_presents(role, presents)
        if superieurs:
            raise ErreurVisaMission(
                f"révocation impossible : visa de rang supérieur présent "
                f"({', '.join(superieurs)}) sur la phase « {phase} » — "
                "révoquez d'abord le rang supérieur"
            )
        row = session.execute(
            text(
                "DELETE FROM visa_mission "
                "WHERE mission_id = :m AND phase = :p AND role = :r "
                "RETURNING phase, role, vise_par, vise_le, commentaire"
            ),
            {"m": mission_id, "p": phase, "r": role},
        ).mappings().one()
    return {"phase": str(row["phase"]), **_serialiser_visa(row)}


def etat_visas(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """État du registre des visas de la mission, phase par phase.

    Retourne ``{phases: [{phase, visas, complet}], synthese:
    {phases_completes, total_visas}}`` — ``complet`` vaut True quand les
    trois rangs (:data:`ORDRE_ROLES`) sont visés. Mission hors tenant →
    :class:`ErreurVisaIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurVisaIntrouvable(f"mission {mission_id} introuvable")
        rows = session.execute(
            text(
                "SELECT phase, role, vise_par, vise_le, commentaire "
                "FROM visa_mission WHERE mission_id = :m"
            ),
            {"m": mission_id},
        ).mappings().all()

    par_phase: dict[str, dict[str, Any]] = {
        str(r["phase"]): {} for r in rows
    }
    for r in rows:
        par_phase[str(r["phase"])][str(r["role"])] = _serialiser_visa(r)

    phases: list[dict[str, Any]] = []
    completes = 0
    total = 0
    for phase in PHASES_VISA:
        visas_phase = par_phase.get(phase, {})
        visas = [
            visas_phase[role] for role in ORDRE_ROLES if role in visas_phase
        ]
        complet = len(visas) == len(ORDRE_ROLES)
        completes += 1 if complet else 0
        total += len(visas)
        phases.append({"phase": phase, "visas": visas, "complet": complet})
    return {
        "phases": phases,
        "synthese": {"phases_completes": completes, "total_visas": total},
    }
