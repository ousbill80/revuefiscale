"""Responsable de mission et charge du cabinet.

POURQUOI : dans un cabinet à plusieurs collaborateurs, chaque mission
doit avoir un responsable identifié (colonne ``mission.responsable_email``,
migration 047) et l'associé veut voir la répartition de la charge —
qui porte combien de missions non clôturées.

DOCTRINE : déterministe et CONSULTATIF. L'affectation est une écriture
sur clic explicite, journalisée (``affectation_responsable_mission``) ;
la charge du cabinet est une lecture seule sous RLS via
``contexte_tenant``. Aucun LLM, aucune règle fiscale.

PAS DE FK dure vers ``utilisateur`` : l'email est l'identifiant métier
utilisé partout (journal, visas) et l'historique reste lisible si le
compte est désactivé. La cohérence — email d'un utilisateur ACTIF du
tenant (table ``utilisateur``, RLS forcée par ``tenant_id``) — est
vérifiée ici à chaque écriture.
"""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# RFC 5321 : longueur maximale d'une adresse.
LONGUEUR_MAX_EMAIL: Final[int] = 254

# Libellé affiché pour les missions sans responsable.
NON_AFFECTE: Final[str] = "non affecté"

MENTION_NOTE: Final[str] = (
    "Vue consultative — répartition des missions non clôturées par "
    "responsable, pour équilibrer la charge du cabinet. L'affectation "
    "se décide mission par mission : l'humain décide."
)


class ErreurResponsable(Exception):
    """Email de responsable invalide — HTTP 422."""


class ErreurMissionIntrouvable(Exception):
    """Mission absente ou hors tenant (RLS) — HTTP 404."""


# ── Validation pure ──────────────────────────────────────────────────


def valider_email_responsable(valeur: object | None) -> str | None:
    """PUR — normalise l'email du responsable ; ``None`` désaffecte.

    Format volontairement simple (contient « @ » puis « . » dans le
    domaine, ≤ 254 caractères) : la vérification forte est l'existence
    d'un utilisateur ACTIF du tenant, faite à l'écriture.
    """
    if valeur is None:
        return None
    email = str(valeur).strip().lower()
    if not email:
        raise ErreurResponsable(
            "email du responsable vide — envoyez null pour désaffecter"
        )
    if len(email) > LONGUEUR_MAX_EMAIL:
        raise ErreurResponsable(
            f"email du responsable trop long ({len(email)} caractères, "
            f"maximum {LONGUEUR_MAX_EMAIL})"
        )
    if email.count("@") != 1:
        raise ErreurResponsable(
            f"email du responsable invalide {email!r} — une seule "
            "arobase attendue (ex. prenom.nom@cabinet.ci)"
        )
    local, _, domaine = email.partition("@")
    if not local or "." not in domaine or domaine.startswith(".") or (
        domaine.endswith(".")
    ):
        raise ErreurResponsable(
            f"email du responsable invalide {email!r} — format attendu : "
            "prenom.nom@cabinet.ci"
        )
    return email


# ── Écriture (clic explicite) ────────────────────────────────────────


def affecter_responsable(
    session: Session,
    tenant_id: int,
    mission_id: int,
    email: object | None,
    acteur: str,
) -> dict[str, Any]:
    """Affecte (ou désaffecte si ``email`` est None) le responsable.

    Écriture sur clic explicite, sous RLS. Vérifie que l'email est
    celui d'un utilisateur ACTIF du tenant (table ``utilisateur``) —
    sinon :class:`ErreurResponsable` (422). Mission hors tenant →
    :class:`ErreurMissionIntrouvable` (404). Journalise
    ``affectation_responsable_mission`` avec ``de`` / ``a``.
    """
    from backend.moteur.journal import append_journal

    email_ok = valider_email_responsable(email)

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text("SELECT id, responsable_email FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurMissionIntrouvable(
                f"mission {mission_id} introuvable"
            )
        precedent = row["responsable_email"]

        if email_ok is not None:
            connu = session.execute(
                text(
                    "SELECT 1 FROM utilisateur "
                    "WHERE lower(email) = :e AND actif = TRUE"
                ),
                {"e": email_ok},
            ).scalar_one_or_none()
            if connu is None:
                raise ErreurResponsable(
                    f"aucun utilisateur actif du cabinet avec l'email "
                    f"{email_ok!r} — invitez d'abord ce collaborateur "
                    "dans l'équipe"
                )

        session.execute(
            text(
                "UPDATE mission SET responsable_email = :e WHERE id = :m"
            ),
            {"e": email_ok, "m": mission_id},
        )
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action="affectation_responsable_mission",
            charge_utile={"de": precedent, "a": email_ok},
        )
        session.flush()

    return {
        "mission_id": int(mission_id),
        "responsable_email": email_ok,
        "precedent": precedent,
    }


def lire_responsable(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> dict[str, Any]:
    """Lecture seule (RLS) du responsable courant d'une mission."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text("SELECT id, responsable_email FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurMissionIntrouvable(f"mission {mission_id} introuvable")
    return {
        "mission_id": int(mission_id),
        "responsable_email": row["responsable_email"],
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def repartir_charge(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — agrège les missions non clôturées par responsable.

    Entrée : lignes ``{responsable_email, statut}``. Sortie : items
    ``{responsable, nb_missions, nb_en_cours, nb_cadrage}`` triés par
    ``nb_missions`` décroissant puis responsable (le « non affecté »
    en dernier à égalité — il faut d'abord équilibrer les personnes).
    """
    par_resp: dict[str, dict[str, int]] = {}
    for r in rows:
        resp = str(r.get("responsable_email") or "").strip() or NON_AFFECTE
        agg = par_resp.setdefault(
            resp, {"nb_missions": 0, "nb_en_cours": 0, "nb_cadrage": 0}
        )
        agg["nb_missions"] += 1
        statut = str(r.get("statut") or "")
        if statut == "en_cours":
            agg["nb_en_cours"] += 1
        elif statut == "cadrage":
            agg["nb_cadrage"] += 1

    def _cle(item: tuple[str, dict[str, int]]) -> tuple:
        resp, agg = item
        return (
            -agg["nb_missions"],
            resp == NON_AFFECTE,  # « non affecté » après les personnes
            resp,
        )

    return [
        {"responsable": resp, **agg}
        for resp, agg in sorted(par_resp.items(), key=_cle)
    ]


def charge_cabinet(session: Session, tenant_id: int) -> dict[str, Any]:
    """Répartition des missions NON clôturées par responsable — RLS.

    LIMITE ASSUMÉE : pas d'``exposition_totale`` agrégée — les risques
    chiffrés naissent surtout à la clôture (hors périmètre de cette
    vue de charge) ; on ne mélange pas charge de travail et enjeu.
    """
    from backend.plateforme.missions import STATUT_CLOTUREE

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT responsable_email, statut FROM mission "
                "WHERE statut <> :cl"
            ),
            {"cl": STATUT_CLOTUREE},
        ).mappings().all()

    items = repartir_charge([dict(r) for r in rows])
    return {
        "items": items,
        "synthese": {
            "missions_actives": sum(i["nb_missions"] for i in items),
            "responsables": sum(
                1 for i in items if i["responsable"] != NON_AFFECTE
            ),
            "non_affectees": next(
                (
                    i["nb_missions"]
                    for i in items
                    if i["responsable"] == NON_AFFECTE
                ),
                0,
            ),
        },
        "note": MENTION_NOTE,
    }
