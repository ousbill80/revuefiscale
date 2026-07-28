"""« Mon tableau de bord » — les priorités du jour du collaborateur.

POURQUOI : chaque collaborateur du cabinet veut ouvrir l'application et
voir d'un coup d'œil SES priorités : les missions dont il est
responsable (``mission.responsable_email``, migration 047), les points
convenus encore « à faire » de ces missions, et les échéances fiscales
des 30 prochains jours de ses missions en cours — sans parcourir les
vues cabinet qui mélangent tous les responsables.

DOCTRINE : déterministe et strictement CONSULTATIF — aucune écriture,
aucun LLM. Fonctions pures + lecture seule sous RLS via
``contexte_tenant``. RÉUTILISE les briques existantes plutôt que de les
copier : :func:`backend.plateforme.points_convenus.point_en_retard`,
:func:`backend.plateforme.points_convenus_cabinet.anciennete_jours`,
et le calendrier COURANT d'``echeances_cabinet``
(:func:`filtrer_fenetre`, :func:`fusionner_echeances`, échéanciers des
exercices année courante et précédente).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeances_cabinet import (
    PLAFOND_MISSIONS,
    SEUIL_SEMAINE_JOURS,
    filtrer_fenetre,
    fusionner_echeances,
)
from backend.plateforme.points_convenus_cabinet import (
    PLAFOND_ITEMS,
    anciennete_jours,
    plafonner_points,
    trier_points,
)

MENTION_NOTE: Final[str] = (
    "Vue consultative — vos missions non clôturées, vos points convenus "
    "encore « à faire » et les échéances fiscales indicatives des 30 "
    "prochains jours de vos missions en cours. Vérifier le calendrier "
    "officiel de la DGI ; chaque action se décide dans la mission "
    "concernée : l'humain décide."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def trier_missions(missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — « en_cours » d'abord, puis exercice décroissant, puis client.

    Le travail actif remonte en tête ; à statut égal, l'exercice le plus
    récent d'abord, puis l'ordre alphabétique des clients (id croissant
    en dernier ressort — stable et lisible).
    """
    def _cle(m: dict[str, Any]) -> tuple:
        return (
            str(m.get("statut") or "") != "en_cours",
            -int(m.get("exercice") or 0),
            str(m.get("client") or ""),
            int(m.get("mission_id") or 0),
        )

    return sorted(missions, key=_cle)


def synthese_mon_tableau(
    missions: list[dict[str, Any]],
    points: list[dict[str, Any]],
    echeances: list[dict[str, Any]],
) -> dict[str, int]:
    """PUR — compteurs du tableau personnel.

    ``{missions, points_a_faire, points_en_retard, echeances_30j,
    echeances_semaine}`` — « semaine » au sens du seuil partagé avec le
    tableau cabinet (:data:`SEUIL_SEMAINE_JOURS`, ≤ 7 jours).
    """
    return {
        "missions": len(missions),
        "points_a_faire": len(points),
        "points_en_retard": sum(
            1 for p in points if bool(p.get("en_retard"))
        ),
        "echeances_30j": len(echeances),
        "echeances_semaine": sum(
            1
            for e in echeances
            if int(e.get("jours_restants") or 0) <= SEUIL_SEMAINE_JOURS
        ),
    }


# ── Lecture (RLS) ────────────────────────────────────────────────────


def mon_tableau(
    session: Session,
    tenant_id: int,
    email: str,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Tableau personnel du collaborateur — lecture seule, RLS.

    Missions NON clôturées du tenant dont ``responsable_email`` est
    l'email (comparaison insensible à la casse), plafonnées à
    :data:`PLAFOND_MISSIONS` ; points « a_faire » de CES missions
    (retard via :func:`point_en_retard`) ; échéances des 30 prochains
    jours de CES missions « en_cours » — même logique de calendrier
    COURANT qu'``echeances_cabinet`` (exercices année courante et
    précédente, l'exercice revu ne borne pas les dates). Une mission en
    erreur d'échéancier est simplement omise (jamais bloquant). Se
    construit toujours (aucune mission affectée → listes vides).
    """
    from backend.plateforme.echeancier_fiscal import (
        _profil_mission,
        _releve_de_la_dge,
        construire_echeancier,
        normaliser_regime,
    )
    from backend.plateforme.missions import STATUT_CLOTUREE, STATUT_EN_COURS
    from backend.plateforme.points_convenus import (
        STATUT_A_FAIRE,
        point_en_retard,
    )

    jour = aujourd_hui or date.today()
    email_norme = str(email or "").strip().lower()

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, m.statut, "
                "m.profil, c.denomination AS client, c.centre_impots "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut <> :cl "
                "AND lower(coalesce(m.responsable_email, '')) = :e "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"cl": STATUT_CLOTUREE, "e": email_norme, "lim": PLAFOND_MISSIONS},
        ).mappings().all()

        ids = [int(r["mission_id"]) for r in rows]
        points_rows: list[dict[str, Any]] = []
        if ids:
            points_rows = [
                dict(p)
                for p in session.execute(
                    text(
                        "SELECT p.id AS point_id, p.libelle, p.date_cible, "
                        "p.cree_le, p.mission_id "
                        "FROM point_convenu p "
                        "WHERE p.statut = :sp AND p.mission_id IN :ids "
                        "ORDER BY p.cree_le, p.id "
                        "LIMIT :lim"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"sp": STATUT_A_FAIRE, "ids": ids, "lim": PLAFOND_ITEMS},
                ).mappings().all()
            ]

    par_id = {int(r["mission_id"]): r for r in rows}

    missions = trier_missions(
        [
            {
                "mission_id": int(r["mission_id"]),
                "client": str(r["client"] or ""),
                "exercice": int(r["exercice"]),
                "statut": str(r["statut"] or ""),
            }
            for r in rows
        ]
    )

    points: list[dict[str, Any]] = []
    for p in points_rows:
        m = par_id.get(int(p["mission_id"]))
        if m is None:  # défensif — le point vient de ces missions
            continue
        cible = p["date_cible"]
        points.append(
            {
                "mission_id": int(p["mission_id"]),
                "client": str(m["client"] or ""),
                "exercice": int(m["exercice"]),
                "point_id": int(p["point_id"]),
                "libelle": str(p["libelle"] or ""),
                "date_cible": (
                    cible.isoformat() if isinstance(cible, date) else None
                ),
                "en_retard": point_en_retard(STATUT_A_FAIRE, cible, jour),
                "anciennete_jours": anciennete_jours(p["cree_le"], jour),
                "cree_le": (
                    p["cree_le"].isoformat()
                    if isinstance(p["cree_le"], datetime)
                    else None
                ),
            }
        )
    points = plafonner_points(trier_points(points))

    par_mission: list[dict[str, Any]] = []
    for r in rows:
        if str(r["statut"] or "") != STATUT_EN_COURS:
            continue
        # Tolérance d'erreur par mission : un échéancier qui échoue
        # n'empêche pas le reste du tableau personnel.
        try:
            profil = _profil_mission(r["profil"])
            regime = (
                normaliser_regime(str(profil.get("regime") or "")) or "reel"
            )
            dge = _releve_de_la_dge(r["centre_impots"])
            echeancier = [
                e
                for annee in (jour.year - 1, jour.year)
                for e in construire_echeancier(annee, regime, dge=dge)
            ]
            par_mission.append(
                {
                    "client": str(r["client"] or ""),
                    "mission_id": int(r["mission_id"]),
                    "exercice": int(r["exercice"]),
                    "echeances": filtrer_fenetre(echeancier, jour),
                }
            )
        except Exception:
            continue
    echeances = fusionner_echeances(par_mission)

    return {
        "aujourd_hui": jour.isoformat(),
        "email": email_norme,
        "missions": missions,
        "points": points,
        "echeances": echeances,
        "synthese": synthese_mon_tableau(missions, points, echeances),
        "note": MENTION_NOTE,
    }
