"""Projet de lettre de relance déclarative — par client (contribuable).

POURQUOI : quand des périodes TVA ou impôts sur salaires restent à
saisir sur les missions ouvertes d'un client, le cabinet veut ORGANISER
la collecte avec lui. Ce module assemble un PROJET de courrier type —
courtois, jamais accusatoire — que l'expert-comptable relit, adapte et
valide AVANT tout envoi : l'outil ne transmet rien, l'humain décide.

AUCUN recalcul métier : les périodes manquantes par mission sont celles
DÉJÀ restituées par
:func:`backend.plateforme.completude_declarative.completude_declarative_mission`,
résumées par :func:`backend.plateforme.portefeuille_declaratif.resumer_mission`
(mêmes clés, même statut ``a_completer``). Assemblage DÉTERMINISTE et
CONSULTATIF (aucun LLM, AUCUN email, AUCUN envoi automatique) — textes
français, valeurs ``str``. Lecture seule sous RLS via
``contexte_tenant`` — AUCUNE écriture, AUCUNE migration.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.portefeuille_declaratif import (
    STATUT_A_COMPLETER,
    resumer_mission,
)

# ── Constantes ───────────────────────────────────────────────────────

#: En-tête du document — PROJET, jamais un courrier définitif.
EN_TETE_RELANCE: Final = "PROJET DE LETTRE — RELANCE DÉCLARATIVE"

#: Rappel de doctrine : la saisie dans l'outil n'est qu'un suivi.
MENTION_DECLARATIONS_FOI: Final = (
    "Les déclarations effectivement déposées auprès de "
    "l'administration font foi : si certaines périodes listées "
    "ci-dessus ont déjà été déclarées, la simple transmission des "
    "quittances correspondantes suffira à mettre notre suivi à jour."
)

#: Note consultative finale — TOUJOURS présente dans la lettre.
NOTE_PROJET_RELANCE: Final = (
    "PROJET de lettre généré automatiquement à partir du suivi "
    "déclaratif : à relire, adapter et valider par "
    "l'expert-comptable avant tout envoi — l'humain décide. Aucun "
    "envoi automatique n'est effectué par l'outil."
)

#: Mois français — rendu lisible des périodes « AAAA-MM ».
MOIS_FR: Final[dict[str, str]] = {
    "01": "janvier",
    "02": "février",
    "03": "mars",
    "04": "avril",
    "05": "mai",
    "06": "juin",
    "07": "juillet",
    "08": "août",
    "09": "septembre",
    "10": "octobre",
    "11": "novembre",
    "12": "décembre",
}


class ErreurRelanceDeclarative(Exception):
    """Échec de construction du projet de relance déclarative."""


class ErreurRelanceIntrouvable(ErreurRelanceDeclarative):
    """Contribuable hors périmètre du tenant — 404 côté route."""


class ErreurAucunePeriodeManquante(ErreurRelanceDeclarative):
    """Aucune période à collecter : la relance est sans objet — 409."""


# ── Fonctions pures ──────────────────────────────────────────────────


def periode_fr(periode: object) -> str:
    """PUR — « AAAA-MM » rendu « mois AAAA » ; brut si illisible."""
    brut = str(periode or "").strip()
    parties = brut.split("-")
    if len(parties) == 2 and parties[1] in MOIS_FR:
        return f"{MOIS_FR[parties[1]]} {parties[0]}"
    return brut


def _ligne_periodes(libelle: str, manquantes: list[str]) -> str:
    """PUR — une ligne « - Libellé : mois AAAA, mois AAAA »."""
    rendues = ", ".join(periode_fr(p) for p in manquantes)
    return f"  - {libelle} : {rendues}"


def construire_lettre(contexte: dict[str, Any]) -> str:
    """PUR — projet de lettre en texte français, déterministe.

    ``contexte`` : ``{denomination, aujourd_hui (date), missions}`` où
    ``missions`` sont les entrées ``a_completer`` DÉJÀ résumées par
    :func:`backend.plateforme.portefeuille_declaratif.resumer_mission`
    (``exercice``, ``tva.manquantes``, ``salaires.manquantes``). Ton
    courtois et factuel — la lettre ORGANISE la collecte, elle ne
    reproche rien. La date vient du paramètre ``aujourd_hui`` (aucun
    ``date.today()`` ici).
    """
    denomination = str(contexte.get("denomination") or "")
    jour: date = contexte["aujourd_hui"]
    missions: list[dict[str, Any]] = list(contexte.get("missions") or [])

    lignes: list[str] = [
        EN_TETE_RELANCE,
        f"Le {jour.strftime('%d/%m/%Y')}",
        "",
        f"À l'attention de la Direction de {denomination}",
        "",
        "Objet : suivi déclaratif — périodes à compléter (TVA et "
        "impôts sur salaires)",
        "",
        "Madame, Monsieur,",
        "",
        "Dans le cadre de notre mission de revue fiscale et afin de "
        "compléter notre revue, nous vous remercions de bien vouloir "
        "nous transmettre, à votre meilleure convenance, les "
        "déclarations (ou quittances de dépôt) relatives aux périodes "
        "suivantes, qui ne figurent pas encore dans notre suivi :",
        "",
    ]

    for m in missions:
        exercice = m.get("exercice")
        tva = list((m.get("tva") or {}).get("manquantes") or [])
        salaires = list((m.get("salaires") or {}).get("manquantes") or [])
        titre = f"Exercice {exercice}" if exercice is not None else "Exercice"
        mission_id = m.get("mission_id")
        if mission_id is not None:
            titre += f" (mission #{mission_id})"
        lignes.append(titre + " :")
        if tva:
            lignes.append(_ligne_periodes("TVA", tva))
        if salaires:
            lignes.append(
                _ligne_periodes("Impôts sur salaires", salaires)
            )
        if not tva and not salaires:
            lignes.append("  - Aucune période à transmettre.")
        lignes.append("")

    lignes += [
        MENTION_DECLARATIONS_FOI,
        "",
        "Nous restons naturellement à votre disposition pour convenir "
        "ensemble des modalités de transmission les plus simples pour "
        "vous, et vous prions d'agréer, Madame, Monsieur, l'expression "
        "de nos salutations distinguées.",
        "",
        "Pour le cabinet : [à compléter]",
        "",
        "Note : " + NOTE_PROJET_RELANCE,
    ]
    return "\n".join(lignes) + "\n"


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def relance_declarative_contribuable(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Projet de relance déclarative du client — LECTURE SEULE, RLS.

    Missions NON clôturées du contribuable, chacune résumée depuis la
    vue EXISTANTE
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    via :func:`backend.plateforme.portefeuille_declaratif.resumer_mission`
    — aucun recalcul. Seules les missions ``a_completer`` alimentent la
    lettre. Contribuable hors tenant → :class:`ErreurRelanceIntrouvable`
    (404 côté route) ; aucune période manquante →
    :class:`ErreurAucunePeriodeManquante` (409 : rien à relancer).
    """
    from backend.plateforme.completude_declarative import (
        completude_declarative_mission,
    )
    from backend.plateforme.missions import STATUT_CLOTUREE

    jour = aujourd_hui or date.today()

    with contexte_tenant(session, tenant_id):
        contribuable = session.execute(
            text(
                "SELECT id, denomination FROM contribuable "
                "WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contribuable is None:
            raise ErreurRelanceIntrouvable(
                f"contribuable {contribuable_id} introuvable pour ce "
                "tenant"
            )
        rows = session.execute(
            text(
                "SELECT id AS mission_id, exercice FROM mission "
                "WHERE contribuable_id = :c AND statut <> :cl "
                "ORDER BY exercice DESC, id"
            ),
            {"c": contribuable_id, "cl": STATUT_CLOTUREE},
        ).mappings().all()

    denomination = str(contribuable["denomination"] or "")
    entrees: list[dict[str, Any]] = []
    for r in rows:
        # Tolérance par mission : un échec de la vue n'empêche jamais
        # la lettre des autres missions (pattern portefeuille).
        try:
            completude: dict[str, Any] | None = (
                completude_declarative_mission(
                    session, tenant_id, int(r["mission_id"])
                )
            )
        except Exception:  # noqa: BLE001 — mission annexe tolérée
            completude = None
        entrees.append(
            resumer_mission(
                {
                    "client": denomination,
                    "mission_id": int(r["mission_id"]),
                    "exercice": r["exercice"],
                    "completude": completude,
                }
            )
        )

    a_completer = [
        e for e in entrees if e.get("statut") == STATUT_A_COMPLETER
    ]
    if not a_completer:
        raise ErreurAucunePeriodeManquante(
            "Aucune période déclarative manquante pour ce client : "
            "le projet de relance est sans objet."
        )

    lettre = construire_lettre(
        {
            "denomination": denomination,
            "aujourd_hui": jour,
            "missions": a_completer,
        }
    )
    return {
        "contribuable_id": int(contribuable["id"]),
        "denomination": denomination,
        "aujourd_hui": jour.isoformat(),
        "nb_missions_a_completer": len(a_completer),
        "lettre": lettre,
        "note": NOTE_PROJET_RELANCE,
    }
