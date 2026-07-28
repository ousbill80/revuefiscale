"""Panorama consultatif de la charge fiscale estimée de la mission.

POURQUOI : au fil de la revue, les estimations d'impôts sont
dispersées sur plusieurs écrans (IS théorique, patente, impôts sur
salaires déclarés, TVA déclarée, acomptes versés). Le fiscaliste a
besoin d'une VUE D'ENSEMBLE de la charge fiscale estimée pour cadrer
la restitution — sans refaire aucun calcul.

AGRÉGAT STRICT (aucun recalcul, aucune invention) : chaque composante
reprend telle quelle l'estimation DÉJÀ produite par le module
existant :

- :mod:`backend.plateforme.resultat_fiscal` — IS théorique du tableau
  de passage (résultat fiscal, signal IMF) ;
- :mod:`backend.plateforme.patente` — estimation PARTIELLE de la
  patente (droit sur le chiffre d'affaires seul) ;
- :mod:`backend.plateforme.rapprochement_salaires` — ITS retenu et
  contribution employeur DÉCLARÉS (sommes des déclarations saisies) ;
- :mod:`backend.plateforme.rapprochement_tva` — TVA nette DÉCLARÉE
  (collectée - déductible, sommes des déclarations saisies) ;
- :mod:`backend.plateforme.acomptes` — position de solde IS projetée
  (solde à payer / crédit à reporter).

TOTAL « CHARGE PROPRE » (règle retenue, documentée) : somme des
composantes DISPONIBLES parmi IS théorique, patente et impôts sur
salaires — total PARTIEL par construction (patente sans droit sur la
valeur locative, impôts non couverts absents). La TVA est un impôt
COLLECTÉ pour le compte de l'État : elle est présentée SÉPARÉMENT et
jamais additionnée à la charge propre. Les acomptes sont une POSITION
de trésorerie (l'IS dû est déjà porté par la composante IS) : jamais
additionnés non plus — sinon double compte.

TOLÉRANCE : chaque composante est tentée indépendamment (pattern
:mod:`backend.plateforme.dossier_mission`, constructeurs appelés HORS
de tout ``with``) — un module en échec donne une composante
``{"disponible": false}``, jamais bloquante. Seule une mission hors
tenant lève (→ 404 côté route, via
:func:`backend.plateforme.missions.lire_mission`).

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
panorama éclaire, l'humain liquide, apprécie et décide. Lecture
seule, aucune écriture hors journal d'audit. Montants sérialisés en
``str`` (Decimal). Clés TOUJOURS présentes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy.orm import Session

# ── Constantes ───────────────────────────────────────────────────────

#: Composantes du panorama — l'assembleur garantit leur présence.
COMPOSANTES_PANORAMA: Final[tuple[str, ...]] = (
    "is",
    "patente",
    "salaires",
    "tva",
    "acomptes",
)

#: Composantes additionnées dans la charge propre estimée — la TVA
#: (impôt collecté) et les acomptes (position de trésorerie, l'IS dû
#: est déjà porté par la composante « is ») en sont EXCLUS.
COMPOSANTES_CHARGE_PROPRE: Final[tuple[str, ...]] = (
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
        "employeur, sommes des déclarations saisies)"
    ),
    "tva": (
        "TVA nette déclarée (collectée - déductible) — impôt collecté, "
        "présenté séparément"
    ),
    "acomptes": (
        "Acomptes IS versés — position de solde projetée (jamais "
        "additionnée : l'IS dû est déjà compté)"
    ),
}

STATUT_COMPLET: Final = "complet"
STATUT_PARTIEL: Final = "partiel"
STATUT_INDISPONIBLE: Final = "indisponible"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_COMPLET: (
        "Panorama complet — toutes les composantes suivies sont "
        "estimées (le total reste partiel : impôts non couverts, "
        "patente sans droit sur la valeur locative)"
    ),
    STATUT_PARTIEL: (
        "Panorama partiel — certaines composantes sont indisponibles "
        "(balance, déclarations ou saisies manquantes)"
    ),
    STATUT_INDISPONIBLE: (
        "Panorama indisponible — importez la balance et saisissez les "
        "déclarations pour estimer la charge fiscale"
    ),
}

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_CHARGE_FISCALE: Final = (
    "Panorama consultatif de la charge fiscale estimée : simple "
    "agrégat des estimations déjà produites par les modules de la "
    "revue (IS théorique du tableau de passage, patente partielle "
    "au droit sur le chiffre d'affaires, impôts sur salaires et TVA "
    "tels que déclarés, position d'acomptes). Le total de charge "
    "propre est PARTIEL par construction et exclut la TVA (impôt "
    "collecté pour le compte de l'État) ainsi que la position "
    "d'acomptes (trésorerie, l'IS dû étant déjà compté). Aucun "
    "recalcul, aucune liquidation : l'humain apprécie et décide."
)

REFERENCES_CHARGE_FISCALE: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, impôt BIC des personnes morales",
        "portee": (
            "IS théorique au taux normal de 25 % appliqué au résultat "
            "fiscal du tableau de passage (signal IMF consultatif)"
        ),
    },
    {
        "reference": "CGI, art. 264 et s.",
        "portee": (
            "Contribution des patentes — seule l'estimation partielle "
            "du droit sur le chiffre d'affaires est reprise ici"
        ),
    },
    {
        "reference": "CGI, impôts sur traitements et salaires",
        "portee": (
            "ITS retenu et contribution employeur repris tels que "
            "déclarés par périodes (aucune reconstitution de paie)"
        ),
    },
    {
        "reference": "CGI, TVA",
        "portee": (
            "TVA nette déclarée (collectée - déductible) — impôt "
            "collecté, présenté séparément de la charge propre"
        ),
    },
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_charge_fiscale"


class ErreurChargeFiscale(Exception):
    """Échec du panorama de charge fiscale."""


class ErreurChargeFiscaleIntrouvable(ErreurChargeFiscale):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def composante_indisponible(cle: str) -> dict[str, Any]:
    """PUR — composante dégradée (module en échec ou données absentes).

    Clés stables : le frontend n'a jamais d'attribut absent à deviner.
    """
    return {
        "disponible": False,
        "libelle": LIBELLES_COMPOSANTES.get(cle, cle),
        "montant_estime": None,
        "incluse_dans_total": cle in COMPOSANTES_CHARGE_PROPRE,
    }


def assembler_charge_fiscale(
    composantes: dict[str, Any],
) -> dict[str, Any]:
    """PUR — assemble le panorama depuis les composantes (testable).

    Chaque clé de :data:`COMPOSANTES_PANORAMA` est toujours présente :
    composante manquante, non-dict ou sans ``disponible`` vrai →
    :func:`composante_indisponible`. Le total de charge propre
    additionne les ``montant_estime`` (str Decimal) des composantes
    DISPONIBLES de :data:`COMPOSANTES_CHARGE_PROPRE` — total PARTIEL
    documenté, hors TVA (collectée) et hors acomptes (position).
    """
    normalisees: dict[str, dict[str, Any]] = {}
    for cle in COMPOSANTES_PANORAMA:
        brut = composantes.get(cle)
        if isinstance(brut, dict) and "disponible" in brut:
            normalisees[cle] = {
                **brut,
                "libelle": str(
                    brut.get("libelle")
                    or LIBELLES_COMPOSANTES.get(cle, cle)
                ),
                "incluse_dans_total": cle in COMPOSANTES_CHARGE_PROPRE,
            }
        else:
            normalisees[cle] = composante_indisponible(cle)

    total = Decimal("0")
    incluses: list[str] = []
    for cle in COMPOSANTES_CHARGE_PROPRE:
        c = normalisees[cle]
        if c["disponible"] and c.get("montant_estime") is not None:
            total += Decimal(str(c["montant_estime"]))
            incluses.append(cle)

    indisponibles = [
        cle
        for cle in COMPOSANTES_PANORAMA
        if not normalisees[cle]["disponible"]
    ]
    nb_disponibles = len(COMPOSANTES_PANORAMA) - len(indisponibles)
    if nb_disponibles == 0:
        statut = STATUT_INDISPONIBLE
    elif indisponibles:
        statut = STATUT_PARTIEL
    else:
        statut = STATUT_COMPLET

    tva = normalisees["tva"]
    return {
        "disponible": nb_disponibles > 0,
        "composantes": normalisees,
        # Total PARTIEL documenté : composantes disponibles hors TVA
        # (impôt collecté) et hors acomptes (position de trésorerie).
        "total_charge_propre_estimee": str(total),
        "composantes_incluses_total": incluses,
        "composantes_indisponibles": indisponibles,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_composantes_disponibles": nb_disponibles,
            "nb_composantes_suivies": len(COMPOSANTES_PANORAMA),
            "total_partiel": True,
            "tva_nette_declaree": (
                tva.get("montant_estime") if tva["disponible"] else None
            ),
        },
        "note": NOTE_CHARGE_FISCALE,
        "references": [dict(r) for r in REFERENCES_CHARGE_FISCALE],
    }


# ── Constructeurs de composantes (modules existants, aucun recalcul) ─


def _composante_is(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """IS théorique — reprend le tableau de passage tel quel.

    :func:`backend.plateforme.resultat_fiscal.vue_resultat_fiscal_mission`
    calcule déjà résultat fiscal, IS théorique (25 %) et signal IMF.
    """
    from backend.plateforme.resultat_fiscal import (
        vue_resultat_fiscal_mission,
    )

    v = vue_resultat_fiscal_mission(session, tenant_id, mission_id)
    disponible = bool(v.get("disponible"))
    imf = v.get("imf") or {}
    return {
        "disponible": disponible,
        "libelle": LIBELLES_COMPOSANTES["is"],
        "montant_estime": v.get("is_theorique") if disponible else None,
        "resultat_fiscal": (
            v.get("resultat_fiscal") if disponible else None
        ),
        "taux_is_normal": v.get("taux_is_normal"),
        "imf_possible": bool(imf.get("possible")),
        "imf_libelle": imf.get("libelle"),
        "statut": (v.get("synthese") or {}).get("statut"),
    }


def _composante_patente(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Patente — reprend l'estimation partielle (droit CA) telle quelle.

    :func:`backend.plateforme.patente.vue_patente_mission` estime déjà
    le droit sur le chiffre d'affaires (plancher/plafond appliqués) ;
    le droit sur la valeur locative n'est jamais estimé.
    """
    from backend.plateforme.patente import vue_patente_mission

    p = vue_patente_mission(session, tenant_id, mission_id)
    disponible = bool(p.get("disponible"))
    return {
        "disponible": disponible,
        "libelle": LIBELLES_COMPOSANTES["patente"],
        "montant_estime": (
            p.get("estimation_totale_partielle") if disponible else None
        ),
        "chiffre_affaires": (
            p.get("chiffre_affaires") if disponible else None
        ),
        "plancher_applique": bool(p.get("plancher_applique")),
        "plafond_applique": bool(p.get("plafond_applique")),
        "estimation_partielle": True,
    }


def _composante_salaires(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Impôts sur salaires — sommes DÉCLARÉES reprises telles quelles.

    :func:`backend.plateforme.rapprochement_salaires.rapprochement_salaires_mission`
    totalise déjà l'ITS retenu et la contribution employeur des
    déclarations saisies. Disponible dès qu'une période est déclarée
    (le rapprochement avec la balance reste sur l'écran dédié) ; le
    montant estimé est la somme ITS + contribution — simple addition
    de totaux existants, aucun recalcul d'assiette.
    """
    from backend.plateforme.rapprochement_salaires import (
        rapprochement_salaires_mission,
    )

    r = rapprochement_salaires_mission(session, tenant_id, mission_id)
    totaux = r.get("totaux_declares") or {}
    nb_periodes = int(
        (r.get("synthese") or {}).get("nb_periodes_declarees") or 0
    )
    disponible = nb_periodes > 0
    its = Decimal(str(totaux.get("its_retenu") or 0))
    contribution = Decimal(str(totaux.get("contribution_employeur") or 0))
    return {
        "disponible": disponible,
        "libelle": LIBELLES_COMPOSANTES["salaires"],
        "montant_estime": str(its + contribution) if disponible else None,
        "its_retenu": str(its) if disponible else None,
        "contribution_employeur": (
            str(contribution) if disponible else None
        ),
        "nb_periodes_declarees": nb_periodes,
    }


def _composante_tva(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """TVA nette déclarée — impôt COLLECTÉ, présenté séparément.

    :func:`backend.plateforme.rapprochement_tva.rapprochement_tva_mission`
    totalise déjà collectée, déductible et nette des déclarations
    saisies. Disponible dès qu'une période est déclarée ; JAMAIS
    additionnée à la charge propre (``incluse_dans_total`` faux).
    """
    from backend.plateforme.rapprochement_tva import (
        rapprochement_tva_mission,
    )

    r = rapprochement_tva_mission(session, tenant_id, mission_id)
    totaux = r.get("totaux_declares") or {}
    nb_periodes = int(
        (r.get("synthese") or {}).get("nb_periodes_declarees") or 0
    )
    disponible = nb_periodes > 0
    return {
        "disponible": disponible,
        "libelle": LIBELLES_COMPOSANTES["tva"],
        "montant_estime": (
            totaux.get("tva_nette") if disponible else None
        ),
        "tva_collectee": (
            totaux.get("tva_collectee") if disponible else None
        ),
        "tva_deductible": (
            totaux.get("tva_deductible") if disponible else None
        ),
        "nb_periodes_declarees": nb_periodes,
        "impot_collecte": True,
    }


def _composante_acomptes(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Acomptes IS — position de solde projetée, jamais additionnée.

    :func:`backend.plateforme.acomptes.vue_acomptes_mission` projette
    déjà la position (solde à payer / crédit à reporter). Composante
    informative de trésorerie : ``montant_estime`` reste ``None`` (l'IS
    dû est déjà porté par la composante « is » — pas de double compte).
    """
    from backend.plateforme.acomptes import vue_acomptes_mission

    a = vue_acomptes_mission(session, tenant_id, mission_id)
    disponible = bool(a.get("disponible"))
    position = a.get("position") or {}
    totaux = a.get("totaux_verses") or {}
    return {
        "disponible": disponible,
        "libelle": LIBELLES_COMPOSANTES["acomptes"],
        "montant_estime": None,
        "position_statut": (
            position.get("statut") if disponible else None
        ),
        "position_libelle": (
            position.get("libelle") if disponible else None
        ),
        "solde_signe": (
            position.get("solde_signe") if disponible else None
        ),
        "total_verse": totaux.get("total"),
        "is_du_estime": a.get("is_du_estime"),
    }


#: Composantes : (clé, constructeur) — chacune est TOLÉRANTE.
_CONSTRUCTEURS: Final[
    tuple[tuple[str, Callable[[Session, int, int], dict[str, Any]]], ...]
] = (
    ("is", _composante_is),
    ("patente", _composante_patente),
    ("salaires", _composante_salaires),
    ("tva", _composante_tva),
    ("acomptes", _composante_acomptes),
)


# ── Lecture mission (RLS) ────────────────────────────────────────────


def charge_fiscale_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Panorama de charge fiscale de la mission (LECTURE SEULE, RLS).

    Agrège les estimations existantes sans dupliquer aucun calcul.
    Mission hors tenant → :class:`ErreurChargeFiscaleIntrouvable`
    (→ 404 côté route) via le module existant
    :func:`backend.plateforme.missions.lire_mission`. Chaque
    composante est tentée indépendamment (try/except) : un sous-module
    en échec donne ``{"disponible": false}``, jamais bloquant. Chaque
    constructeur ouvre son propre ``contexte_tenant`` : appels HORS de
    tout autre ``with`` (pattern dossier_mission).
    """
    from backend.plateforme.missions import ErreurMission, lire_mission

    try:
        mission = lire_mission(session, tenant_id, mission_id)
    except ErreurMission as e:
        raise ErreurChargeFiscaleIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        ) from e

    composantes: dict[str, Any] = {}
    for cle, construire in _CONSTRUCTEURS:
        # Tolérance par composante : un sous-module en échec n'empêche
        # jamais la remise du panorama (pattern dossier_mission).
        try:
            composantes[cle] = construire(session, tenant_id, mission_id)
        except Exception:  # noqa: BLE001 — composante annexe tolérée
            composantes[cle] = None

    vue = assembler_charge_fiscale(composantes)
    vue["mission_id"] = mission_id
    vue["exercice"] = (
        int(mission["exercice"])
        if mission.get("exercice") is not None
        else None
    )
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
