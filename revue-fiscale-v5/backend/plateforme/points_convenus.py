"""Suivi des points convenus du compte-rendu de restitution.

POURQUOI : le compte-rendu de réunion
(:mod:`backend.plateforme.compte_rendu`) consigne les points convenus
avec le client en texte libre, mais rien ne permet ensuite de suivre
s'ils ont été traités. Ce module stocke UN point par ligne, saisi par
le fiscaliste, avec un statut de suivi explicite : « a_faire » (défaut),
« fait » ou « abandonne ».

DOCTRINE : déterministe et CONSULTATIF — le suivi éclaire, l'humain
décide. Écriture en base uniquement sur clic explicite du fiscaliste
(ajout d'un point, changement de statut) ; aucun LLM. Fonctions pures
testables sans base + accès RLS via ``contexte_tenant`` (même pattern
que :mod:`backend.plateforme.compte_rendu`). La création n'a de sens
que sur une mission « en_cours » (restitution tenue) ou « cloturee »
(le suivi se poursuit après clôture) — jamais en cadrage.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.missions import STATUT_CLOTUREE, STATUT_EN_COURS

# Statuts de suivi d'un point convenu.
STATUT_A_FAIRE: Final = "a_faire"
STATUT_FAIT: Final = "fait"
STATUT_ABANDONNE: Final = "abandonne"
STATUTS_POINT: Final[tuple[str, ...]] = (
    STATUT_A_FAIRE,
    STATUT_FAIT,
    STATUT_ABANDONNE,
)

# Transitions autorisées : un point « à faire » est marqué fait ou
# abandonné ; un point fait/abandonné peut être remis « à faire »
# (correction humaine). Jamais fait ↔ abandonné directement.
TRANSITIONS_POINT: Final[dict[str, frozenset[str]]] = {
    STATUT_A_FAIRE: frozenset({STATUT_FAIT, STATUT_ABANDONNE}),
    STATUT_FAIT: frozenset({STATUT_A_FAIRE}),
    STATUT_ABANDONNE: frozenset({STATUT_A_FAIRE}),
}

LONGUEUR_MAX_LIBELLE: Final = 500

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_POINTS_CONVENUS: Final = (
    "Suivi consultatif des points convenus avec le client lors de la "
    "restitution — statuts saisis par le fiscaliste, l'humain décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_CREATION: Final = "creation_point_convenu"
ACTION_MAJ: Final = "maj_point_convenu"


class ErreurPointConvenu(Exception):
    """Échec du suivi des points convenus."""


class ErreurPointConvenuInvalide(ErreurPointConvenu):
    """Saisie invalide (libellé vide/trop long, statut inconnu) — 422."""


class ErreurPointConvenuIntrouvable(ErreurPointConvenu):
    """Mission ou point hors périmètre du tenant — 404 côté route."""


class ErreurPointConvenuConflit(ErreurPointConvenu):
    """Statut de mission ou transition non autorisés — 409 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_libelle(libelle: object) -> str:
    """PUR — valide et normalise le libellé d'un point convenu.

    Non vide après trim, au plus :data:`LONGUEUR_MAX_LIBELLE` caractères.
    Invalide → :class:`ErreurPointConvenuInvalide` (422 côté route).
    """
    texte_libelle = str(libelle or "").strip()
    if not texte_libelle:
        raise ErreurPointConvenuInvalide(
            "libellé du point convenu requis"
        )
    if len(texte_libelle) > LONGUEUR_MAX_LIBELLE:
        raise ErreurPointConvenuInvalide(
            f"libellé trop long ({len(texte_libelle)} caractères) — "
            f"maximum {LONGUEUR_MAX_LIBELLE}"
        )
    return texte_libelle


def valider_transition(statut_actuel: str, statut_cible: str) -> str:
    """PUR — valide un changement de statut de point convenu.

    Statut cible inconnu → :class:`ErreurPointConvenuInvalide` (422) ;
    transition non autorisée (:data:`TRANSITIONS_POINT`) →
    :class:`ErreurPointConvenuConflit` (409). Retourne le statut cible
    normalisé.
    """
    cible = str(statut_cible or "").strip().lower()
    if cible not in STATUTS_POINT:
        raise ErreurPointConvenuInvalide(
            f"statut invalide « {statut_cible} » — attendus : "
            f"{', '.join(STATUTS_POINT)}"
        )
    actuel = str(statut_actuel or "").strip().lower()
    if cible not in TRANSITIONS_POINT.get(actuel, frozenset()):
        raise ErreurPointConvenuConflit(
            f"transition non autorisée : « {actuel or 'inconnu'} » → "
            f"« {cible} »"
        )
    return cible


def synthese_points(points: list[dict[str, Any]]) -> dict[str, int]:
    """PUR — compteurs par statut ``{a_faire, fait, abandonne}``."""
    compteurs = {s: 0 for s in STATUTS_POINT}
    for p in points:
        statut = str(p.get("statut") or "").strip().lower()
        if statut in compteurs:
            compteurs[statut] += 1
    return compteurs


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB → charge JSON (horodatages ISO)."""
    cree = row.get("cree_le")
    maj = row.get("mis_a_jour_le")
    return {
        "id": int(row["id"]),
        "libelle": str(row.get("libelle") or ""),
        "statut": str(row.get("statut") or STATUT_A_FAIRE),
        "cree_le": (
            cree.isoformat() if isinstance(cree, datetime) else None
        ),
        "mis_a_jour_le": (
            maj.isoformat() if isinstance(maj, datetime) else None
        ),
    }


# ── Lecture / écriture par mission (RLS) ─────────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, statut FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurPointConvenuIntrouvable(
            f"mission {mission_id} introuvable"
        )
    return dict(mission)


def lister_points_convenus(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Points convenus de la mission + synthèse — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurPointConvenuIntrouvable` (404
    côté route).
    """
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        rows = session.execute(
            text(
                "SELECT id, libelle, statut, cree_le, mis_a_jour_le "
                "FROM point_convenu WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mission_id},
        ).mappings().all()
    points = [_serialiser(dict(r)) for r in rows]
    return {
        "mission_id": mission_id,
        "points": points,
        "synthese": synthese_points(points),
        "note": NOTE_POINTS_CONVENUS,
    }


def creer_point_convenu(
    session: Session,
    tenant_id: int,
    mission_id: int,
    libelle: object,
    acteur: str,
) -> dict[str, Any]:
    """Ajoute un point convenu — clic explicite du fiscaliste.

    Libellé invalide → :class:`ErreurPointConvenuInvalide` (422) ;
    mission hors tenant → :class:`ErreurPointConvenuIntrouvable` (404) ;
    mission en cadrage → :class:`ErreurPointConvenuConflit` (409 — les
    points convenus n'existent qu'après la restitution : mission
    « en_cours » ou « cloturee »). Journalise
    :data:`ACTION_CREATION`. Retourne le point créé + synthèse.
    """
    from backend.moteur.journal import append_journal

    texte_libelle = valider_libelle(libelle)
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        statut_mission = str(mission["statut"] or "").strip().lower()
        if statut_mission not in (STATUT_EN_COURS, STATUT_CLOTUREE):
            raise ErreurPointConvenuConflit(
                f"mission {mission_id} au statut "
                f"« {statut_mission or 'inconnu'} » — les points "
                "convenus ne se suivent que sur une mission en cours "
                "ou clôturée (restitution tenue)"
            )
        row = session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle) VALUES (:t, :m, :lib) "
                "RETURNING id, libelle, statut, cree_le, mis_a_jour_le"
            ),
            {"t": tenant_id, "m": mission_id, "lib": texte_libelle},
        ).mappings().one()
        point = _serialiser(dict(row))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_CREATION,
            charge_utile={
                "point_convenu_id": point["id"],
                "libelle": point["libelle"],
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "point": point,
        "note": NOTE_POINTS_CONVENUS,
    }


def changer_statut_point_convenu(
    session: Session,
    tenant_id: int,
    point_id: int,
    statut_cible: object,
    acteur: str,
) -> dict[str, Any]:
    """Change le statut d'un point convenu — clic explicite.

    Point hors tenant → :class:`ErreurPointConvenuIntrouvable` (404) ;
    statut inconnu → :class:`ErreurPointConvenuInvalide` (422) ;
    transition non autorisée → :class:`ErreurPointConvenuConflit`
    (409). Journalise :data:`ACTION_MAJ`. Retourne le point mis à jour.
    """
    from backend.moteur.journal import append_journal

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, mission_id, libelle, statut "
                "FROM point_convenu WHERE id = :p"
            ),
            {"p": point_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurPointConvenuIntrouvable(
                f"point convenu {point_id} introuvable"
            )
        cible = valider_transition(
            str(row["statut"] or ""), str(statut_cible or "")
        )
        maj = session.execute(
            text(
                "UPDATE point_convenu SET statut = :s, "
                "mis_a_jour_le = now() WHERE id = :p "
                "RETURNING id, libelle, statut, cree_le, mis_a_jour_le"
            ),
            {"s": cible, "p": point_id},
        ).mappings().one()
        point = _serialiser(dict(maj))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=int(row["mission_id"]),
            acteur=acteur,
            action=ACTION_MAJ,
            charge_utile={
                "point_convenu_id": point["id"],
                "de": str(row["statut"] or ""),
                "a": cible,
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": int(row["mission_id"]),
        "point": point,
        "note": NOTE_POINTS_CONVENUS,
    }
