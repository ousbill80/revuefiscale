"""Fil conducteur de la mission — guide pas-à-pas en LECTURE SEULE.

POURQUOI : le fiscaliste dispose de nombreux écrans spécialisés
(lettre de mission, data room, matérialité, rapprochements, résultat
fiscal, restitution, suivi…) mais d'aucune vue qui le GUIDE à travers
les étapes du process de revue : où en suis-je, qu'ai-je déjà couvert,
que reste-t-il ? Ce module dérive l'état de chaque étape des MODULES
EXISTANTS — il ne réimplémente aucune logique métier, il appelle leurs
fonctions et projette leurs synthèses en statuts d'étapes.

CONSULTATIF : la progression suggérée n'impose rien — l'humain décide
de l'ordre réel de ses travaux. Module déterministe, AUCUN LLM, AUCUNE
écriture, RLS via les fonctions réutilisées (chacune ouvre son propre
``contexte_tenant`` — appels HORS de tout ``with``, même pattern que
:mod:`backend.plateforme.pilotage_mission`).

TOLÉRANCE (pattern :mod:`backend.plateforme.dossier_mission`) : une
source en échec vaut ``None`` → étape « indisponible », jamais
bloquante. Seule une mission hors tenant lève (→ 404 côté route), via
le PREMIER module appelé (lettre de mission).

RÈGLES DE STATUT — déterministes, documentées par étape :

1. ``cadrage`` : faite si responsable affecté ET honoraires convenus
   (lettre de mission complète) ; en_cours si l'un des deux ; a_faire
   sinon.
2. ``collecte`` : faite si taux de complétude data room = 100 % ;
   en_cours si au moins une pièce attendue est présente ; a_faire
   sinon.
3. ``ciblage`` : faite si seuil de matérialité retenu ET au moins une
   diligence du programme cochée ; en_cours si l'un des deux ; a_faire
   sinon (le programme standard initialisé seul ne suffit pas).
4. ``revues`` : faite si les 4 revues (rapprochement TVA, rapprochement
   salaires, déductibilité, revue analytique) sont disponibles ;
   en_cours si 1 à 3 le sont ; a_faire si aucune.
5. ``liquidation`` : faite si résultat fiscal établi (passage
   disponible ou retraitement saisi) ET position d'acomptes projetée ;
   en_cours si l'un des deux ; a_faire sinon.
6. ``restitution`` : faite si compte-rendu consigné ET au moins un
   point convenu saisi ; en_cours si l'un des deux ; a_faire sinon.
7. ``suivi`` : faite si aucun point antérieur restant ET aucune
   échéance de contrôle fiscal proche ou dépassée ; en_cours sinon
   (le suivi se constate — « a_faire » n'est pas émis pour cette
   étape).

Pour chaque étape, ``indisponible`` si TOUTES ses sources sont en
échec ; une source en échec parmi d'autres est simplement ignorée
(signalée dans le détail).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy.orm import Session

# ── Constantes ───────────────────────────────────────────────────────

STATUT_FAITE: Final[str] = "faite"
STATUT_EN_COURS: Final[str] = "en_cours"
STATUT_A_FAIRE: Final[str] = "a_faire"
STATUT_INDISPONIBLE: Final[str] = "indisponible"

STATUTS_ETAPE: Final[tuple[str, ...]] = (
    STATUT_FAITE,
    STATUT_EN_COURS,
    STATUT_A_FAIRE,
    STATUT_INDISPONIBLE,
)

#: Étapes du fil conducteur — (code, libellé) dans l'ordre du process.
ETAPES_FIL: Final[tuple[tuple[str, str], ...]] = (
    ("cadrage", "Cadrage de la mission"),
    ("collecte", "Collecte des pièces"),
    ("ciblage", "Ciblage des travaux"),
    ("revues", "Revues fiscales"),
    ("liquidation", "Liquidation de l'impôt"),
    ("restitution", "Restitution au client"),
    ("suivi", "Suivi des points et contrôles"),
)

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_FAITE: "Faite",
    STATUT_EN_COURS: "En cours",
    STATUT_A_FAIRE: "À faire",
    STATUT_INDISPONIBLE: "Indisponible",
}

MENTION_NOTE: Final[str] = (
    "Fil conducteur consultatif de la mission — l'état de chaque étape "
    "est dérivé de manière déterministe des modules existants (lettre "
    "de mission, data room, matérialité, programme de travail, "
    "rapprochements, résultat fiscal, acomptes, restitution, suivi). "
    "La progression suggérée n'impose rien : le fiscaliste apprécie et "
    "décide de l'ordre réel de ses travaux."
)


class ErreurFilConducteur(Exception):
    """Échec métier du fil conducteur."""


class ErreurFilConducteurIntrouvable(ErreurFilConducteur):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Aides pures ──────────────────────────────────────────────────────


def _decimal(valeur: object) -> Decimal | None:
    """PUR — conversion prudente en Decimal (None si impossible)."""
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _etape(code: str, statut: str, detail: str) -> dict[str, Any]:
    """PUR — étape normalisée {code, libelle, statut, detail}."""
    libelles = dict(ETAPES_FIL)
    return {
        "code": code,
        "libelle": libelles.get(code, code),
        "statut": statut,
        "detail": detail,
    }


# ── Fonctions pures de statut (une par étape) ────────────────────────


def statut_cadrage(
    lettre: dict[str, Any] | None, responsable: dict[str, Any] | None
) -> dict[str, Any]:
    """PUR — étape 1 : lettre de mission + responsable affecté.

    Faite si responsable affecté ET honoraires convenus (lettre
    complète) ; en_cours si l'un des deux ; a_faire sinon ;
    indisponible si les deux sources sont en échec.
    """
    if lettre is None and responsable is None:
        return _etape(
            "cadrage", STATUT_INDISPONIBLE, "Sources de cadrage en échec."
        )
    honoraires_ok = bool(lettre and lettre.get("honoraires") is not None)
    email = str((responsable or {}).get("responsable_email") or "").strip()
    responsable_ok = bool(email)
    morceaux = [
        "Lettre de mission : honoraires convenus."
        if honoraires_ok
        else "Lettre de mission : honoraires non convenus.",
        f"Responsable : {email}."
        if responsable_ok
        else "Aucun responsable affecté.",
    ]
    if honoraires_ok and responsable_ok:
        statut = STATUT_FAITE
    elif honoraires_ok or responsable_ok:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("cadrage", statut, " ".join(morceaux))


def statut_collecte(completude: dict[str, Any] | None) -> dict[str, Any]:
    """PUR — étape 2 : complétude de la data room.

    Faite si taux de complétude = 100 % ; en_cours si au moins une
    pièce attendue est présente ; a_faire sinon ; indisponible si la
    source est en échec.
    """
    if completude is None:
        return _etape(
            "collecte", STATUT_INDISPONIBLE, "Complétude data room en échec."
        )
    taux = _decimal(completude.get("taux_completude"))
    presentes = int(completude.get("presentes") or 0)
    manquantes = int(completude.get("essentielles_manquantes") or 0)
    detail = (
        f"Complétude data room : {taux if taux is not None else '?'} % "
        f"({manquantes} essentielle(s) manquante(s))."
    )
    if taux is not None and taux >= Decimal("100"):
        statut = STATUT_FAITE
    elif presentes > 0:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("collecte", statut, detail)


def statut_ciblage(
    materialite: dict[str, Any] | None, programme: dict[str, Any] | None
) -> dict[str, Any]:
    """PUR — étape 3 : seuil de matérialité + programme de travail.

    Faite si seuil retenu ET au moins une diligence cochée ; en_cours
    si l'un des deux ; a_faire sinon (le programme standard initialisé
    seul ne suffit pas) ; indisponible si les deux sources en échec.
    """
    if materialite is None and programme is None:
        return _etape(
            "ciblage", STATUT_INDISPONIBLE, "Sources de ciblage en échec."
        )
    seuil_ok = bool(materialite and materialite.get("seuil_retenu"))
    faites = int((programme or {}).get("faites") or 0)
    total = int((programme or {}).get("total") or 0)
    morceaux = [
        "Seuil de matérialité retenu."
        if seuil_ok
        else "Seuil de matérialité non retenu.",
        f"Programme de travail : {faites}/{total} diligence(s) cochée(s).",
    ]
    if seuil_ok and faites > 0:
        statut = STATUT_FAITE
    elif seuil_ok or faites > 0:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("ciblage", statut, " ".join(morceaux))


#: Revues de l'étape 4 — (clé de source, libellé court).
_REVUES: Final[tuple[tuple[str, str], ...]] = (
    ("rapprochement_tva", "rapprochement TVA"),
    ("rapprochement_salaires", "rapprochement salaires"),
    ("deductibilite", "déductibilité"),
    ("revue_analytique", "revue analytique"),
)


def statut_revues(sources: dict[str, Any]) -> dict[str, Any]:
    """PUR — étape 4 : disponibilité des 4 revues.

    ``sources`` : ``{cle: {"disponible": bool} | None}`` pour les clés
    de :data:`_REVUES`. Faite si les 4 revues sont disponibles ;
    en_cours si 1 à 3 ; a_faire si aucune ; indisponible si toutes les
    sources sont en échec.
    """
    valeurs = {cle: sources.get(cle) for cle, _ in _REVUES}
    if all(v is None for v in valeurs.values()):
        return _etape(
            "revues", STATUT_INDISPONIBLE, "Sources des revues en échec."
        )
    disponibles = [
        lib
        for cle, lib in _REVUES
        if (valeurs.get(cle) or {}).get("disponible") is True
    ]
    nb = len(disponibles)
    detail = (
        f"{nb}/{len(_REVUES)} revue(s) disponible(s)"
        + (f" : {', '.join(disponibles)}." if disponibles else ".")
    )
    if nb == len(_REVUES):
        statut = STATUT_FAITE
    elif nb > 0:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("revues", statut, detail)


def statut_liquidation(
    resultat: dict[str, Any] | None, acomptes: dict[str, Any] | None
) -> dict[str, Any]:
    """PUR — étape 5 : résultat fiscal + position d'acomptes.

    Faite si résultat fiscal établi (passage disponible ou au moins un
    retraitement saisi) ET position d'acomptes projetée ; en_cours si
    l'un des deux ; a_faire sinon ; indisponible si les deux sources
    en échec.
    """
    if resultat is None and acomptes is None:
        return _etape(
            "liquidation",
            STATUT_INDISPONIBLE,
            "Sources de liquidation en échec.",
        )
    nb_retraitements = int((resultat or {}).get("nb_retraitements") or 0)
    resultat_ok = bool(
        resultat
        and (resultat.get("disponible") is True or nb_retraitements > 0)
    )
    acomptes_ok = bool(acomptes and acomptes.get("disponible") is True)
    morceaux = [
        f"Résultat fiscal établi ({nb_retraitements} retraitement(s))."
        if resultat_ok
        else "Résultat fiscal non établi.",
        "Position d'acomptes projetée."
        if acomptes_ok
        else "Position d'acomptes non projetée (IS dû estimé non saisi).",
    ]
    if resultat_ok and acomptes_ok:
        statut = STATUT_FAITE
    elif resultat_ok or acomptes_ok:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("liquidation", statut, " ".join(morceaux))


def statut_restitution(
    compte_rendu: dict[str, Any] | None,
    points_convenus: dict[str, Any] | None,
) -> dict[str, Any]:
    """PUR — étape 6 : compte-rendu consigné + points convenus saisis.

    ``compte_rendu`` : ``{"consigne": bool}`` (None si source en
    échec). Faite si compte-rendu consigné ET au moins un point
    convenu ; en_cours si l'un des deux ; a_faire sinon ; indisponible
    si les deux sources en échec.
    """
    if compte_rendu is None and points_convenus is None:
        return _etape(
            "restitution",
            STATUT_INDISPONIBLE,
            "Sources de restitution en échec.",
        )
    cr_ok = bool((compte_rendu or {}).get("consigne"))
    nb_points = int((points_convenus or {}).get("nb_points") or 0)
    morceaux = [
        "Compte-rendu consigné."
        if cr_ok
        else "Compte-rendu non consigné.",
        f"{nb_points} point(s) convenu(s) saisi(s)."
        if nb_points > 0
        else "Aucun point convenu saisi.",
    ]
    if cr_ok and nb_points > 0:
        statut = STATUT_FAITE
    elif cr_ok or nb_points > 0:
        statut = STATUT_EN_COURS
    else:
        statut = STATUT_A_FAIRE
    return _etape("restitution", statut, " ".join(morceaux))


#: Statuts de contrôles fiscaux considérés « à surveiller ».
_CONTROLES_A_SURVEILLER: Final[tuple[str, ...]] = (
    "echeances_proches",
    "echeances_depassees",
)


def statut_suivi(
    anterieurs: dict[str, Any] | None, controles: dict[str, Any] | None
) -> dict[str, Any]:
    """PUR — étape 7 : points antérieurs + contrôles fiscaux.

    Faite si aucun point antérieur restant ET aucune échéance de
    contrôle proche ou dépassée ; en_cours sinon (« a_faire » n'est
    pas émis : le suivi se constate, il ne se prépare pas) ;
    indisponible si les deux sources en échec.
    """
    if anterieurs is None and controles is None:
        return _etape(
            "suivi", STATUT_INDISPONIBLE, "Sources de suivi en échec."
        )
    nb_anterieurs = int((anterieurs or {}).get("total") or 0)
    statut_controles = str((controles or {}).get("statut") or "")
    a_surveiller = statut_controles in _CONTROLES_A_SURVEILLER
    morceaux = [
        f"{nb_anterieurs} point(s) antérieur(s) restant(s)."
        if nb_anterieurs > 0
        else "Aucun point antérieur restant.",
        "Échéances de contrôle fiscal à surveiller."
        if a_surveiller
        else "Aucune échéance de contrôle fiscal à surveiller.",
    ]
    statut = (
        STATUT_FAITE
        if nb_anterieurs == 0 and not a_surveiller
        else STATUT_EN_COURS
    )
    return _etape("suivi", statut, " ".join(morceaux))


# ── Assemblage pur ───────────────────────────────────────────────────


def assembler_fil(etapes: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — fil conducteur normalisé : étapes + synthèse + note.

    Synthèse : ``faites`` / ``total`` et ``prochaine_etape`` = première
    étape non « faite » dans l'ordre du process (``None`` si tout est
    fait) — suggestion consultative, l'humain décide de l'ordre réel.
    """
    faites = sum(1 for e in etapes if e.get("statut") == STATUT_FAITE)
    prochaine = next(
        (
            {"code": e["code"], "libelle": e["libelle"]}
            for e in etapes
            if e.get("statut") != STATUT_FAITE
        ),
        None,
    )
    return {
        "etapes": etapes,
        "synthese": {
            "faites": faites,
            "total": len(etapes),
            "prochaine_etape": prochaine,
        },
        "note": MENTION_NOTE,
    }


# ── Constructeurs tolérants (chacun réutilise un module existant) ────
#
# Chaque constructeur PROJETTE la sortie d'un module existant en petit
# dict pour les fonctions pures. Les fonctions réutilisées ouvrent leur
# PROPRE contexte_tenant (RLS) — appels HORS de tout with.


def _src_lettre(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Lettre de mission — honoraires convenus (identité de la lettre).

    PREMIER module appelé : mission hors tenant →
    :class:`ErreurFilConducteurIntrouvable` (404 côté route).
    """
    from backend.plateforme.lettre_mission import (
        ErreurLettreIntrouvable,
        lettre_mission,
    )

    try:
        lettre = lettre_mission(session, tenant_id, mission_id)
    except ErreurLettreIntrouvable as e:
        raise ErreurFilConducteurIntrouvable(str(e)) from e
    identite = lettre.get("identite") or {}
    return {"honoraires": identite.get("honoraires")}


def _src_responsable(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.responsable_mission import lire_responsable

    r = lire_responsable(session, tenant_id, mission_id)
    return {"responsable_email": r.get("responsable_email")}


def _src_completude(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.completude_data_room import completude_data_room

    s = completude_data_room(session, tenant_id, mission_id).get(
        "synthese"
    ) or {}
    return {
        "taux_completude": s.get("taux_completude"),
        "presentes": s.get("presentes"),
        "essentielles_manquantes": s.get("essentielles_manquantes"),
    }


def _src_materialite(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.materialite import materialite_mission

    m = materialite_mission(session, tenant_id, mission_id)
    return {"seuil_retenu": m.get("seuil_retenu")}


def _src_programme(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.programme_travail import etat_programme

    s = etat_programme(session, tenant_id, mission_id).get("synthese") or {}
    return {"faites": s.get("faites"), "total": s.get("total")}


def _src_disponible(module: str, fonction: str):
    """Fabrique un constructeur projetant seulement ``disponible``."""

    def construire(
        session: Session, tenant_id: int, mission_id: int
    ) -> dict[str, Any]:
        import importlib

        fn = getattr(importlib.import_module(module), fonction)
        vue = fn(session, tenant_id, mission_id)
        return {"disponible": bool(vue.get("disponible"))}

    return construire


def _src_resultat(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.resultat_fiscal import (
        vue_resultat_fiscal_mission,
    )

    v = vue_resultat_fiscal_mission(session, tenant_id, mission_id)
    synthese = v.get("synthese") or {}
    return {
        "disponible": bool(v.get("disponible")),
        "nb_retraitements": synthese.get("nb_retraitements"),
    }


def _src_compte_rendu(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.compte_rendu import lire_compte_rendu

    cr = lire_compte_rendu(session, tenant_id, mission_id)
    return {"consigne": cr is not None}


def _src_points_convenus(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.points_convenus import lister_points_convenus

    p = lister_points_convenus(session, tenant_id, mission_id)
    return {"nb_points": len(p.get("points") or [])}


def _src_anterieurs(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.points_anterieurs import points_anterieurs

    s = points_anterieurs(session, tenant_id, mission_id).get(
        "synthese"
    ) or {}
    return {"total": s.get("total")}


def _src_controles(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    from backend.plateforme.controles_fiscaux import controles_mission

    s = controles_mission(session, tenant_id, mission_id).get(
        "synthese"
    ) or {}
    return {"statut": s.get("statut")}


#: Sources facultatives : (clé, constructeur) — chacune est TOLÉRÉE.
_SOURCES_FACULTATIVES: Final[tuple[tuple[str, Any], ...]] = (
    ("responsable", _src_responsable),
    ("completude", _src_completude),
    ("materialite", _src_materialite),
    ("programme", _src_programme),
    (
        "rapprochement_tva",
        _src_disponible(
            "backend.plateforme.rapprochement_tva",
            "rapprochement_tva_mission",
        ),
    ),
    (
        "rapprochement_salaires",
        _src_disponible(
            "backend.plateforme.rapprochement_salaires",
            "rapprochement_salaires_mission",
        ),
    ),
    (
        "deductibilite",
        _src_disponible(
            "backend.plateforme.deductibilite", "deductibilite_mission"
        ),
    ),
    (
        "revue_analytique",
        _src_disponible(
            "backend.plateforme.revue_analytique",
            "revue_analytique_mission",
        ),
    ),
    ("resultat_fiscal", _src_resultat),
    ("acomptes", _src_disponible("backend.plateforme.acomptes", "vue_acomptes_mission")),
    ("compte_rendu", _src_compte_rendu),
    ("points_convenus", _src_points_convenus),
    ("points_anterieurs", _src_anterieurs),
    ("controles_fiscaux", _src_controles),
)


# ── Lecture mission (RLS via les modules réutilisés) ─────────────────


def fil_conducteur_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Fil conducteur de la mission (LECTURE SEULE, consultatif).

    Dérive l'état des 7 étapes du process des modules existants. La
    PREMIÈRE source (lettre de mission) porte le 404 hors tenant ; les
    autres sont tolérées indépendamment (source en échec → ``None`` →
    étape « indisponible » si toutes ses sources échouent). Chaque
    fonction réutilisée ouvre son propre ``contexte_tenant`` : appels
    HORS de tout ``with``.
    """
    # Première source : porte le 404 hors tenant. En échec « autre »,
    # la source vaut None (tolérance) — le 404 seul est propagé.
    try:
        lettre: dict[str, Any] | None = _src_lettre(
            session, tenant_id, mission_id
        )
    except ErreurFilConducteurIntrouvable:
        raise
    except Exception:  # noqa: BLE001 — source annexe tolérée
        lettre = None

    sources: dict[str, Any] = {"lettre": lettre}
    for cle, construire in _SOURCES_FACULTATIVES:
        # Tolérance par source : un sous-module en échec n'empêche
        # jamais la restitution du fil (pattern dossier_mission).
        try:
            sources[cle] = construire(session, tenant_id, mission_id)
        except Exception:  # noqa: BLE001 — source annexe tolérée
            sources[cle] = None

    etapes = [
        statut_cadrage(sources["lettre"], sources["responsable"]),
        statut_collecte(sources["completude"]),
        statut_ciblage(sources["materialite"], sources["programme"]),
        statut_revues(sources),
        statut_liquidation(sources["resultat_fiscal"], sources["acomptes"]),
        statut_restitution(
            sources["compte_rendu"], sources["points_convenus"]
        ),
        statut_suivi(
            sources["points_anterieurs"], sources["controles_fiscaux"]
        ),
    ]
    fil = assembler_fil(etapes)
    fil["mission_id"] = mission_id
    return fil
