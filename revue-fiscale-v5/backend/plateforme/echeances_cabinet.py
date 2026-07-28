"""Échéances fiscales à venir au niveau cabinet — vue transverse.

POURQUOI : sur le tableau de bord cabinet, le fiscaliste veut voir d'un
coup d'œil les dates limites des 30 prochains jours pour TOUS ses
clients en mission — et anticiper (préparer les déclarations, relancer
les pièces) sans ouvrir chaque mission. Ce bloc applique le régime de
chaque mission « en_cours » au calendrier COURANT
(:func:`backend.plateforme.echeancier_fiscal.construire_echeancier`,
pur, exercices année courante et précédente) et ne garde que la
fenêtre [aujourd'hui, aujourd'hui + 30 jours].

LIMITE ASSUMÉE : vue strictement CONSULTATIVE — référentiel de dates
indicatif (vérifier le calendrier officiel DGI), aucune écriture,
aucun LLM. Fonctions pures + lecture seule sous RLS via
``contexte_tenant``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeancier_fiscal import (
    _profil_mission,
    _releve_de_la_dge,
    construire_echeancier,
    normaliser_regime,
)

# ── Constantes ───────────────────────────────────────────────────────

# Fenêtre d'anticipation : les 30 prochains jours (bornes incluses).
FENETRE_JOURS: Final[int] = 30

# En deçà de 7 jours, l'échéance est « cette semaine » (badge rouge).
SEUIL_SEMAINE_JOURS: Final[int] = 7

# Plafond d'items restitués — vue de pilotage, pas un export.
PLAFOND_ITEMS: Final[int] = 100

# Plafond de missions examinées (chaque mission déclenche la
# construction d'un échéancier complet : coût borné et prévisible).
PLAFOND_MISSIONS: Final[int] = 50

MENTION_NOTE: Final[str] = (
    "Vue consultative — dates limites indicatives des 30 prochains "
    "jours pour les clients en mission, d'après l'échéancier fiscal du "
    "régime de chaque mission appliqué au calendrier courant (pratique "
    "déclarative usuelle CI). Vérifier le calendrier officiel de la "
    "DGI ; le dépôt reste une décision du cabinet et de son client."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def filtrer_fenetre(
    echeances: list[dict[str, Any]],
    aujourd_hui: date,
    fenetre_jours: int = FENETRE_JOURS,
) -> list[dict[str, Any]]:
    """PUR — échéances dont la date limite tombe dans la fenêtre.

    Fenêtre [``aujourd_hui``, ``aujourd_hui + fenetre_jours``], bornes
    incluses. Chaque item retenu est enrichi de ``jours_restants``
    (int ≥ 0). Date illisible → item ignoré (défensif, jamais bloquant).
    """
    fin = aujourd_hui + timedelta(days=max(0, int(fenetre_jours)))
    retenues: list[dict[str, Any]] = []
    for e in echeances:
        try:
            d = date.fromisoformat(str(e.get("date_limite") or ""))
        except ValueError:
            continue
        if aujourd_hui <= d <= fin:
            retenues.append({**e, "jours_restants": (d - aujourd_hui).days})
    return retenues


def fusionner_echeances(
    par_mission: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — fusion des échéances de plusieurs missions en une liste plate.

    Chaque entrée de ``par_mission`` : ``{client, mission_id, exercice,
    echeances}`` (échéances déjà filtrées sur la fenêtre, avec
    ``jours_restants``). Résultat : items homogènes ``{client,
    mission_id, exercice, impot, obligation, periode, date_limite,
    jours_restants}``, triés (:func:`trier_echeances`) et plafonnés à
    :data:`PLAFOND_ITEMS` (les plus proches d'abord — le plafond ne
    coupe donc que les plus lointaines).
    """
    items: list[dict[str, Any]] = []
    for m in par_mission:
        for e in m.get("echeances") or []:
            items.append(
                {
                    "client": str(m.get("client") or ""),
                    "mission_id": int(m.get("mission_id") or 0),
                    "exercice": int(m.get("exercice") or 0),
                    "impot": str(e.get("impot") or ""),
                    "obligation": str(e.get("obligation") or ""),
                    "periode": str(e.get("periode") or ""),
                    "date_limite": str(e.get("date_limite") or ""),
                    "jours_restants": int(e.get("jours_restants") or 0),
                }
            )
    return trier_echeances(items)[:PLAFOND_ITEMS]


def trier_echeances(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — par date limite croissante, puis client, puis impôt.

    La plus urgente en tête ; à égalité de date, ordre alphabétique des
    clients puis des impôts — stable et lisible.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        return (
            str(i.get("date_limite") or ""),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
            str(i.get("impot") or ""),
            str(i.get("obligation") or ""),
        )

    return sorted(items, key=_cle)


def synthese_echeances(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs : total, cette semaine (≤ 7 jours), clients."""
    cette_semaine = sum(
        1
        for i in items
        if int(i.get("jours_restants") or 0) <= SEUIL_SEMAINE_JOURS
    )
    clients = {str(i.get("client") or "") for i in items}
    return {
        "total": len(items),
        "cette_semaine": cette_semaine,
        "clients": len(clients),
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def echeances_cabinet(
    session: Session, tenant_id: int, aujourd_hui: date | None = None
) -> dict[str, Any]:
    """Échéances des 30 prochains jours, missions en cours (lecture, RLS).

    Missions au statut « en_cours » du tenant (plafonnées à
    :data:`PLAFOND_MISSIONS`) : pour chacune, le régime (profil JSON de
    la mission, DGE via ``contribuable.centre_impots``) est appliqué au
    CALENDRIER COURANT — échéanciers des exercices ``aujourd_hui.year``
    et ``aujourd_hui.year - 1`` (dont les reliquats — TVA de décembre,
    états financiers — tombent l'année suivante) — puis filtré sur la
    fenêtre de :data:`FENETRE_JOURS` jours et fusionné. L'exercice revu
    par la mission ne borne PAS les échéances : le client vit dans le
    calendrier d'aujourd'hui. Une mission en erreur est simplement omise
    (échec silencieux, jamais bloquant). Se construit toujours (tenant
    sans mission en cours → liste vide).
    """
    from backend.plateforme.missions import STATUT_EN_COURS

    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, m.profil, "
                "c.denomination AS client, c.centre_impots "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut = :s "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"s": STATUT_EN_COURS, "lim": PLAFOND_MISSIONS},
        ).mappings().all()

    par_mission: list[dict[str, Any]] = []
    for r in rows:
        # Tolérance d'erreur par mission : un échéancier qui échoue
        # n'empêche pas le reste du tableau de bord.
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

    items = fusionner_echeances(par_mission)
    return {
        "aujourd_hui": jour.isoformat(),
        "items": items,
        "synthese": synthese_echeances(items),
        "note": MENTION_NOTE,
    }
