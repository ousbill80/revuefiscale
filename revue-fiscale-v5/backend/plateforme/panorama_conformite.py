"""Panorama de conformité de la mission — agrégat de STATUTS consultatifs.

POURQUOI : les vues fiscales consultatives (complétude déclarative,
cohérence CA/TVA, retenues, déficits, acomptes, patente, charge
fiscale) sont dispersées sur plusieurs écrans. Le fiscaliste a besoin
d'un BANDEAU compact qui agrège leurs STATUTS — jamais leurs montants —
pour repérer d'un coup d'œil les volets à examiner.

AGRÉGAT STRICT DE STATUTS (aucun recalcul, aucun montant repris) :
chaque volet reprend tel quel le statut DÉJÀ produit par le module
existant, puis le classe dans un NIVEAU D'ATTENTION fermé :

- ``a_examiner`` — un signal appelle une lecture (écart à expliquer,
  aucune saisie, complétude lacunaire) ;
- ``a_qualifier`` — une qualification HUMAINE est requise (retenues
  sur loyers / honoraires : assiette et redevables à apprécier) ;
- ``a_suivre`` — un point de suivi indicatif existe (déficits à
  suivre, solde ou excédent indicatif, estimation partielle) ;
- ``sans_signal`` — la vue ne relève aucun point particulier
  (cohérent, complet, aucun déficit, équilibre, sans période échue) ;
- ``indisponible`` — la vue n'a pas pu être servie (données absentes
  ou module en échec).

AUCUN SCORE CHIFFRÉ, AUCUN CUMUL PONDÉRÉ : de simples compteurs par
niveau et la liste des volets. Un niveau n'est jamais une conclusion —
formulations non accusatoires, vocabulaire fermé.

TOLÉRANCE : chaque volet est tenté indépendamment (pattern
:mod:`backend.plateforme.dossier_mission`, constructeurs appelés HORS
de tout ``with``) — un module en échec donne un volet ``indisponible``
listé dans ``volets_en_echec``, jamais bloquant. Seule une mission
hors tenant lève (→ 404 côté route, via
:func:`backend.plateforme.missions.lire_mission`).

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
panorama oriente la lecture, il ne conclut rien : chaque volet
s'apprécie dans sa vue détaillée. Lecture seule, aucune écriture hors
journal d'audit. Clés TOUJOURS présentes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Final

from sqlalchemy.orm import Session

# ── Constantes ───────────────────────────────────────────────────────

NIVEAU_A_EXAMINER: Final = "a_examiner"
NIVEAU_A_QUALIFIER: Final = "a_qualifier"
NIVEAU_A_SUIVRE: Final = "a_suivre"
NIVEAU_SANS_SIGNAL: Final = "sans_signal"
NIVEAU_INDISPONIBLE: Final = "indisponible"

#: Niveaux d'attention — ordre de présentation (vocabulaire fermé).
NIVEAUX_ATTENTION: Final[tuple[str, ...]] = (
    NIVEAU_A_EXAMINER,
    NIVEAU_A_QUALIFIER,
    NIVEAU_A_SUIVRE,
    NIVEAU_SANS_SIGNAL,
    NIVEAU_INDISPONIBLE,
)

LIBELLES_NIVEAUX: Final[dict[str, str]] = {
    NIVEAU_A_EXAMINER: (
        "À examiner — un signal appelle une lecture de la vue détaillée"
    ),
    NIVEAU_A_QUALIFIER: (
        "À qualifier — une appréciation humaine est requise"
    ),
    NIVEAU_A_SUIVRE: "À suivre — point de suivi indicatif",
    NIVEAU_SANS_SIGNAL: (
        "Sans signal particulier — la vue ne relève aucun point"
    ),
    NIVEAU_INDISPONIBLE: (
        "Indisponible — la vue n'a pas pu être servie"
    ),
}

#: Classement d'un statut SOURCE (produit par un module existant) en
#: niveau d'attention. Statut inconnu ou absent → ``indisponible``
#: (défensif : jamais d'invention de signal).
CLASSEMENT_STATUTS: Final[dict[str, str]] = {
    # Signaux appelant une lecture.
    "ecart_a_expliquer": NIVEAU_A_EXAMINER,
    "aucune_saisie": NIVEAU_A_EXAMINER,
    "lacunaire": NIVEAU_A_EXAMINER,
    # Qualification humaine requise (retenues à la source).
    "a_qualifier": NIVEAU_A_QUALIFIER,
    # Points de suivi indicatifs.
    "deficits_a_suivre": NIVEAU_A_SUIVRE,
    "solde_a_payer_indicatif": NIVEAU_A_SUIVRE,
    "excedent_indicatif": NIVEAU_A_SUIVRE,
    # Estimations partielles disponibles (patente, charge fiscale) :
    # simple point de suivi, jamais un signal d'anomalie.
    "estimation_partielle": NIVEAU_A_SUIVRE,
    "partiel": NIVEAU_A_SUIVRE,
    # Aucun point particulier relevé.
    "coherent": NIVEAU_SANS_SIGNAL,
    "complet": NIVEAU_SANS_SIGNAL,
    "aucun_deficit": NIVEAU_SANS_SIGNAL,
    "equilibre_indicatif": NIVEAU_SANS_SIGNAL,
    "sans_periode_echue": NIVEAU_SANS_SIGNAL,
    # Vue explicitement indisponible.
    "indisponible": NIVEAU_INDISPONIBLE,
}

#: Volets agrégés — clé et libellé (l'assembleur garantit leur
#: présence, dans cet ordre).
LIBELLES_VOLETS: Final[dict[str, str]] = {
    "completude_declarative": (
        "Complétude déclarative (TVA / salaires)"
    ),
    "coherence_ca": "Cohérence CA / TVA",
    "retenue_loyers": "Retenue sur loyers",
    "retenue_honoraires": "Retenue sur honoraires",
    "deficits_reportables": "Déficits reportables",
    "rapprochement_acomptes": "Rapprochement acomptes / IS théorique",
    "patente": "Contribution des patentes (estimation partielle)",
    "charge_fiscale": "Charge fiscale estimée (panorama)",
}

VOLETS_PANORAMA: Final[tuple[str, ...]] = tuple(LIBELLES_VOLETS)

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_PANORAMA_CONFORMITE: Final = (
    "Panorama consultatif de conformité : simple agrégat des statuts "
    "déjà produits par les vues fiscales de la revue, classés en "
    "niveaux d'attention (à examiner, à qualifier, à suivre, sans "
    "signal, indisponible). Aucun score, aucun cumul pondéré, aucun "
    "montant repris : le panorama oriente la lecture, il ne conclut "
    "rien — chaque volet s'apprécie dans sa vue détaillée. L'humain "
    "décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_panorama_conformite"


class ErreurPanoramaConformite(Exception):
    """Échec du panorama de conformité."""


class ErreurPanoramaIntrouvable(ErreurPanoramaConformite):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def classer_statut(statut_source: str | None) -> str:
    """PUR — classe un statut source en niveau d'attention.

    Vocabulaire fermé : statut inconnu, vide ou absent →
    ``indisponible`` (défensif — jamais d'invention de signal).
    """
    if not statut_source:
        return NIVEAU_INDISPONIBLE
    return CLASSEMENT_STATUTS.get(str(statut_source), NIVEAU_INDISPONIBLE)


def volet_indisponible(cle: str) -> dict[str, Any]:
    """PUR — volet dégradé (module en échec ou données absentes).

    Clés stables : le frontend n'a jamais d'attribut absent à deviner.
    """
    return {
        "volet": cle,
        "libelle": LIBELLES_VOLETS.get(cle, cle),
        "disponible": False,
        "statut_source": None,
        "niveau": NIVEAU_INDISPONIBLE,
    }


def assembler_panorama(volets: dict[str, Any]) -> dict[str, Any]:
    """PUR — assemble le panorama depuis les statuts par volet.

    ``volets`` : par clé de :data:`VOLETS_PANORAMA`, un dict
    ``{"disponible": bool, "statut_source": str | None}`` — ou ``None``
    / non-dict si le module a échoué (→ volet ``indisponible`` listé
    dans ``volets_en_echec``). Compteurs par niveau, AUCUN score.
    """
    lignes: list[dict[str, Any]] = []
    en_echec: list[str] = []
    compteurs: dict[str, int] = {n: 0 for n in NIVEAUX_ATTENTION}
    for cle in VOLETS_PANORAMA:
        brut = volets.get(cle)
        if isinstance(brut, dict) and "disponible" in brut:
            statut = brut.get("statut_source")
            ligne = {
                "volet": cle,
                "libelle": LIBELLES_VOLETS.get(cle, cle),
                "disponible": bool(brut.get("disponible")),
                "statut_source": (
                    str(statut) if statut is not None else None
                ),
                "niveau": classer_statut(statut),
            }
        else:
            ligne = volet_indisponible(cle)
            en_echec.append(cle)
        compteurs[ligne["niveau"]] += 1
        lignes.append(ligne)

    nb_disponibles = sum(1 for ligne in lignes if ligne["disponible"])
    return {
        "disponible": nb_disponibles > 0,
        "volets": lignes,
        # Simples compteurs par niveau — AUCUN score, AUCUNE pondération.
        "compteurs": {n: compteurs[n] for n in NIVEAUX_ATTENTION},
        "volets_en_echec": en_echec,
        "nb_volets_suivis": len(VOLETS_PANORAMA),
        "nb_volets_disponibles": nb_disponibles,
        "libelles_niveaux": dict(LIBELLES_NIVEAUX),
        "note": NOTE_PANORAMA_CONFORMITE,
    }


# ── Extracteurs de statuts (modules existants, aucun recalcul) ───────


def _volet_completude_declarative(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut global de la complétude déclarative — repris tel quel."""
    from backend.plateforme.completude_declarative import (
        completude_declarative_mission,
    )

    c = completude_declarative_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(c.get("disponible")),
        "statut_source": (c.get("synthese") or {}).get("statut_global"),
    }


def _volet_coherence_ca(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut de la cohérence CA / TVA — repris tel quel."""
    from backend.plateforme.coherence_ca import coherence_ca_mission

    c = coherence_ca_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(c.get("disponible")),
        "statut_source": c.get("statut"),
    }


def _volet_retenue_loyers(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut de la retenue sur loyers — repris tel quel."""
    from backend.plateforme.retenue_loyers import (
        vue_retenue_loyers_mission,
    )

    r = vue_retenue_loyers_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(r.get("disponible")),
        "statut_source": r.get("statut"),
    }


def _volet_retenue_honoraires(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut de la retenue sur honoraires — repris tel quel."""
    from backend.plateforme.retenue_honoraires import (
        vue_retenue_honoraires_mission,
    )

    r = vue_retenue_honoraires_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(r.get("disponible")),
        "statut_source": r.get("statut"),
    }


def _volet_deficits_reportables(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut du suivi des déficits reportables — repris tel quel."""
    from backend.plateforme.deficits_reportables import (
        vue_deficits_reportables_mission,
    )

    d = vue_deficits_reportables_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(d.get("disponible")),
        "statut_source": d.get("statut"),
    }


def _volet_rapprochement_acomptes(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut du rapprochement acomptes / IS — repris tel quel."""
    from backend.plateforme.rapprochement_acomptes import (
        vue_rapprochement_acomptes_mission,
    )

    r = vue_rapprochement_acomptes_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(r.get("disponible")),
        "statut_source": r.get("statut"),
    }


def _volet_patente(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut de l'estimation de patente — repris tel quel."""
    from backend.plateforme.patente import vue_patente_mission

    p = vue_patente_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(p.get("disponible")),
        "statut_source": (p.get("synthese") or {}).get("statut"),
    }


def _volet_charge_fiscale(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Statut du panorama de charge fiscale — repris tel quel."""
    from backend.plateforme.charge_fiscale import charge_fiscale_mission

    c = charge_fiscale_mission(session, tenant_id, mission_id)
    return {
        "disponible": bool(c.get("disponible")),
        "statut_source": (c.get("synthese") or {}).get("statut"),
    }


#: Volets : (clé, extracteur) — chacun est TOLÉRANT.
_EXTRACTEURS: Final[
    tuple[tuple[str, Callable[[Session, int, int], dict[str, Any]]], ...]
] = (
    ("completude_declarative", _volet_completude_declarative),
    ("coherence_ca", _volet_coherence_ca),
    ("retenue_loyers", _volet_retenue_loyers),
    ("retenue_honoraires", _volet_retenue_honoraires),
    ("deficits_reportables", _volet_deficits_reportables),
    ("rapprochement_acomptes", _volet_rapprochement_acomptes),
    ("patente", _volet_patente),
    ("charge_fiscale", _volet_charge_fiscale),
)


# ── Lecture mission (RLS) ────────────────────────────────────────────


def panorama_conformite_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Panorama de conformité de la mission (LECTURE SEULE, RLS).

    Agrège les statuts existants sans dupliquer aucun calcul. Mission
    hors tenant → :class:`ErreurPanoramaIntrouvable` (→ 404 côté
    route) via :func:`backend.plateforme.missions.lire_mission`.
    Chaque volet est tenté indépendamment (try/except) : un sous-module
    en échec donne un volet ``indisponible`` listé dans
    ``volets_en_echec``, jamais bloquant. Chaque extracteur ouvre son
    propre ``contexte_tenant`` : appels HORS de tout autre ``with``
    (pattern dossier_mission / charge_fiscale).
    """
    from backend.plateforme.missions import ErreurMission, lire_mission

    try:
        mission = lire_mission(session, tenant_id, mission_id)
    except ErreurMission as e:
        raise ErreurPanoramaIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        ) from e

    volets: dict[str, Any] = {}
    for cle, extraire in _EXTRACTEURS:
        # Tolérance par volet : un sous-module en échec n'empêche
        # jamais la remise du panorama (pattern dossier_mission).
        try:
            volets[cle] = extraire(session, tenant_id, mission_id)
        except Exception:  # noqa: BLE001 — volet annexe toléré
            volets[cle] = None

    vue = assembler_panorama(volets)
    vue["mission_id"] = mission_id
    vue["exercice"] = (
        int(mission["exercice"])
        if mission.get("exercice") is not None
        else None
    )
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
