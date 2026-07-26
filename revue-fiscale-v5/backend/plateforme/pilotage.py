"""Pilotage portefeuille — cockpit associé (lecture seule, sous RLS).

Agrège pour un tenant : exposition cumulée par contribuable, missions
en cours inactives, alertes de fiabilité des sources FEC et risques en
retard de traitement. Aucune écriture — tout passe par contexte_tenant.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeancier_fiscal import (
    STATUT_DEPASSEE,
    STATUT_IMMINENTE,
    prochaines_echeances,
)
from backend.plateforme.risques import calculer_score_risque

# Statuts de risque considérés comme exposition ouverte. « en_retard »
# n'existe pas dans le CHECK de la table risque mais est toléré ici par
# compatibilité si le schéma évolue.
STATUTS_RISQUE_OUVERTS: Final[tuple[str, ...]] = (
    "ouvert",
    "en_traitement",
    "en_retard",
)
# Statuts d'action dont l'échéance dépassée signale un retard réel.
_STATUTS_ACTION_SUIVIS: Final[tuple[str, ...]] = (
    "acceptee",
    "en_cours",
    "preuve_deposee",
)
JOURS_INACTIVITE_MISSION: Final[int] = 30
TOP_EXPOSITION: Final[int] = 10
TOP_RETARDS: Final[int] = 5
# Volet échéances déclaratives : horizon court (30 j) et plafond de
# lignes affichées — le compteur total reste exhaustif.
HORIZON_ECHEANCES_JOURS: Final[int] = 30
TOP_ECHEANCES: Final[int] = 15


def _decimal_str(valeur: Any) -> str:
    """Montant NUMERIC → chaîne stable (jamais de float)."""
    return str(valeur) if valeur is not None else "0"


def _exposition_par_client(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT c.id AS contribuable_id, c.denomination, "
            "SUM(COALESCE(r.montant_estime, 0) "
            "    + COALESCE(r.penalites_estimees, 0)) AS exposition, "
            "COUNT(*) AS nb_risques_ouverts "
            "FROM risque r "
            "JOIN contribuable c ON c.id = r.contribuable_id "
            "WHERE r.statut = ANY(:ouverts) "
            "GROUP BY c.id, c.denomination "
            "ORDER BY exposition DESC, nb_risques_ouverts DESC, c.id "
            "LIMIT :lim"
        ),
        {"ouverts": list(STATUTS_RISQUE_OUVERTS), "lim": TOP_EXPOSITION},
    ).mappings().all()
    if not rows:
        return []
    ids = [int(r["contribuable_id"]) for r in rows]

    # Données nécessaires au score déterministe (réutilise le calcul
    # officiel de risques.py — pas de duplication de barème).
    risques_rows = session.execute(
        text(
            "SELECT r.contribuable_id, r.statut, r.probabilite, "
            "r.montant_estime, r.penalites_estimees, r.derniere_revue, "
            "r.cree_le, r.exercice_origine "
            "FROM risque r WHERE r.contribuable_id = ANY(:ids)"
        ),
        {"ids": ids},
    ).mappings().all()
    retards_rows = session.execute(
        text(
            "SELECT r.contribuable_id, count(*) AS n "
            "FROM action_risque a JOIN risque r ON r.id = a.risque_id "
            "WHERE r.contribuable_id = ANY(:ids) "
            "AND a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
            "AND a.statut = ANY(:suivis) "
            "GROUP BY r.contribuable_id"
        ),
        {"ids": ids, "suivis": list(_STATUTS_ACTION_SUIVIS)},
    ).mappings().all()
    refus_rows = session.execute(
        text(
            "SELECT r.contribuable_id, count(*) AS n "
            "FROM action_risque a JOIN risque r ON r.id = a.risque_id "
            "WHERE r.contribuable_id = ANY(:ids) AND a.statut = 'refusee' "
            "GROUP BY r.contribuable_id"
        ),
        {"ids": ids},
    ).mappings().all()

    risques_par_client: dict[int, list[dict[str, Any]]] = {}
    for r in risques_rows:
        risques_par_client.setdefault(int(r["contribuable_id"]), []).append(
            dict(r)
        )
    retards = {int(r["contribuable_id"]): int(r["n"]) for r in retards_rows}
    refus = {int(r["contribuable_id"]): int(r["n"]) for r in refus_rows}

    resultat: list[dict[str, Any]] = []
    for row in rows:
        cid = int(row["contribuable_id"])
        score = calculer_score_risque(
            {
                "risques": risques_par_client.get(cid, []),
                "actions_en_retard": retards.get(cid, 0),
                "actions_refusees": refus.get(cid, 0),
            }
        )
        resultat.append(
            {
                "contribuable_id": cid,
                "denomination": str(row["denomination"]),
                "exposition_ouverte": _decimal_str(row["exposition"]),
                "nb_risques_ouverts": int(row["nb_risques_ouverts"]),
                "score": int(score["score"]),
                "niveau": str(score["niveau"]),
            }
        )
    return resultat


def _missions_a_cloturer(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT m.id AS mission_id, m.exercice, "
            "c.id AS contribuable_id, c.denomination, "
            "MAX(e.lancee_le) AS derniere_execution, "
            "EXTRACT(DAY FROM now() - MAX(e.lancee_le))::int "
            "  AS jours_inactivite "
            "FROM mission m "
            "JOIN contribuable c ON c.id = m.contribuable_id "
            "JOIN execution e ON e.mission_id = m.id "
            "WHERE m.statut = 'en_cours' "
            "GROUP BY m.id, m.exercice, c.id, c.denomination "
            "HAVING MAX(e.lancee_le) < now() - make_interval(days => :j) "
            "ORDER BY MAX(e.lancee_le) ASC"
        ),
        {"j": JOURS_INACTIVITE_MISSION},
    ).mappings().all()
    return [
        {
            "mission_id": int(r["mission_id"]),
            "contribuable_id": int(r["contribuable_id"]),
            "denomination": str(r["denomination"]),
            "exercice": int(r["exercice"]),
            "derniere_execution_le": r["derniere_execution"].isoformat()
            if r["derniere_execution"] is not None
            else None,
            "jours_inactivite": int(r["jours_inactivite"]),
        }
        for r in rows
    ]


def _alertes_source(session: Session) -> list[dict[str, Any]]:
    # Dernier jeu de contrôles par mission ; on ne remonte que ceux
    # contenant au moins un statut « alerte ».
    rows = session.execute(
        text(
            "SELECT d.mission_id, d.exercice, d.cree_le, d.controles, "
            "c.id AS contribuable_id, c.denomination "
            "FROM ( "
            "  SELECT DISTINCT ON (mission_id) "
            "  mission_id, exercice, cree_le, controles "
            "  FROM controle_source_fec "
            "  ORDER BY mission_id, cree_le DESC, id DESC "
            ") d "
            "JOIN mission m ON m.id = d.mission_id "
            "JOIN contribuable c ON c.id = m.contribuable_id "
            "ORDER BY d.cree_le DESC"
        )
    ).mappings().all()
    resultat: list[dict[str, Any]] = []
    for r in rows:
        controles = r["controles"] or []
        if not isinstance(controles, list):
            continue
        codes = [
            str(c.get("code") or "")
            for c in controles
            if isinstance(c, dict) and str(c.get("statut") or "") == "alerte"
        ]
        codes = [c for c in codes if c]
        if not codes:
            continue
        resultat.append(
            {
                "mission_id": int(r["mission_id"]),
                "contribuable_id": int(r["contribuable_id"]),
                "denomination": str(r["denomination"]),
                "exercice": int(r["exercice"]),
                "codes_alerte": codes,
                "controle_le": r["cree_le"].isoformat()
                if r["cree_le"] is not None
                else None,
            }
        )
    return resultat


def _risques_en_retard(session: Session) -> dict[str, Any]:
    # Risque « en retard » = risque encore ouvert dont au moins une
    # action suivie a dépassé son échéance.
    rows = session.execute(
        text(
            "SELECT r.id AS risque_id, r.libelle, r.montant_estime, "
            "c.id AS contribuable_id, c.denomination, "
            "MIN(a.echeance) AS echeance "
            "FROM risque r "
            "JOIN contribuable c ON c.id = r.contribuable_id "
            "JOIN action_risque a ON a.risque_id = r.id "
            "WHERE r.statut = ANY(:ouverts) "
            "AND a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
            "AND a.statut = ANY(:suivis) "
            "GROUP BY r.id, r.libelle, r.montant_estime, "
            "c.id, c.denomination "
            "ORDER BY COALESCE(r.montant_estime, 0) DESC, "
            "MIN(a.echeance) ASC"
        ),
        {
            "ouverts": list(STATUTS_RISQUE_OUVERTS),
            "suivis": list(_STATUTS_ACTION_SUIVIS),
        },
    ).mappings().all()
    top = [
        {
            "risque_id": int(r["risque_id"]),
            "contribuable_id": int(r["contribuable_id"]),
            "denomination": str(r["denomination"]),
            "libelle": str(r["libelle"]),
            "montant_estime": _decimal_str(r["montant_estime"]),
            "echeance": r["echeance"].isoformat()
            if r["echeance"] is not None
            else None,
        }
        for r in rows[:TOP_RETARDS]
    ]
    return {"total": len(rows), "top": top}


def _echeances_portefeuille(session: Session) -> dict[str, Any]:
    """Obligations déclaratives imminentes ou dépassées du portefeuille.

    Parcourt les contribuables du tenant (même périmètre RLS que les
    autres volets), projette leurs échéances indicatives sur 30 jours
    via ``prochaines_echeances`` et n'agrège que les statuts
    « imminente » et « depassee ». Régime vide ou inconnu → contribuable
    ignoré silencieusement (la fonction pure renvoie une liste vide).
    """
    rows = session.execute(
        text(
            "SELECT id, denomination, regime_fiscal, mois_cloture "
            "FROM contribuable ORDER BY id"
        )
    ).mappings().all()
    aujourd_hui = date.today()
    lignes: list[dict[str, Any]] = []
    for r in rows:
        mois_cloture = (
            int(r["mois_cloture"]) if r["mois_cloture"] is not None else None
        )
        for e in prochaines_echeances(
            r["regime_fiscal"],
            aujourd_hui,
            horizon_jours=HORIZON_ECHEANCES_JOURS,
            mois_cloture=mois_cloture,
        ):
            if e["statut"] not in (STATUT_IMMINENTE, STATUT_DEPASSEE):
                continue
            lignes.append(
                {
                    "contribuable_id": int(r["id"]),
                    "denomination": str(r["denomination"]),
                    "code": str(e["code"]),
                    "libelle": str(e["libelle"]),
                    "date_limite": str(e["date_limite"]),
                    "jours_restants": int(e["jours_restants"]),
                    "statut": str(e["statut"]),
                }
            )
    lignes.sort(
        key=lambda x: (x["date_limite"], x["denomination"], x["code"])
    )
    return {"total": len(lignes), "lignes": lignes[:TOP_ECHEANCES]}


def pilotage_portefeuille(
    session: Session, tenant_id: int
) -> dict[str, Any]:
    """Cockpit associé — cinq volets, lecture seule sous RLS."""
    with contexte_tenant(session, tenant_id):
        return {
            "exposition_par_client": _exposition_par_client(session),
            "missions_a_cloturer": _missions_a_cloturer(session),
            "alertes_source": _alertes_source(session),
            "risques_en_retard": _risques_en_retard(session),
            "echeances_portefeuille": _echeances_portefeuille(session),
        }
