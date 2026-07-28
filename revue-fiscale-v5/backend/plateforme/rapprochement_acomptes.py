"""Rapprochement acomptes IS versés / IS théorique — vue consultative.

POURQUOI : au moment de projeter la liquidation de l'impôt sur les
bénéfices, le fiscaliste rapproche l'IS THÉORIQUE du tableau de
passage (module :mod:`backend.plateforme.resultat_fiscal`, AUCUN
recalcul ici) du total des acomptes et crédits d'impôt SAISIS dans
l'outil pour l'exercice (module :mod:`backend.plateforme.acomptes`,
saisis depuis les quittances du client). Le solde indicatif de
liquidation (IS théorique − acomptes saisis) éclaire le reste à payer
ou le crédit d'impôt indicatif — jamais une liquidation opposable.

DIFFÉRENCE AVEC :mod:`backend.plateforme.acomptes` : ce module
existant rapproche les versements d'un IS dû estimé SAISI par le
fiscaliste ; le présent module rapproche les mêmes versements de l'IS
THÉORIQUE calculé par le tableau de passage — les deux vues sont
complémentaires (l'une part de la saisie humaine, l'autre de la
projection théorique), aucun calcul n'est dupliqué.

APPROXIMATION ASSUMÉE (documentée, ``approximation: true``) : l'outil
ne connaît que les acomptes SAISIS dans l'application — les quittances
et les états de la DGI font foi des versements réellement effectués.
Le solde restitué est un ORDRE DE GRANDEUR indicatif, jamais un solde
de liquidation opposable.

MINIMUM DE PERCEPTION : le module du résultat fiscal SIGNALE l'impôt
minimum forfaitaire sans le calculer (aucun IS minimum chiffré n'est
exposé) — l'IS retenu ici est donc l'IS théorique au taux normal, tel
quel, et le minimum de perception est restitué ``calculable: false``
avec un motif explicite (le signal IMF du passage est relayé).

DONNÉES : projection de
:func:`backend.plateforme.resultat_fiscal.vue_resultat_fiscal_mission`
et lecture des saisies ``acompte_impot`` via les aides du module
:mod:`backend.plateforme.acomptes` — AUCUNE table nouvelle, AUCUNE
migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
rapprochement éclaire, l'humain liquide et décide. Fonctions pures
testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.deficits_reportables`). Montants sérialisés
en ``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente. Formulations jamais accusatoires : un
solde s'explique, il ne se conclut pas.
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
STATUT_SOLDE_A_PAYER: Final = "solde_a_payer_indicatif"
STATUT_EXCEDENT: Final = "excedent_indicatif"
STATUT_EQUILIBRE: Final = "equilibre_indicatif"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Rapprochement indisponible — l'IS théorique du tableau de "
        "passage ne se chiffre pas (importez la balance, classes 6 "
        "et 7)"
    ),
    STATUT_SOLDE_A_PAYER: (
        "Solde indicatif à payer — l'IS théorique excède les acomptes "
        "saisis : reste à payer indicatif à rapprocher des quittances"
    ),
    STATUT_EXCEDENT: (
        "Crédit d'impôt indicatif / excédent à faire valoir — les "
        "acomptes saisis excèdent l'IS théorique : excédent indicatif "
        "à rapprocher des quittances"
    ),
    STATUT_EQUILIBRE: (
        "Position équilibrée indicative — acomptes saisis égaux à "
        "l'IS théorique"
    ),
}

# Motif restitué pour le minimum de perception — JAMAIS calculé ici :
# le tableau de passage signale l'IMF sans le chiffrer.
MOTIF_MINIMUM_NON_CALCULABLE: Final = (
    "Le module du résultat fiscal signale l'impôt minimum forfaitaire "
    "sans le calculer (assiette chiffre d'affaires TTC, taux, "
    "plancher, plafond et exonérations hors périmètre) — l'IS retenu "
    "pour le rapprochement est l'IS théorique au taux normal, tel "
    "quel : le fiscaliste vérifie le minimum de perception sur le CGI "
    "en vigueur et décide."
)

# Références restituées — TOUJOURS présentes (portées génériques, à
# vérifier par le fiscaliste sur le CGI en vigueur).
REFERENCES_RAPPROCHEMENT_ACOMPTES: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, acomptes de l'impôt sur les bénéfices",
        "portee": (
            "Versements d'acomptes en cours d'exercice imputables sur "
            "l'impôt dû — les quittances font foi des versements "
            "réellement effectués"
        ),
    },
    {
        "reference": "CGI, liquidation de l'impôt sur les bénéfices",
        "portee": (
            "Solde de liquidation après imputation des acomptes, "
            "retenues et crédits d'impôt — le solde restitué ici est "
            "indicatif, la liquidation relève du fiscaliste"
        ),
    },
    {
        "reference": "CGI, impôt minimum forfaitaire",
        "portee": (
            "Minimum de perception éventuel — non calculé par "
            "l'outil : l'IS retenu est l'IS théorique au taux normal, "
            "le fiscaliste vérifie le minimum applicable"
        ),
    },
)

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : un solde s'explique, il ne se conclut pas.
NOTE_RAPPROCHEMENT_ACOMPTES: Final = (
    "Rapprochement consultatif des acomptes IS saisis dans l'outil "
    "avec l'IS THÉORIQUE du tableau de passage (aucun recalcul) : le "
    "solde indicatif de liquidation (reste à payer ou crédit d'impôt "
    "indicatif / excédent à faire valoir) est un ordre de grandeur — "
    "APPROXIMATION ASSUMÉE : l'outil ne connaît que les acomptes "
    "saisis, les quittances font foi des versements réellement "
    "effectués. Le minimum de perception n'est pas calculé et un "
    "écart est un élément à expliquer, jamais une conclusion — le "
    "fiscaliste liquide, apprécie et décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_rapprochement_acomptes"


class ErreurRapprochementAcomptes(Exception):
    """Échec du rapprochement acomptes / IS théorique."""


class ErreurRapprochementAcomptesIntrouvable(ErreurRapprochementAcomptes):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def construire_rapprochement(
    passage: dict[str, Any] | None,
    acomptes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — rapprochement acomptes saisis / IS théorique du passage.

    ``passage`` : vue du tableau de passage (module
    :mod:`backend.plateforme.resultat_fiscal`, clés ``disponible``,
    ``is_theorique``, ``imf``) — ``None`` si la projection a échoué ;
    ``acomptes`` : lignes de versement sérialisées ``{id, nature,
    libelle_nature, date_versement, montant, reference_quittance}``
    (module :mod:`backend.plateforme.acomptes`, aucun recalcul).
    Montants restitués en ``str`` (Decimal). Clés TOUJOURS présentes ;
    ``disponible`` est vrai seulement si le passage chiffre un IS
    théorique — sans lui, le solde ne se projette pas (les acomptes
    saisis restent listés et totalisés).

    Déterministe : solde indicatif = IS théorique − total des
    acomptes saisis ; positif → ``solde_a_payer_indicatif`` ; négatif
    → ``excedent_indicatif`` (crédit d'impôt indicatif / excédent à
    faire valoir) ; nul → ``equilibre_indicatif``. Le minimum de
    perception n'est JAMAIS calculé (``calculable: false`` + motif) ;
    le signal IMF du passage est relayé tel quel.
    """
    from backend.plateforme.acomptes import (
        NATURES_VERSEMENT,
        totaliser_acomptes,
    )

    totaux = totaliser_acomptes(acomptes)
    lignes = [
        {
            "id": a.get("id"),
            "nature": str(a.get("nature") or ""),
            "libelle_nature": str(a.get("libelle_nature") or ""),
            "date_versement": str(a.get("date_versement") or ""),
            "montant": str(Decimal(str(a.get("montant") or 0))),
            "reference_quittance": (
                str(a["reference_quittance"])
                if a.get("reference_quittance")
                else None
            ),
        }
        for a in sorted(
            acomptes,
            key=lambda a: (
                str(a.get("date_versement") or ""),
                str(a.get("nature") or ""),
            ),
        )
    ]

    disponible = bool(passage and passage.get("disponible"))
    imf_passage = (passage or {}).get("imf") or {}
    if disponible:
        is_theorique = Decimal(str(passage.get("is_theorique") or 0))  # type: ignore[union-attr]
        solde = is_theorique - totaux["total"]
        if solde > 0:
            statut = STATUT_SOLDE_A_PAYER
        elif solde < 0:
            statut = STATUT_EXCEDENT
        else:
            statut = STATUT_EQUILIBRE
        is_theorique_str: str | None = str(is_theorique)
    else:
        solde = Decimal("0")
        statut = STATUT_INDISPONIBLE
        is_theorique_str = None

    return {
        "disponible": disponible,
        "is_theorique": is_theorique_str,
        "is_source": "resultat_fiscal_theorique",
        "acomptes": lignes,
        "totaux_saisis": {
            nature: str(totaux[nature]) for nature in NATURES_VERSEMENT
        }
        | {"total": str(totaux["total"])},
        "solde_indicatif": {
            "statut": statut,
            "libelle": LIBELLES_STATUT[statut],
            "montant": str(abs(solde)),
            "solde_signe": str(solde),
        },
        # Le solde est TOUJOURS une approximation : seuls les acomptes
        # SAISIS sont connus, les quittances font foi.
        "approximation": True,
        # Minimum de perception JAMAIS calculé — motif explicite ; le
        # signal IMF du tableau de passage est relayé tel quel.
        "minimum_perception": {
            "calculable": False,
            "motif": MOTIF_MINIMUM_NON_CALCULABLE,
            "imf_possible_signale": bool(imf_passage.get("possible")),
        },
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_versements": len(lignes),
            "total_acomptes_saisis": str(totaux["total"]),
        },
        "note": NOTE_RAPPROCHEMENT_ACOMPTES,
        "references": [
            dict(r) for r in REFERENCES_RAPPROCHEMENT_ACOMPTES
        ],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurRapprochementAcomptesIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def vue_rapprochement_acomptes_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement acomptes / IS théorique — lecture seule, RLS.

    Mission hors tenant →
    :class:`ErreurRapprochementAcomptesIntrouvable` (404 côté route).
    Se construit toujours : sans IS théorique chiffrable (balance
    absente), ``disponible=false`` et ``statut="indisponible"`` — les
    acomptes saisis restent listés, les clés présentes, aucun montant
    inventé. L'IS théorique est PROJETÉ depuis
    :func:`backend.plateforme.resultat_fiscal.vue_resultat_fiscal_mission`
    (aucun recalcul) ; tolérance : un passage en échec dégrade la vue
    en indisponible au lieu de la faire échouer.
    """
    from backend.plateforme.acomptes import (
        _acomptes_mission,
        _serialiser_acompte,
    )
    from backend.plateforme.resultat_fiscal import (
        vue_resultat_fiscal_mission,
    )

    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        acomptes = [
            _serialiser_acompte(a)
            for a in _acomptes_mission(session, mission_id)
        ]

    # Projection SANS recalcul du tableau de passage existant —
    # vue_resultat_fiscal_mission ouvre son propre contexte_tenant,
    # d'où l'appel HORS du with ci-dessus. Tolérance : échec → vue
    # indisponible, jamais bloquante.
    try:
        passage: dict[str, Any] | None = vue_resultat_fiscal_mission(
            session, tenant_id, mission_id
        )
    except Exception:  # noqa: BLE001 — projection annexe tolérée
        passage = None

    vue = construire_rapprochement(passage, acomptes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
