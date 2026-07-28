"""Suivi pluriannuel des déficits reportables — vue consultative.

POURQUOI : un cabinet revoit le même client exercice après exercice
(une mission par exercice). Lorsqu'un exercice ressort déficitaire au
tableau de passage, le déficit fiscal est en principe REPORTABLE EN
AVANT sur les bénéfices des exercices suivants — le fiscaliste doit
donc SUIVRE, d'un exercice à l'autre, les déficits constatés et leur
imputation. Le présent module assemble ce suivi pluriannuel depuis les
missions du MÊME contribuable (exercices antérieurs ou égal à celui de
la mission consultée) : résultat fiscal théorique par exercice (module
:mod:`backend.plateforme.resultat_fiscal` réutilisé tel quel, AUCUN
recalcul), déficit constaté et cumul INDICATIF des déficits antérieurs
non encore imputés.

APPROXIMATION ASSUMÉE (documentée, ``approximation: true``) : l'outil
ne connaît PAS les imputations réellement pratiquées dans les liasses
fiscales déposées. Le cumul indicatif suppose une imputation théorique
MAXIMALE : chaque bénéfice fiscal théorique absorbe le cumul des
déficits antérieurs dans la limite de ce bénéfice (même règle
prudente que le tableau de passage — l'imputation ne crée jamais de
déficit). Le cumul restitué est donc un ORDRE DE GRANDEUR, jamais un
solde opposable — seules les liasses font foi.

RÈGLE DE REPORT (principe général, JAMAIS un délai inventé) : le CGI
organise le report en avant des déficits avec, selon les versions et
les régimes, des délais et des plafonds d'imputation particuliers. Le
module rappelle le PRINCIPE (report en avant, imputation plafonnée au
bénéfice) et renvoie l'humain au CGI applicable pour le délai et le
plafond précis — aucun chiffre de délai n'est inventé ici.

IMPUTATION RÉELLE : restituée ``calculable: false`` avec un motif
explicite — les imputations pratiquées dans les liasses déposées ne
sont pas connues de l'outil, seul l'humain les rapproche.

DONNÉES : lecture seule des missions du contribuable et projection de
:func:`backend.plateforme.resultat_fiscal.vue_resultat_fiscal_mission`
par exercice — AUCUNE table nouvelle, AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le suivi
éclaire, l'humain vérifie les liasses et décide. Fonctions pures
testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.retenue_loyers`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente. Formulations jamais accusatoires : un
déficit se SUIT, il ne se conclut pas.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_AUCUN_DEFICIT: Final = "aucun_deficit"
STATUT_DEFICITS_A_SUIVRE: Final = "deficits_a_suivre"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Suivi indisponible — aucun exercice du client ne porte de "
        "résultat fiscal théorique chiffrable (importez les balances "
        "des missions du client)"
    ),
    STATUT_AUCUN_DEFICIT: (
        "Aucun déficit constaté sur les exercices suivis — rien à "
        "reporter d'après les résultats fiscaux théoriques"
    ),
    STATUT_DEFICITS_A_SUIVRE: (
        "Déficits à suivre — des déficits fiscaux théoriques ont été "
        "constatés : l'humain rapproche les liasses déposées et "
        "vérifie les imputations réellement pratiquées"
    ),
}

# Statuts d'une LIGNE du tableau pluriannuel (par exercice).
STATUT_LIGNE_INDISPONIBLE: Final = "indisponible"
STATUT_LIGNE_BENEFICE: Final = "benefice"
STATUT_LIGNE_DEFICIT: Final = "deficit"
STATUT_LIGNE_NUL: Final = "nul"

LIBELLES_STATUT_LIGNE: Final[dict[str, str]] = {
    STATUT_LIGNE_INDISPONIBLE: (
        "Résultat fiscal théorique indisponible (balance non importée)"
    ),
    STATUT_LIGNE_BENEFICE: "Résultat fiscal théorique bénéficiaire",
    STATUT_LIGNE_DEFICIT: "Déficit fiscal théorique constaté",
    STATUT_LIGNE_NUL: "Résultat fiscal théorique nul",
}

# Principe général du report en avant — AUCUN délai ni plafond chiffré
# n'est inventé : ils dépendent du CGI applicable, l'humain vérifie.
REGLE_REPORT_INDICATIVE: Final = (
    "Principe général : le déficit fiscal d'un exercice est en "
    "principe reportable EN AVANT sur les bénéfices des exercices "
    "suivants, l'imputation étant plafonnée au bénéfice de chaque "
    "exercice (elle ne crée ni n'aggrave un déficit). Le délai de "
    "report et les éventuels plafonds particuliers dépendent du CGI "
    "applicable à chaque exercice — le fiscaliste les vérifie sur le "
    "texte en vigueur, aucun délai n'est chiffré ici."
)

# Motif restitué pour l'imputation réelle — JAMAIS calculée : les
# liasses déposées ne sont pas connues de l'outil.
MOTIF_IMPUTATION_REELLE_NON_CALCULABLE: Final = (
    "Les imputations de déficits réellement pratiquées dans les "
    "liasses fiscales déposées ne sont pas connues de l'outil — le "
    "cumul restitué est une approximation à imputation théorique "
    "maximale : le fiscaliste rapproche les liasses et les décisions "
    "de gestion du client pour établir le solde réellement reportable."
)

# Références restituées — TOUJOURS présentes (portées génériques, à
# vérifier par le fiscaliste sur le CGI en vigueur).
REFERENCES_DEFICITS_REPORTABLES: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, dispositions sur le report des déficits",
        "portee": (
            "Report en avant du déficit fiscal sur les bénéfices des "
            "exercices suivants — délai et plafonds d'imputation "
            "selon le texte applicable à chaque exercice"
        ),
    },
    {
        "reference": "CGI, impôt sur les bénéfices (BIC)",
        "portee": (
            "Détermination du résultat fiscal — le déficit suivi ici "
            "est le résultat fiscal THÉORIQUE du tableau de passage, "
            "pas celui de la liasse déposée"
        ),
    },
    {
        "reference": "LPF, obligations déclaratives",
        "portee": (
            "Les liasses fiscales déposées font foi des imputations "
            "réellement pratiquées — la balance et le tableau de "
            "passage de l'outil ne s'y substituent pas"
        ),
    },
)

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : un déficit se suit, il ne se conclut pas.
NOTE_DEFICITS_REPORTABLES: Final = (
    "Suivi pluriannuel consultatif des déficits reportables : le "
    "résultat fiscal THÉORIQUE de chaque exercice revu du client est "
    "repris du tableau de passage (aucun recalcul) et les déficits "
    "constatés sont cumulés à imputation théorique maximale — "
    "APPROXIMATION ASSUMÉE : l'outil ne connaît pas les imputations "
    "réellement pratiquées dans les liasses déposées, qui seules font "
    "foi. Le délai et les plafonds de report dépendent du CGI "
    "applicable à chaque exercice et ne sont pas chiffrés ici. Un "
    "cumul restitué est un ordre de grandeur « à rapprocher », jamais "
    "une conclusion — le fiscaliste vérifie les liasses et décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_deficits_reportables"


class ErreurDeficitsReportables(Exception):
    """Échec du suivi pluriannuel des déficits reportables."""


class ErreurDeficitsReportablesIntrouvable(ErreurDeficitsReportables):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def construire_suivi_deficits(
    exercices: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — tableau pluriannuel des déficits depuis les exercices revus.

    ``exercices`` : lignes ``{exercice, mission_id, disponible,
    resultat_fiscal}`` (résultat fiscal THÉORIQUE du tableau de
    passage, str ou Decimal ; ``disponible`` faux si le passage de
    l'exercice ne se chiffre pas). Tri par exercice CROISSANT (le
    cumul se lit dans l'ordre du temps). Montants restitués en ``str``
    (Decimal). Clés TOUJOURS présentes ; ``disponible`` est vrai
    seulement si au moins un exercice porte un résultat fiscal
    théorique chiffrable.

    Cumul INDICATIF (approximation assumée, imputation théorique
    maximale — l'outil ne connaît pas les liasses) :

    - exercice déficitaire : le déficit s'AJOUTE au cumul ;
    - exercice bénéficiaire : le cumul est imputé DANS LA LIMITE du
      bénéfice (``min(cumul, bénéfice)``) — jamais au-delà ;
    - exercice indisponible : cumul inchangé, aucun montant inventé.

    Statuts : ``indisponible``, ``aucun_deficit`` (aucun déficit
    constaté) ou ``deficits_a_suivre`` — JAMAIS de conclusion, le
    suivi appelle un rapprochement humain avec les liasses.
    """
    lignes: list[dict[str, Any]] = []
    cumul = Decimal("0")
    nb_chiffrables = 0
    nb_deficits = 0

    for ex in sorted(
        exercices,
        key=lambda e: (int(e.get("exercice") or 0), int(e.get("mission_id") or 0)),
    ):
        chiffrable = bool(ex.get("disponible"))
        if chiffrable:
            nb_chiffrables += 1
            resultat = Decimal(str(ex.get("resultat_fiscal") or 0))
            if resultat < 0:
                statut_ligne = STATUT_LIGNE_DEFICIT
                deficit = -resultat
                imputation = Decimal("0")
                cumul += deficit
                nb_deficits += 1
            elif resultat > 0:
                statut_ligne = STATUT_LIGNE_BENEFICE
                deficit = Decimal("0")
                # Imputation théorique MAXIMALE : plafonnée au
                # bénéfice, ne crée jamais de déficit (approximation).
                imputation = min(cumul, resultat)
                cumul -= imputation
            else:
                statut_ligne = STATUT_LIGNE_NUL
                deficit = Decimal("0")
                imputation = Decimal("0")
            resultat_str: str | None = str(resultat)
        else:
            statut_ligne = STATUT_LIGNE_INDISPONIBLE
            deficit = Decimal("0")
            imputation = Decimal("0")
            resultat_str = None
        lignes.append(
            {
                "exercice": int(ex.get("exercice") or 0),
                "mission_id": (
                    int(ex["mission_id"])
                    if ex.get("mission_id") is not None
                    else None
                ),
                "disponible": chiffrable,
                "resultat_fiscal_theorique": resultat_str,
                "deficit_constate": str(deficit),
                "imputation_theorique": str(imputation),
                "cumul_indicatif_deficits": str(cumul),
                "statut": statut_ligne,
                "libelle_statut": LIBELLES_STATUT_LIGNE[statut_ligne],
            }
        )

    disponible = nb_chiffrables > 0
    if not disponible:
        statut = STATUT_INDISPONIBLE
    elif nb_deficits > 0:
        statut = STATUT_DEFICITS_A_SUIVRE
    else:
        statut = STATUT_AUCUN_DEFICIT

    return {
        "disponible": disponible,
        "exercices": lignes,
        "cumul_indicatif_final": str(cumul),
        # Le cumul est TOUJOURS une approximation (imputation
        # théorique maximale, liasses inconnues) — le contrat l'assume.
        "approximation": True,
        "regle_report": {
            "principe": REGLE_REPORT_INDICATIVE,
            "delai_chiffre": False,
        },
        # Les imputations réelles des liasses déposées ne sont JAMAIS
        # calculées ni inventées — seul l'humain rapproche.
        "imputation_reelle": {
            "calculable": False,
            "motif": MOTIF_IMPUTATION_REELLE_NON_CALCULABLE,
        },
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_exercices": len(lignes),
            "nb_exercices_chiffrables": nb_chiffrables,
            "nb_deficits_constates": nb_deficits,
        },
        "note": NOTE_DEFICITS_REPORTABLES,
        "references": [dict(r) for r in REFERENCES_DEFICITS_REPORTABLES],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text(
            "SELECT id, exercice, contribuable_id "
            "FROM mission WHERE id = :m"
        ),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurDeficitsReportablesIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _missions_par_exercice(
    session: Session, contribuable_id: int, exercice_max: int
) -> list[dict[str, Any]]:
    """Une mission par exercice ≤ exercice_max — la plus récente (id).

    Même convention que
    :mod:`backend.plateforme.comparaison_exercices` : à exercice égal,
    la mission au plus grand id représente l'exercice.
    """
    rows = session.execute(
        text(
            "SELECT DISTINCT ON (exercice) id, exercice FROM mission "
            "WHERE contribuable_id = :c AND exercice <= :e "
            "ORDER BY exercice ASC, id DESC"
        ),
        {"c": contribuable_id, "e": exercice_max},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_deficits_reportables_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Suivi pluriannuel des déficits de la mission — lecture seule, RLS.

    Mission hors tenant →
    :class:`ErreurDeficitsReportablesIntrouvable` (404 côté route). Se
    construit toujours : sans historique chiffrable (aucune balance
    sur aucun exercice du client), ``disponible=false`` et
    ``statut="indisponible"`` — les clés restent présentes, aucun
    montant inventé. Le résultat fiscal théorique de chaque exercice
    est PROJETÉ depuis
    :func:`backend.plateforme.resultat_fiscal.vue_resultat_fiscal_mission`
    (aucun recalcul) ; tolérance par exercice : un passage en échec
    dégrade la ligne en indisponible au lieu de faire échouer la vue.
    """
    from backend.plateforme.resultat_fiscal import (
        vue_resultat_fiscal_mission,
    )

    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        missions = _missions_par_exercice(
            session,
            int(mission["contribuable_id"]),
            int(mission["exercice"]),
        )

    exercices: list[dict[str, Any]] = []
    for m in missions:
        # Projection SANS recalcul du tableau de passage existant —
        # vue_resultat_fiscal_mission ouvre son propre contexte_tenant,
        # d'où l'appel HORS du with ci-dessus. Tolérance par exercice.
        try:
            passage = vue_resultat_fiscal_mission(
                session, tenant_id, int(m["id"])
            )
            exercices.append(
                {
                    "exercice": int(m["exercice"]),
                    "mission_id": int(m["id"]),
                    "disponible": bool(passage["disponible"]),
                    "resultat_fiscal": passage["resultat_fiscal"],
                }
            )
        except Exception:  # noqa: BLE001 — exercice annexe toléré
            exercices.append(
                {
                    "exercice": int(m["exercice"]),
                    "mission_id": int(m["id"]),
                    "disponible": False,
                    "resultat_fiscal": None,
                }
            )

    vue = construire_suivi_deficits(exercices)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
