"""Complétude déclarative mensuelle de l'exercice — TVA et salaires.

POURQUOI : avant de rapprocher les montants, le réviseur vérifie que
CHAQUE période mensuelle échue de l'exercice dispose d'une déclaration
saisie — une période absente est le signal le plus simple (et le plus
fréquent) d'une déclaration omise. Cette vue balaye, par impôt
mensuel, les périodes AAAA-MM attendues (janvier → décembre de
l'exercice, limitées aux périodes ÉCHUES) et les compare aux périodes
saisies dans ``declaration_tva`` (migration 048) et
``declaration_salaires`` (migration 052).

RÈGLE DES PÉRIODES ÉCHUES : une période est échue si elle est
STRICTEMENT antérieure au mois courant — exercice passé : les 12
périodes ; exercice en cours : janvier → mois précédent ; exercice
futur : aucune (statut ``sans_periode_echue``).

LIMITE ASSUMÉE : la présence d'une saisie dans l'outil ne prouve PAS
le dépôt effectif à la DGI (ni l'inverse) — seul l'examen des
quittances et accusés de dépôt fait foi, l'humain vérifie.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF, AUCUNE
migration (lecture seule des tables existantes). Fonctions pures
testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.rapprochement_tva`). Contrat stable : clés
toujours présentes, taux en ``str`` (1 décimale, point machine), note
consultative toujours présente, tolérance par bloc (un impôt illisible
ne fait pas tomber la vue).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

IMPOT_TVA: Final = "tva"
IMPOT_SALAIRES: Final = "salaires"

LIBELLES_IMPOT: Final[dict[str, str]] = {
    IMPOT_TVA: "TVA (déclaration mensuelle)",
    IMPOT_SALAIRES: "Impôts sur salaires (déclaration mensuelle)",
}

# Statuts par impôt et statut global — vocabulaire fermé.
STATUT_COMPLET: Final = "complet"
STATUT_LACUNAIRE: Final = "lacunaire"
STATUT_AUCUNE_SAISIE: Final = "aucune_saisie"
STATUT_SANS_PERIODE_ECHUE: Final = "sans_periode_echue"

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_COMPLETUDE_DECLARATIVE: Final = (
    "Contrôle consultatif de complétude déclarative : les périodes "
    "mensuelles échues de l'exercice sont comparées aux déclarations "
    "saisies dans l'outil (TVA et impôts sur salaires). La saisie "
    "dans l'outil ne prouve pas le dépôt effectif à la DGI, ni "
    "l'inverse : seuls les quittances et accusés de dépôt font foi — "
    "l'humain vérifie et décide."
)

REFERENCES_COMPLETUDE: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI — TVA, régime du réel",
        "portee": (
            "Déclaration mensuelle de la TVA du mois précédent "
            "(échéancier DGI : 10/15/20 du mois suivant selon la "
            "direction de rattachement)"
        ),
    },
    {
        "reference": "CGI — ITS et retenues à la source",
        "portee": (
            "Déclaration mensuelle des impôts sur salaires du mois "
            "précédent (même calendrier mensuel DGI)"
        ),
    },
    {
        "reference": "LPF — obligations déclaratives",
        "portee": (
            "Une période sans déclaration expose aux pénalités pour "
            "défaut ou retard de déclaration — vérifier les quittances "
            "avant toute conclusion"
        ),
    },
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_completude_declarative"


class ErreurCompletudeDeclarative(Exception):
    """Échec du contrôle de complétude déclarative."""


class ErreurCompletudeDeclarativeIntrouvable(ErreurCompletudeDeclarative):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def generer_periodes(exercice: int, aujourd_hui: date) -> list[str]:
    """PUR — périodes AAAA-MM ÉCHUES de l'exercice, triées.

    Une période est échue si elle est STRICTEMENT antérieure au mois
    courant de ``aujourd_hui`` : exercice passé → les 12 périodes ;
    exercice en cours → janvier jusqu'au mois précédent ; exercice
    futur → aucune.
    """
    exercice = int(exercice)
    if exercice < aujourd_hui.year:
        dernier_mois = 12
    elif exercice > aujourd_hui.year:
        dernier_mois = 0
    else:
        dernier_mois = aujourd_hui.month - 1
    return [f"{exercice:04d}-{mois:02d}" for mois in range(1, dernier_mois + 1)]


def comparer(
    periodes_attendues: list[str], periodes_saisies: list[str]
) -> dict[str, Any]:
    """PUR — compare périodes attendues et saisies pour UN impôt.

    Retourne ``attendues``, ``saisies`` (dédoublonnées, triées),
    ``manquantes`` (attendues sans saisie), ``taux_couverture``
    (``str`` à 1 décimale, point machine — part des attendues
    couvertes ; « 0.0 » sans période attendue) et ``statut``
    (:data:`STATUT_COMPLET` / :data:`STATUT_LACUNAIRE` /
    :data:`STATUT_AUCUNE_SAISIE` / :data:`STATUT_SANS_PERIODE_ECHUE`).
    """
    attendues = sorted({str(p) for p in periodes_attendues})
    saisies = sorted({str(p) for p in periodes_saisies})
    ensemble_saisies = set(saisies)
    manquantes = [p for p in attendues if p not in ensemble_saisies]
    couvertes = len(attendues) - len(manquantes)

    if not attendues:
        taux = "0.0"
        statut = STATUT_SANS_PERIODE_ECHUE
    else:
        taux = f"{couvertes * 100 / len(attendues):.1f}"
        if not manquantes:
            statut = STATUT_COMPLET
        elif couvertes == 0:
            statut = STATUT_AUCUNE_SAISIE
        else:
            statut = STATUT_LACUNAIRE

    return {
        "attendues": attendues,
        "saisies": saisies,
        "manquantes": manquantes,
        "nb_attendues": len(attendues),
        "nb_saisies": len(saisies),
        "nb_manquantes": len(manquantes),
        "taux_couverture": taux,
        "statut": statut,
    }


def _bloc_impot(
    impot: str,
    periodes_attendues: list[str],
    periodes_saisies: list[str] | None,
) -> dict[str, Any]:
    """PUR — bloc d'un impôt ; ``periodes_saisies=None`` = illisible.

    Tolérance par bloc : un impôt dont les saisies sont illisibles est
    restitué ``disponible=false`` avec des clés stables (comparaison
    sur une liste vide) — la vue globale ne tombe pas.
    """
    vue = comparer(periodes_attendues, periodes_saisies or [])
    vue["impot"] = impot
    vue["libelle"] = LIBELLES_IMPOT.get(impot, impot)
    vue["disponible"] = periodes_saisies is not None
    return vue


def construire_completude(
    exercice: int,
    aujourd_hui: date,
    periodes_tva: list[str] | None,
    periodes_salaires: list[str] | None,
) -> dict[str, Any]:
    """PUR — vue complète de complétude déclarative (clés stables).

    ``periodes_tva`` / ``periodes_salaires`` : périodes saisies lues
    en base (``None`` si le bloc est illisible — tolérance par bloc).
    Statut global : ``sans_periode_echue`` si aucune période échue ;
    sinon ``complet`` (aucune manquante), ``aucune_saisie`` (aucune
    période couverte sur les blocs lisibles) ou ``lacunaire``.
    """
    attendues = generer_periodes(exercice, aujourd_hui)
    impots = {
        IMPOT_TVA: _bloc_impot(IMPOT_TVA, attendues, periodes_tva),
        IMPOT_SALAIRES: _bloc_impot(
            IMPOT_SALAIRES, attendues, periodes_salaires
        ),
    }

    blocs_lisibles = [b for b in impots.values() if b["disponible"]]
    nb_manquantes_total = sum(
        b["nb_manquantes"] for b in blocs_lisibles
    )
    if not attendues:
        statut_global = STATUT_SANS_PERIODE_ECHUE
    elif not blocs_lisibles:
        statut_global = STATUT_AUCUNE_SAISIE
    elif nb_manquantes_total == 0:
        statut_global = STATUT_COMPLET
    elif all(
        b["statut"] == STATUT_AUCUNE_SAISIE for b in blocs_lisibles
    ):
        statut_global = STATUT_AUCUNE_SAISIE
    else:
        statut_global = STATUT_LACUNAIRE

    return {
        "disponible": bool(blocs_lisibles),
        "exercice": int(exercice),
        "aujourd_hui": aujourd_hui.isoformat(),
        "impots": impots,
        "synthese": {
            "statut_global": statut_global,
            "nb_periodes_attendues": len(attendues),
            "nb_manquantes_total": nb_manquantes_total,
        },
        "note": NOTE_COMPLETUDE_DECLARATIVE,
        "references": [dict(r) for r in REFERENCES_COMPLETUDE],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurCompletudeDeclarativeIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _periodes_saisies(
    session: Session, table: str, mission_id: int
) -> list[str] | None:
    """Périodes saisies d'une table de déclarations — ``None`` si
    illisible (tolérance par bloc, la vue globale ne tombe pas)."""
    try:
        rows = session.execute(
            text(
                f"SELECT DISTINCT periode FROM {table} "  # noqa: S608
                "WHERE mission_id = :m ORDER BY periode"
            ),
            {"m": mission_id},
        ).scalars().all()
        return [str(p) for p in rows]
    except Exception:
        return None


def completude_declarative_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Complétude déclarative de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurCompletudeDeclarativeIntrouvable`
    (404 côté route). Se construit toujours : les clés restent
    présentes même sans aucune saisie ou avec un bloc illisible.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        periodes_tva = _periodes_saisies(
            session, "declaration_tva", mission_id
        )
        periodes_salaires = _periodes_saisies(
            session, "declaration_salaires", mission_id
        )

    vue = construire_completude(
        int(mission["exercice"]),
        date.today(),
        periodes_tva,
        periodes_salaires,
    )
    vue["mission_id"] = mission_id
    return vue
