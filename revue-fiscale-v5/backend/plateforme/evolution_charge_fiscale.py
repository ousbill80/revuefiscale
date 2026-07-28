"""Évolution pluriannuelle de la charge fiscale — vue consultative.

POURQUOI : un cabinet revoit le même client exercice après exercice
(une mission par exercice). Le panorama de charge fiscale
(:mod:`backend.plateforme.charge_fiscale`) restitue déjà, PAR MISSION,
les composantes estimées (IS théorique, patente partielle, impôts sur
salaires déclarés, TVA nette déclarée) et le total de charge propre.
Le présent module assemble l'ÉVOLUTION de ces composantes entre les
exercices revus du même contribuable (exercices antérieurs ou égal à
celui de la mission consultée) : tableau pluriannuel et variations
entre exercices consécutifs DISPONIBLES.

AGRÉGAT STRICT (aucun recalcul, aucune invention) : chaque exercice
PROJETTE la vue de charge fiscale existante
(:func:`backend.plateforme.charge_fiscale.charge_fiscale_mission`)
telle quelle — composantes et total repris sans aucune liquidation.
La TVA nette (impôt COLLECTÉ) reste présentée séparément et n'est
jamais additionnée à la charge propre (règle du module réutilisé).

VARIATIONS (simple arithmétique, jamais une conclusion) : entre deux
exercices consécutifs disponibles, variation absolue (Decimal, str) et
variation relative en pourcentage (str à point décimal, 1 décimale —
contrat machine ; l'affichage français est du ressort du frontend),
``None`` si la base est nulle (aucune division inventée). Le sens
(« hausse » / « baisse » / « stable ») est purement descriptif : une
VARIATION S'EXPLIQUE (activité, taux, assiettes, exonérations), elle
ne s'impute à personne.

TOLÉRANCE : chaque exercice est tenté indépendamment (pattern
:mod:`backend.plateforme.deficits_reportables`) — un panorama en échec
dégrade la ligne en indisponible, jamais bloquant. Moins de deux
exercices disponibles → ``statut="indisponible"``, clés stables.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — la vue
éclaire, l'humain analyse et décide. Lecture seule, aucune écriture
hors journal d'audit. Montants sérialisés en ``str`` (Decimal). Clés
TOUJOURS présentes. Formulations jamais accusatoires : une variation
est « à expliquer », jamais un reproche.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

#: Composantes suivies dans l'évolution — clés TOUJOURS présentes.
COMPOSANTES_EVOLUTION: Final[tuple[str, ...]] = (
    "is",
    "patente",
    "salaires",
    "tva",
)

#: Composantes additionnées dans le total de charge propre du module
#: réutilisé — la TVA (impôt collecté) en est EXCLUE (jamais sommée).
COMPOSANTES_INCLUSES_TOTAL: Final[tuple[str, ...]] = (
    "is",
    "patente",
    "salaires",
)

LIBELLES_COMPOSANTES: Final[dict[str, str]] = {
    "is": "Impôt sur les bénéfices (IS théorique du tableau de passage)",
    "patente": (
        "Contribution des patentes (estimation partielle — droit sur "
        "le chiffre d'affaires seul)"
    ),
    "salaires": (
        "Impôts sur salaires déclarés (ITS retenu + contribution "
        "employeur)"
    ),
    "tva": (
        "TVA nette déclarée (impôt collecté, présentée séparément — "
        "jamais additionnée à la charge propre)"
    ),
}

SENS_HAUSSE: Final = "hausse"
SENS_BAISSE: Final = "baisse"
SENS_STABLE: Final = "stable"

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_EVOLUTION_DISPONIBLE: Final = "evolution_disponible"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Évolution indisponible — moins de deux exercices du client "
        "portent un panorama de charge fiscale estimée (importez les "
        "balances et saisissez les déclarations des missions du client)"
    ),
    STATUT_EVOLUTION_DISPONIBLE: (
        "Évolution disponible — les variations entre exercices "
        "consécutifs sont restituées à titre indicatif : chaque "
        "variation s'explique (activité, taux, assiettes, "
        "exonérations), le fiscaliste analyse"
    ),
}

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : une variation s'explique, elle ne se reproche pas.
NOTE_EVOLUTION_CHARGE_FISCALE: Final = (
    "Évolution pluriannuelle consultative de la charge fiscale : le "
    "panorama de chaque exercice revu du client est repris tel quel "
    "(aucun recalcul) et les variations entre exercices consécutifs "
    "disponibles sont restituées à titre indicatif. Les variations "
    "s'expliquent (activité, taux, assiettes, exonérations) — vue "
    "indicative fondée sur les charges THÉORIQUES estimées, les "
    "liasses font foi ; l'humain analyse et décide. La TVA nette "
    "(impôt collecté) est présentée séparément et jamais additionnée "
    "à la charge propre."
)

REFERENCES_EVOLUTION: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, impôt BIC des personnes morales",
        "portee": (
            "IS théorique du tableau de passage repris tel quel par "
            "exercice — aucun recalcul dans l'évolution"
        ),
    },
    {
        "reference": "CGI, art. 264 et s.",
        "portee": (
            "Contribution des patentes — estimation partielle (droit "
            "sur le chiffre d'affaires) reprise par exercice"
        ),
    },
    {
        "reference": "CGI, impôts sur traitements et salaires",
        "portee": (
            "Impôts sur salaires repris tels que déclarés par exercice"
        ),
    },
    {
        "reference": "CGI, TVA",
        "portee": (
            "TVA nette déclarée — impôt collecté, présenté séparément "
            "de la charge propre à chaque exercice"
        ),
    },
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_evolution_charge_fiscale"

#: Quantum du pourcentage de variation — 1 décimale, point décimal
#: (contrat machine ; l'affichage français relève du frontend).
_QUANTUM_PCT: Final = Decimal("0.1")


class ErreurEvolutionChargeFiscale(Exception):
    """Échec de l'évolution pluriannuelle de la charge fiscale."""


class ErreurEvolutionChargeFiscaleIntrouvable(ErreurEvolutionChargeFiscale):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def calculer_variation(
    precedent: Decimal | str | None, courant: Decimal | str | None
) -> dict[str, Any] | None:
    """PUR — variation entre deux montants d'exercices consécutifs.

    ``None`` si l'un des deux montants est indisponible (aucune
    variation inventée). Sinon : ``variation_absolue`` (str Decimal),
    ``variation_relative_pct`` (str à POINT décimal, 1 décimale,
    ``None`` si la base est nulle — aucune division par zéro) et
    ``sens`` descriptif (« hausse » / « baisse » / « stable »). La
    base relative est la VALEUR ABSOLUE du montant précédent (une TVA
    nette créditrice reste comparable en ampleur).
    """
    if precedent is None or courant is None:
        return None
    base = Decimal(str(precedent))
    valeur = Decimal(str(courant))
    delta = valeur - base
    if delta > 0:
        sens = SENS_HAUSSE
    elif delta < 0:
        sens = SENS_BAISSE
    else:
        sens = SENS_STABLE
    if base == 0:
        pct: str | None = None
    else:
        pct = str(
            (delta * Decimal("100") / abs(base)).quantize(
                _QUANTUM_PCT, rounding=ROUND_HALF_UP
            )
        )
    return {
        "variation_absolue": str(delta),
        "variation_relative_pct": pct,
        "sens": sens,
    }


def construire_evolution(
    exercices: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — tableau pluriannuel et variations (testable sans base).

    ``exercices`` : lignes ``{exercice, mission_id, disponible, total,
    composantes}`` — ``total`` : total de charge propre estimée (str
    ou Decimal, ``None`` si indisponible) ; ``composantes`` : dict
    ``{cle: montant str | None}`` (clés libres, normalisées sur
    :data:`COMPOSANTES_EVOLUTION`). Tri par exercice CROISSANT.

    Variations entre exercices consécutifs DISPONIBLES uniquement (un
    exercice indisponible est toléré : il n'engendre aucune variation,
    la paire suivante saute par-dessus — aucune valeur inventée).
    Statuts : ``indisponible`` (moins de deux exercices disponibles) /
    ``evolution_disponible``. Clés TOUJOURS présentes, montants str.
    """
    lignes: list[dict[str, Any]] = []
    for ex in sorted(
        exercices,
        key=lambda e: (
            int(e.get("exercice") or 0),
            int(e.get("mission_id") or 0),
        ),
    ):
        disponible = bool(ex.get("disponible"))
        brutes = ex.get("composantes") or {}
        composantes: dict[str, Any] = {}
        for cle in COMPOSANTES_EVOLUTION:
            montant = brutes.get(cle) if disponible else None
            composantes[cle] = {
                "libelle": LIBELLES_COMPOSANTES[cle],
                "montant_estime": (
                    str(Decimal(str(montant)))
                    if montant is not None
                    else None
                ),
                "incluse_dans_total": cle in COMPOSANTES_INCLUSES_TOTAL,
            }
        total = ex.get("total") if disponible else None
        lignes.append(
            {
                "exercice": int(ex.get("exercice") or 0),
                "mission_id": (
                    int(ex["mission_id"])
                    if ex.get("mission_id") is not None
                    else None
                ),
                "disponible": disponible,
                "total_charge_propre_estimee": (
                    str(Decimal(str(total))) if total is not None else None
                ),
                "composantes": composantes,
            }
        )

    disponibles = [ligne for ligne in lignes if ligne["disponible"]]
    variations: list[dict[str, Any]] = []
    for precedent, courant in zip(disponibles, disponibles[1:]):
        variations.append(
            {
                "exercice_precedent": precedent["exercice"],
                "exercice": courant["exercice"],
                # Total de charge propre : toujours présent sur une
                # ligne disponible (str « 0 » au pire) → variation
                # toujours chiffrable entre deux lignes disponibles.
                "total": calculer_variation(
                    precedent["total_charge_propre_estimee"],
                    courant["total_charge_propre_estimee"],
                ),
                "composantes": {
                    cle: calculer_variation(
                        precedent["composantes"][cle]["montant_estime"],
                        courant["composantes"][cle]["montant_estime"],
                    )
                    for cle in COMPOSANTES_EVOLUTION
                },
            }
        )

    statut = (
        STATUT_EVOLUTION_DISPONIBLE
        if len(disponibles) >= 2
        else STATUT_INDISPONIBLE
    )
    return {
        "disponible": statut == STATUT_EVOLUTION_DISPONIBLE,
        "exercices": lignes,
        "variations": variations,
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_exercices": len(lignes),
            "nb_exercices_disponibles": len(disponibles),
            "nb_variations": len(variations),
        },
        "note": NOTE_EVOLUTION_CHARGE_FISCALE,
        "references": [dict(r) for r in REFERENCES_EVOLUTION],
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
        raise ErreurEvolutionChargeFiscaleIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _missions_par_exercice(
    session: Session, contribuable_id: int, exercice_max: int
) -> list[dict[str, Any]]:
    """Une mission par exercice ≤ exercice_max — la plus récente (id).

    Même convention que
    :mod:`backend.plateforme.deficits_reportables` : à exercice égal,
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


def vue_evolution_charge_fiscale_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Évolution pluriannuelle de la charge fiscale — lecture seule, RLS.

    Mission hors tenant →
    :class:`ErreurEvolutionChargeFiscaleIntrouvable` (404 côté route).
    Se construit toujours : moins de deux exercices disponibles →
    ``disponible=false`` et ``statut="indisponible"`` — clés stables,
    aucun montant inventé. Le panorama de chaque exercice est PROJETÉ
    depuis
    :func:`backend.plateforme.charge_fiscale.charge_fiscale_mission`
    (aucun recalcul) ; tolérance par exercice : un panorama en échec
    dégrade la ligne en indisponible au lieu de faire échouer la vue.
    """
    from backend.plateforme.charge_fiscale import charge_fiscale_mission

    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        missions = _missions_par_exercice(
            session,
            int(mission["contribuable_id"]),
            int(mission["exercice"]),
        )

    exercices: list[dict[str, Any]] = []
    for m in missions:
        # Projection SANS recalcul du panorama existant —
        # charge_fiscale_mission ouvre son propre contexte_tenant,
        # d'où l'appel HORS du with ci-dessus. Tolérance par exercice.
        try:
            panorama = charge_fiscale_mission(
                session, tenant_id, int(m["id"])
            )
            composantes = panorama.get("composantes") or {}
            exercices.append(
                {
                    "exercice": int(m["exercice"]),
                    "mission_id": int(m["id"]),
                    "disponible": bool(panorama.get("disponible")),
                    "total": panorama.get("total_charge_propre_estimee"),
                    "composantes": {
                        cle: (composantes.get(cle) or {}).get(
                            "montant_estime"
                        )
                        for cle in COMPOSANTES_EVOLUTION
                    },
                }
            )
        except Exception:  # noqa: BLE001 — exercice annexe toléré
            exercices.append(
                {
                    "exercice": int(m["exercice"]),
                    "mission_id": int(m["id"]),
                    "disponible": False,
                    "total": None,
                    "composantes": {},
                }
            )

    vue = construire_evolution(exercices)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
