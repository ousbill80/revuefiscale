"""Dossier de synthèse imprimable de la mission — agrégat lecture seule.

POURQUOI : en fin de mission, le fiscaliste remet au client (ou archive)
un document UNIQUE récapitulant la mission : identité du dossier,
synthèse des risques, civisme déclaratif, complétude de la data room,
points convenus, compte-rendu de restitution et délais de traitement.
La page frontend imprime ce dossier via le navigateur (impression → PDF).

Assemblage DÉTERMINISTE et CONSULTATIF (aucun LLM) : chaque bloc est
produit par le MODULE EXISTANT qui alimente déjà son endpoint dédié —
:mod:`backend.plateforme.plan_actions` (risques / exposition),
:mod:`backend.plateforme.civisme_fiscal`,
:mod:`backend.plateforme.completude_data_room`,
:mod:`backend.plateforme.points_convenus`,
:mod:`backend.plateforme.compte_rendu` et
:mod:`backend.plateforme.delais_mission`. Aucun calcul n'est dupliqué.

TOLÉRANCE : un bloc qui échoue ou est vide vaut ``None`` — jamais
bloquant (même pattern que :mod:`backend.plateforme.echeances_cabinet`).
Seule une mission hors tenant lève (→ 404 côté route). Montants déjà
sérialisés en str (Decimal) par les modules réutilisés.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Blocs attendus du dossier — l'assembleur garantit leur présence
#: (bloc indisponible → None, jamais d'attribut manquant côté client).
BLOCS_DOSSIER: Final[tuple[str, ...]] = (
    "identite",
    "risques",
    "civisme",
    "completude",
    "points_convenus",
    "compte_rendu",
    "delais",
    "rapprochement_tva",
    "controles_fiscaux",
    "materialite",
    "acomptes",
    "rapprochement_salaires",
    "patente",
    "charge_fiscale",
    "completude_declarative",
    "coherence_ca",
    "retenue_loyers",
    "deficits_reportables",
    "rapprochement_acomptes",
)

MENTION_NOTE: Final[str] = (
    "Dossier de synthèse consultatif de la mission — assemblage "
    "déterministe des analyses déjà restituées dans l'application "
    "(risques et exposition estimés par le cabinet, civisme déclaratif "
    "déduit des pièces collectées, complétude documentaire, points "
    "convenus et délais observés). Ce document ne constitue pas un avis "
    "fiscal : le fiscaliste apprécie et le client reste seul décideur "
    "des suites."
)


class ErreurDossierMission(Exception):
    """Echec métier du dossier de synthèse."""


class ErreurDossierIntrouvable(ErreurDossierMission):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonction pure d'assemblage ───────────────────────────────────────


def assembler_dossier(
    blocs: dict[str, Any], genere_le: str | None = None
) -> dict[str, Any]:
    """PUR — normalise les blocs et ajoute note + horodatage (testable).

    Chaque clé de :data:`BLOCS_DOSSIER` est toujours présente : bloc
    manquant ou non-dict → ``None`` (le frontend n'a jamais d'attribut
    absent à deviner). ``blocs_disponibles`` compte les blocs non nuls ;
    ``genere_le`` : horodatage ISO UTC de génération (fourni pour les
    tests, sinon maintenant) ; ``note`` : mention consultative française.
    """
    normalises: dict[str, Any] = {
        cle: (blocs.get(cle) if isinstance(blocs.get(cle), dict) else None)
        for cle in BLOCS_DOSSIER
    }
    return {
        **normalises,
        "blocs_disponibles": sum(
            1 for v in normalises.values() if v is not None
        ),
        "genere_le": genere_le
        or datetime.now(UTC).replace(microsecond=0).isoformat(),
        "note": MENTION_NOTE,
    }


# ── Constructeurs de blocs (chacun réutilise un module existant) ─────


def _bloc_identite(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Identité du dossier — mission + contribuable + cabinet (RLS).

    Seul bloc OBLIGATOIRE : mission hors tenant →
    :class:`ErreurDossierIntrouvable` (404). Le régime vient du profil
    JSON de la mission (même lecture que l'échéancier fiscal) ; les
    honoraires (str Decimal) restent ``None`` s'ils ne sont pas convenus.
    """
    from backend.plateforme.echeancier_fiscal import (
        _profil_mission,
        normaliser_regime,
    )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.id, m.exercice, m.statut, m.honoraires, "
                "m.profil, c.denomination AS contribuable_denomination, "
                "c.ncc FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurDossierIntrouvable(f"mission {mission_id} introuvable")
    cabinet = session.execute(
        text("SELECT denomination FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()
    profil = _profil_mission(row["profil"])
    honoraires = row["honoraires"]
    return {
        "mission_id": int(row["id"]),
        "exercice": int(row["exercice"]),
        "statut": str(row["statut"]),
        "cabinet": str(cabinet or ""),
        "contribuable": str(row["contribuable_denomination"] or ""),
        "ncc": str(row["ncc"]) if row["ncc"] else None,
        "regime": normaliser_regime(str(profil.get("regime") or "")),
        "honoraires": str(honoraires) if honoraires is not None else None,
    }


def _bloc_risques(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Synthèse des risques — réutilise le plan d'actions post-revue.

    :func:`backend.plateforme.plan_actions.analyse_mission` liste déjà
    les risques non clos du client avec exposition (str Decimal),
    priorité et exposition totale — aucun recalcul ici.
    """
    from backend.plateforme.plan_actions import analyse_mission

    a = analyse_mission(session, tenant_id, mission_id)
    return {
        "risques": [
            {
                "risque_id": p.get("risque_id"),
                "libelle": str(p.get("libelle_risque") or ""),
                "impot": str(p.get("impot") or ""),
                "exercice_origine": p.get("exercice_origine"),
                "priorite": str(p.get("priorite") or ""),
                "exposition": p.get("exposition"),
            }
            for p in a.get("plan") or []
        ],
        "exposition_totale": a["synthese"].get("exposition_totale"),
        "note": a.get("note"),
    }


def _bloc_civisme(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Taux de civisme fiscal — recopie la synthèse de l'analyse."""
    from backend.plateforme.civisme_fiscal import analyse_mission

    a = analyse_mission(session, tenant_id, mission_id)
    s = a["synthese"]
    return {
        "taux_civisme": s.get("taux_civisme"),
        "couvertes": s.get("couvertes"),
        "en_attente": s.get("en_attente"),
        "manquantes": s.get("manquantes"),
        "note": a.get("note"),
    }


def _bloc_completude(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Complétude data room — synthèse + pièces essentielles manquantes."""
    from backend.plateforme.completude_data_room import completude_data_room

    c = completude_data_room(session, tenant_id, mission_id)
    return {
        "regime": c.get("regime"),
        "synthese": c.get("synthese"),
        "manquantes": [
            {"code": a.get("code"), "libelle": a.get("libelle")}
            for a in c.get("attendus") or []
            if a.get("essentielle") and not a.get("presente")
        ],
        "note": c.get("note"),
    }


def _bloc_points_convenus(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Points convenus — statuts et retards déjà calculés par le module."""
    from backend.plateforme.points_convenus import lister_points_convenus

    p = lister_points_convenus(session, tenant_id, mission_id)
    return {
        "points": p.get("points") or [],
        "synthese": p.get("synthese"),
        "note": p.get("note"),
    }


def _bloc_compte_rendu(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any] | None:
    """Compte-rendu de restitution — None si aucun n'est consigné."""
    from backend.plateforme.compte_rendu import lire_compte_rendu

    return lire_compte_rendu(session, tenant_id, mission_id)


def _bloc_delais(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Délais / jalons de la mission — module delais_mission tel quel."""
    from backend.plateforme.delais_mission import delais_mission

    d = delais_mission(session, tenant_id, mission_id)
    return {
        "jalons": d.get("jalons") or [],
        "duree_totale_jours": d.get("duree_totale_jours"),
        "note": d.get("note"),
    }


def _bloc_rapprochement_tva(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement TVA — synthèse + écarts significatifs seulement.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.rapprochement_tva.rapprochement_tva_mission`
    (comme :func:`_bloc_risques`) : le détail des déclarations par
    période et des comptes de balance reste sur l'écran dédié.
    """
    from backend.plateforme.rapprochement_tva import (
        rapprochement_tva_mission,
    )

    r = rapprochement_tva_mission(session, tenant_id, mission_id)
    return {
        "synthese": r.get("synthese"),
        "seuil_signification": r.get("seuil_signification"),
        "ecarts_significatifs": [
            {
                "nature": e.get("nature"),
                "libelle": e.get("libelle"),
                "declare": e.get("declare"),
                "comptabilise": e.get("comptabilise"),
                "ecart": e.get("ecart"),
            }
            for e in r.get("ecarts") or []
            if e.get("significatif")
        ],
        "note": r.get("note"),
    }


def _bloc_controles_fiscaux(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Contrôles fiscaux — synthèse + échéances proches ou dépassées.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.controles_fiscaux.controles_mission` :
    seules les échéances de riposte à surveiller sont reprises, la
    chronologie complète reste sur l'écran dédié.
    """
    from backend.plateforme.controles_fiscaux import controles_mission

    c = controles_mission(session, tenant_id, mission_id)
    return {
        "synthese": c.get("synthese"),
        "echeances_a_surveiller": [
            {
                "libelle": e.get("libelle"),
                "date_evenement": e.get("date_evenement"),
                "echeance": (e.get("delai_riposte") or {}).get("echeance"),
                "statut": (e.get("echeance") or {}).get("statut"),
                "jours_restants": (e.get("echeance") or {}).get(
                    "jours_restants"
                ),
            }
            for e in c.get("evenements") or []
            if (e.get("echeance") or {}).get("statut")
            in ("proche", "depassee")
        ],
        "note": c.get("note"),
    }


def _bloc_materialite(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Matérialité — seuil retenu, synthèse et couverture globale.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.materialite.materialite_mission` : ni les
    propositions ni le détail des comptes ciblés (écran dédié).
    """
    from backend.plateforme.materialite import materialite_mission

    m = materialite_mission(session, tenant_id, mission_id)
    couverture = m.get("couverture") or {}
    return {
        "synthese": m.get("synthese"),
        "seuil_retenu": m.get("seuil_retenu"),
        "couverture": {
            "masse_totale": couverture.get("masse_totale"),
            "masse_ciblee": couverture.get("masse_ciblee"),
            "taux_global": couverture.get("taux_global"),
        },
        "note": m.get("note"),
    }


def _bloc_acomptes(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Acomptes IS — position de solde projetée et totaux versés.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.acomptes.vue_acomptes_mission` (comme
    :func:`_bloc_rapprochement_tva`) : ni le détail des versements ni
    les comptes de balance — l'écran dédié les restitue.
    """
    from backend.plateforme.acomptes import vue_acomptes_mission

    a = vue_acomptes_mission(session, tenant_id, mission_id)
    return {
        "synthese": a.get("synthese"),
        "position": a.get("position"),
        "totaux_verses": a.get("totaux_verses"),
        "is_du_estime": a.get("is_du_estime"),
        "note": a.get("note"),
    }


def _bloc_rapprochement_salaires(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement salaires — synthèse + écarts significatifs seulement.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.rapprochement_salaires.rapprochement_salaires_mission`
    (même pattern que :func:`_bloc_rapprochement_tva`) : le détail des
    déclarations par période et des comptes de balance reste sur
    l'écran dédié.
    """
    from backend.plateforme.rapprochement_salaires import (
        rapprochement_salaires_mission,
    )

    r = rapprochement_salaires_mission(session, tenant_id, mission_id)
    return {
        "synthese": r.get("synthese"),
        "seuil_signification": r.get("seuil_signification"),
        "ecarts_significatifs": [
            {
                "nature": e.get("nature"),
                "libelle": e.get("libelle"),
                "declare": e.get("declare"),
                "comptabilise": e.get("comptabilise"),
                "ecart": e.get("ecart"),
                "commentaire": e.get("commentaire"),
            }
            for e in r.get("ecarts") or []
            if e.get("significatif")
        ],
        "note": r.get("note"),
    }


def _bloc_patente(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Patente estimée — synthèse de l'estimation consultative.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.patente.vue_patente_mission` (même
    pattern que :func:`_bloc_acomptes`) : statut, estimation totale
    partielle (droit sur le chiffre d'affaires seul) et plancher —
    ni le détail des comptes 70x ni les références CGI, restitués
    par l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.patente import vue_patente_mission

    p = vue_patente_mission(session, tenant_id, mission_id)
    s = p.get("synthese") or {}
    return {
        "synthese": {
            "statut": s.get("statut"),
            "libelle_statut": s.get("libelle_statut"),
            "nb_comptes_ca": s.get("nb_comptes_ca"),
        },
        "estimation_totale_partielle": p.get(
            "estimation_totale_partielle"
        ),
        "plancher_applique": p.get("plancher_applique"),
        "note": p.get("note"),
    }


def _bloc_charge_fiscale(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Charge fiscale estimée — synthèse du panorama consultatif.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.charge_fiscale.charge_fiscale_mission`
    (même pattern que :func:`_bloc_patente`) : total de charge propre
    PARTIEL, composantes incluses / indisponibles et synthèse — ni le
    détail des composantes ni les références CGI, restitués par
    l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.charge_fiscale import charge_fiscale_mission

    c = charge_fiscale_mission(session, tenant_id, mission_id)
    return {
        "total_charge_propre_estimee": c.get(
            "total_charge_propre_estimee"
        ),
        "composantes_incluses_total": list(
            c.get("composantes_incluses_total") or []
        ),
        "composantes_indisponibles": list(
            c.get("composantes_indisponibles") or []
        ),
        "synthese": c.get("synthese"),
        "note": c.get("note"),
    }


def _bloc_completude_declarative(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Complétude déclarative — synthèse des périodes mensuelles échues.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    (même pattern que :func:`_bloc_charge_fiscale`) : statut global,
    nombre de périodes manquantes et, par impôt mensuel, statut /
    manquantes / taux de couverture — ni le détail des périodes ni les
    références CGI, restitués par l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.completude_declarative import (
        completude_declarative_mission,
    )

    c = completude_declarative_mission(session, tenant_id, mission_id)
    s = c.get("synthese") or {}
    return {
        "exercice": c.get("exercice"),
        "synthese": {
            "statut_global": s.get("statut_global"),
            "nb_manquantes_total": s.get("nb_manquantes_total"),
        },
        "impots": {
            cle: {
                "statut": (bloc or {}).get("statut"),
                "nb_manquantes": (bloc or {}).get("nb_manquantes"),
                "taux_couverture": (bloc or {}).get("taux_couverture"),
            }
            for cle, bloc in (c.get("impots") or {}).items()
        },
        "note": c.get("note"),
    }


def _bloc_coherence_ca(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Cohérence CA / TVA — croisement consultatif du chiffre d'affaires.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.coherence_ca.coherence_ca_mission` (même
    pattern que :func:`_bloc_patente`) : statut, CA comptable, CA
    reconstitué (approximation assumée au seul taux normal), écart et
    écart relatif — ni le détail des déclarations ni les références
    CGI, restitués par l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.coherence_ca import coherence_ca_mission

    c = coherence_ca_mission(session, tenant_id, mission_id)
    return {
        "statut": c.get("statut"),
        "ca_comptable": c.get("ca_comptable"),
        "ca_reconstitue": c.get("ca_reconstitue"),
        "ecart": c.get("ecart"),
        "ecart_relatif_pct": c.get("ecart_relatif_pct"),
        "approximation": c.get("approximation"),
        "note": c.get("note"),
    }


def _bloc_retenue_loyers(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Retenue sur loyers — synthèse de la vue consultative.

    Projection SYNTHÉTIQUE de
    :func:`backend.plateforme.retenue_loyers.vue_retenue_loyers_mission`
    (même pattern que :func:`_bloc_coherence_ca`) : statut, loyers
    bruts (comptes 622x), retenue théorique maximale indicative et
    non-calculabilité de la répartition par bailleur — ni le détail
    des comptes 622x ni les références, restitués par l'écran dédié.
    Aucun recalcul ici.
    """
    from backend.plateforme.retenue_loyers import (
        vue_retenue_loyers_mission,
    )

    r = vue_retenue_loyers_mission(session, tenant_id, mission_id)
    return {
        "statut": r.get("statut"),
        "loyers_bruts": r.get("loyers_bruts"),
        "taux_indicatif": r.get("taux_indicatif"),
        "retenue_theorique_max": r.get("retenue_theorique_max"),
        "repartition_calculable": (
            r.get("repartition_par_bailleur") or {}
        ).get("calculable"),
        "note": r.get("note"),
    }


def _bloc_deficits_reportables(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Déficits reportables — synthèse du suivi pluriannuel consultatif.

    Projection SYNTHÉTIQUE (tolérante) de
    :func:`backend.plateforme.deficits_reportables.vue_deficits_reportables_mission`
    (même pattern que :func:`_bloc_retenue_loyers`) : statut, nombre
    d'exercices suivis, déficits constatés, cumul indicatif final
    (approximation assumée) et non-calculabilité de l'imputation
    réelle — ni le tableau pluriannuel détaillé ni les références,
    restitués par l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.deficits_reportables import (
        vue_deficits_reportables_mission,
    )

    d = vue_deficits_reportables_mission(session, tenant_id, mission_id)
    s = d.get("synthese") or {}
    return {
        "statut": d.get("statut"),
        "nb_exercices": s.get("nb_exercices"),
        "nb_deficits_constates": s.get("nb_deficits_constates"),
        "cumul_indicatif_final": d.get("cumul_indicatif_final"),
        "approximation": d.get("approximation"),
        "imputation_reelle_calculable": (
            d.get("imputation_reelle") or {}
        ).get("calculable"),
        "note": d.get("note"),
    }


def _bloc_rapprochement_acomptes(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement acomptes / IS théorique — synthèse consultative.

    Projection SYNTHÉTIQUE (tolérante) de
    :func:`backend.plateforme.rapprochement_acomptes.vue_rapprochement_acomptes_mission`
    (même pattern que :func:`_bloc_deficits_reportables`) : statut, IS
    théorique repris, total des acomptes saisis, solde indicatif de
    liquidation (approximation assumée) et non-calculabilité du
    minimum de perception — ni le détail des versements ni les
    références, restitués par l'écran dédié. Aucun recalcul ici.
    """
    from backend.plateforme.rapprochement_acomptes import (
        vue_rapprochement_acomptes_mission,
    )

    r = vue_rapprochement_acomptes_mission(session, tenant_id, mission_id)
    s = r.get("synthese") or {}
    solde = r.get("solde_indicatif") or {}
    return {
        "statut": r.get("statut"),
        "is_theorique": r.get("is_theorique"),
        "total_acomptes_saisis": s.get("total_acomptes_saisis"),
        "nb_versements": s.get("nb_versements"),
        "solde_indicatif": solde.get("montant"),
        "solde_signe": solde.get("solde_signe"),
        "approximation": r.get("approximation"),
        "minimum_perception_calculable": (
            r.get("minimum_perception") or {}
        ).get("calculable"),
        "note": r.get("note"),
    }


#: Blocs facultatifs : (clé, constructeur) — chacun est TOLÉRANT.
_BLOCS_FACULTATIFS: Final[
    tuple[tuple[str, Callable[[Session, int, int], dict[str, Any] | None]], ...]
] = (
    ("risques", _bloc_risques),
    ("civisme", _bloc_civisme),
    ("completude", _bloc_completude),
    ("points_convenus", _bloc_points_convenus),
    ("compte_rendu", _bloc_compte_rendu),
    ("delais", _bloc_delais),
    ("rapprochement_tva", _bloc_rapprochement_tva),
    ("controles_fiscaux", _bloc_controles_fiscaux),
    ("materialite", _bloc_materialite),
    ("acomptes", _bloc_acomptes),
    ("rapprochement_salaires", _bloc_rapprochement_salaires),
    ("patente", _bloc_patente),
    ("charge_fiscale", _bloc_charge_fiscale),
    ("completude_declarative", _bloc_completude_declarative),
    ("coherence_ca", _bloc_coherence_ca),
    ("retenue_loyers", _bloc_retenue_loyers),
    ("deficits_reportables", _bloc_deficits_reportables),
    ("rapprochement_acomptes", _bloc_rapprochement_acomptes),
)


# ── Lecture mission (RLS) ────────────────────────────────────────────


def dossier_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Dossier de synthèse de la mission (LECTURE SEULE, RLS).

    Agrège les blocs existants sans dupliquer aucun calcul. Chaque bloc
    facultatif est tenté indépendamment (try/except) : un sous-module en
    échec ou vide donne un bloc ``None``, jamais bloquant. Seule une
    mission hors tenant lève :class:`ErreurDossierIntrouvable` (→ 404).
    Chaque constructeur ouvre son propre ``contexte_tenant`` : appels
    HORS de tout autre ``with``.
    """
    blocs: dict[str, Any] = {
        "identite": _bloc_identite(session, tenant_id, mission_id)
    }
    for cle, construire in _BLOCS_FACULTATIFS:
        # Tolérance par bloc : un sous-module en échec n'empêche jamais
        # la remise du dossier (pattern echeances_cabinet).
        try:
            blocs[cle] = construire(session, tenant_id, mission_id)
        except Exception:  # noqa: BLE001 — bloc annexe toléré
            blocs[cle] = None
    return assembler_dossier(blocs)
