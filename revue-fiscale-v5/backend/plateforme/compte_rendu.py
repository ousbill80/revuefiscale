"""Compte-rendu de la réunion de restitution — saisie humaine traçable.

POURQUOI : après la réunion de restitution avec le client (préparée par
l'« Ordre du jour » — :mod:`backend.plateforme.ordre_du_jour`), le
fiscaliste doit consigner un compte-rendu SIMPLE et traçable : date de
la réunion, participants, points convenus. Un seul compte-rendu par
mission (UPSERT — un nouvel enregistrement remplace le précédent).

Écriture uniquement sur clic explicite « Enregistrer » du fiscaliste —
aucun contenu généré, aucun LLM : le compte-rendu est intégralement
saisi par l'humain. Validation pure + accès RLS via ``contexte_tenant``
(même pattern que :func:`backend.plateforme.plan_actions.decider_action`
: mission hors tenant → 404, mission clôturée → 409).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant


class ErreurCompteRendu(Exception):
    """Échec du compte-rendu de réunion."""


class ErreurCompteRenduInvalide(ErreurCompteRendu):
    """Saisie invalide (date future, champ vide…) — 422 côté route."""


class ErreurCompteRenduIntrouvable(ErreurCompteRendu):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurCompteRenduMissionCloturee(ErreurCompteRendu):
    """Mission clôturée — écriture refusée (409 côté route)."""


# ── Validation pure ──────────────────────────────────────────────────


def valider_compte_rendu(
    date_reunion: object,
    participants: object,
    points_convenus: object,
    aujourd_hui: date,
) -> dict[str, Any]:
    """PUR — valide et normalise la saisie du compte-rendu.

    - ``date_reunion`` : ISO ``AAAA-MM-JJ`` (ou :class:`date`), jamais
      future — la réunion a déjà eu lieu (aujourd'hui accepté) ;
    - ``participants`` et ``points_convenus`` : texte non vide.

    Retourne ``{date_reunion (date), participants, points_convenus}``
    normalisé ; saisie invalide → :class:`ErreurCompteRenduInvalide`
    (422 côté route).
    """
    if isinstance(date_reunion, date):
        jour_reunion = date_reunion
    else:
        brut = str(date_reunion or "").strip()
        if not brut:
            raise ErreurCompteRenduInvalide(
                "date de réunion requise (format AAAA-MM-JJ)"
            )
        try:
            jour_reunion = date.fromisoformat(brut)
        except ValueError as e:
            raise ErreurCompteRenduInvalide(
                f"date de réunion invalide « {brut} » — format attendu "
                "AAAA-MM-JJ"
            ) from e
    if jour_reunion > aujourd_hui:
        raise ErreurCompteRenduInvalide(
            f"date de réunion future ({jour_reunion.isoformat()}) — le "
            "compte-rendu consigne une réunion déjà tenue"
        )
    participants_txt = str(participants or "").strip()
    if not participants_txt:
        raise ErreurCompteRenduInvalide("participants requis")
    points_txt = str(points_convenus or "").strip()
    if not points_txt:
        raise ErreurCompteRenduInvalide("points convenus requis")
    return {
        "date_reunion": jour_reunion,
        "participants": participants_txt,
        "points_convenus": points_txt,
    }


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB → charge JSON (dates ISO)."""
    maj = row.get("maj_le")
    jour = row.get("date_reunion")
    return {
        "date_reunion": (
            jour.isoformat() if isinstance(jour, date) else str(jour or "")
        ),
        "participants": str(row.get("participants") or ""),
        "points_convenus": str(row.get("points_convenus") or ""),
        "maj_le": maj.isoformat() if maj is not None else None,
    }


# ── Lecture / écriture par mission (RLS) ─────────────────────────────


def _mission_ou_404(
    session: Session, mission_id: int
) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, statut FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurCompteRenduIntrouvable(
            f"mission {mission_id} introuvable"
        )
    return dict(mission)


def lire_compte_rendu(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any] | None:
    """Compte-rendu de la mission — None si aucun n'est consigné.

    Mission hors tenant → :class:`ErreurCompteRenduIntrouvable` (404
    côté route). Lecture seule sous RLS.
    """
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "SELECT date_reunion, participants, points_convenus, "
                "maj_le FROM compte_rendu_reunion WHERE mission_id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        return None
    return _serialiser(dict(row))


def enregistrer_compte_rendu(
    session: Session,
    tenant_id: int,
    mission_id: int,
    date_reunion: object,
    participants: object,
    points_convenus: object,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Consigne LE compte-rendu de la réunion de restitution (UPSERT).

    Déclenché par un clic explicite « Enregistrer » du fiscaliste — un
    nouvel enregistrement remplace le précédent (un seul compte-rendu
    par mission). Saisie invalide →
    :class:`ErreurCompteRenduInvalide` (422) ; mission hors tenant →
    :class:`ErreurCompteRenduIntrouvable` (404) ; mission clôturée →
    :class:`ErreurCompteRenduMissionCloturee` (409 — même garde-fou que
    :func:`backend.plateforme.plan_actions.decider_action`).

    Retourne le compte-rendu enregistré (dates ISO).
    """
    jour = aujourd_hui or date.today()
    saisie = valider_compte_rendu(
        date_reunion, participants, points_convenus, jour
    )
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        if str(mission["statut"] or "").lower() == "cloturee":
            raise ErreurCompteRenduMissionCloturee(
                f"mission {mission_id} clôturée — réouvrez-la avant de "
                "consigner le compte-rendu de réunion"
            )
        row = session.execute(
            text(
                "INSERT INTO compte_rendu_reunion "
                "(tenant_id, mission_id, date_reunion, participants, "
                "points_convenus) VALUES (:t, :m, :d, :p, :pts) "
                "ON CONFLICT (tenant_id, mission_id) "
                "DO UPDATE SET date_reunion = EXCLUDED.date_reunion, "
                "participants = EXCLUDED.participants, "
                "points_convenus = EXCLUDED.points_convenus, "
                "maj_le = now() "
                "RETURNING date_reunion, participants, points_convenus, "
                "maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "d": saisie["date_reunion"],
                "p": saisie["participants"],
                "pts": saisie["points_convenus"],
            },
        ).mappings().one()
    # Pas de commit ici : get_session committe en fin de requête.
    return _serialiser(dict(row))
