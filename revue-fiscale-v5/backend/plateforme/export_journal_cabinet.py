"""Export téléchargeable du journal d'activité du cabinet — texte + CSV.

POURQUOI : la traçabilité professionnelle (contrôle interne,
supervision de l'expert-comptable) se documente avec un support
diffusable — l'admin veut EMPORTER le journal d'activité (imprimé ou
archivé dans le dossier de contrôle interne), pas seulement le
consulter à l'écran. Ce module REND les entrées DÉJÀ serialisées par
:func:`backend.plateforme.journal_cabinet.journal_cabinet` en deux
formats : texte français lisible (revue de supervision) et CSV
point-virgule (tri sous Excel FR).

Aucun recalcul : fonctions PURES de mise en forme, mêmes données que
GET /cabinet/journal — assemblage déterministe et CONSULTATIF (aucun
LLM, aucun email), note consultative reprise en pied de document.
Pattern : :mod:`backend.plateforme.export_alertes` et
:mod:`backend.plateforme.export_calendrier`.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Final

from sqlalchemy.orm import Session

from backend.plateforme.journal_cabinet import (
    MENTION_NOTE,
    TAILLE_MAX,
    journal_cabinet,
)

#: Plafond d'entrées exportées — un export de traçabilité raisonnable,
#: pas un dump de base : au-delà, l'admin resserre ses filtres.
PLAFOND_EXPORT: Final[int] = 500

#: Colonnes du CSV — ordre stable, tri naturel sous Excel (horodatage
#: ISO en première colonne pour un tri chronologique fiable).
COLONNES_CSV: Final[tuple[str, ...]] = (
    "horodatage", "date", "acteur", "action", "libelle", "mission",
    "details",
)


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    parties = brut.split("-")
    if len(parties) != 3 or not all(parties):
        return ""
    a, m, j = parties
    return f"{j}/{m}/{a}"


def _date_heure_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA HH:MM » depuis un horodatage ISO — tolérant.

    Même règle d'affichage que le frontend (JournalCabinetVue.tsx,
    fonction ``dateHeureFr``) : ce qui est lu dans l'export est ce qui
    est affiché à l'écran. Horodatage illisible → restitué brut.
    """
    brut = str(iso or "").strip()
    date_part, _, time_part = brut.partition("T")
    jour = _date_fr(date_part)
    if not jour:
        return brut
    heure = time_part[:5] if time_part else ""
    return f"{jour} {heure}" if heure else jour


def _details_texte(details: Any) -> str:
    """Détails condensés « clé : valeur · clé : valeur » — tolérant."""
    if not isinstance(details, dict):
        return ""
    return " · ".join(
        f"{cle} : {'—' if valeur is None else valeur}"
        for cle, valeur in details.items()
    )


def rendre_journal_texte(
    corps: dict[str, Any], aujourd_hui: str | None = None
) -> str:
    """PUR — journal d'activité en texte français lisible (supervision).

    En-tête cabinet + date d'édition, filtres appliqués rappelés,
    entrées datées JJ/MM/AAAA HH:MM avec acteur, libellé français de
    l'action, mission et détails ; mention du plafond si le total
    dépasse les entrées exportées ; note consultative en pied —
    l'humain décide, le document DÉCRIT. Tolérant : un corps vide ou
    partiel produit un document valide.
    """
    entrees = list(corps.get("entrees") or [])
    filtres = dict(corps.get("filtres") or {})
    total = int(corps.get("total") or len(entrees))
    date_fr = _date_fr(aujourd_hui)

    lignes: list[str] = [
        "JOURNAL D'ACTIVITÉ DU CABINET",
        "",
    ]
    if date_fr:
        lignes.append(f"Date d'édition : {date_fr}")
    lignes.append(
        f"Entrées exportées : {len(entrees)} (total : {total})"
    )
    if total > len(entrees):
        lignes.append(
            "Export plafonné aux entrées les plus récentes — "
            "resserrer les filtres pour un extrait plus ciblé."
        )
    action = str(filtres.get("action") or "")
    acteur = str(filtres.get("acteur") or "")
    if action:
        lignes.append(f"Filtre action : {action}")
    if acteur:
        lignes.append(f"Filtre acteur : {acteur}")
    lignes.append("")

    # ── Entrées, du plus récent au plus ancien (ordre du corps) ───
    if not entrees:
        lignes += ["Aucune entrée pour ces critères.", ""]
    for e in entrees:
        partie = f"  - {_date_heure_fr(e.get('horodatage'))}"
        acteur_e = str(e.get("acteur") or "")
        if acteur_e:
            partie += f" — {acteur_e}"
        partie += f" — {str(e.get('libelle_action') or '')}"
        mission = e.get("mission_id")
        if mission is not None:
            partie += f" (mission n°{mission})"
        details = _details_texte(e.get("details"))
        if details:
            partie += f" — {details}"
        lignes.append(partie)
    if entrees:
        lignes.append("")

    # ── Note consultative en pied — l'humain décide ───────────────
    note = str(corps.get("note") or "")
    if note:
        lignes += ["Note : " + note]
    return "\n".join(lignes).rstrip() + "\n"


def rendre_journal_csv(corps: dict[str, Any]) -> str:
    """PUR — journal d'activité en CSV point-virgule pour Excel FR.

    BOM UTF-8 en tête (encodage reconnu par Excel), délimiteur « ; »,
    échappement délégué au module :mod:`csv` de la stdlib — jamais de
    concaténation manuelle. Colonnes stables :data:`COLONNES_CSV` —
    horodatage ISO en première colonne (tri chronologique fiable),
    date française lisible en seconde, toutes valeurs en ``str``.
    """
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for e in list(corps.get("entrees") or []):
        mission = e.get("mission_id")
        ecrivain.writerow([
            str(e.get("horodatage") or ""),
            _date_heure_fr(e.get("horodatage")),
            str(e.get("acteur") or ""),
            str(e.get("action") or ""),
            str(e.get("libelle_action") or ""),
            "" if mission is None else str(mission),
            _details_texte(e.get("details")),
        ])
    return "\ufeff" + tampon.getvalue()


# ── Lecture cabinet pour export (RLS, via journal_cabinet) ──────────


def journal_pour_export(
    session: Session,
    tenant_id: int,
    action: str | None = None,
    acteur: str | None = None,
    plafond: int = PLAFOND_EXPORT,
) -> dict[str, Any]:
    """Entrées du journal pour l'export — MÊME lecture que la vue.

    Réutilise :func:`journal_cabinet` page par page (AUCUNE requête
    divergente avec GET /cabinet/journal, mêmes filtres, même RLS)
    jusqu'au plafond ou à l'épuisement — du plus récent au plus
    ancien. Corps au même contrat : ``total``, ``entrees``,
    ``filtres``, ``note``.
    """
    borne = max(1, min(int(plafond), PLAFOND_EXPORT))
    entrees: list[dict[str, Any]] = []
    total = 0
    page = 1
    while len(entrees) < borne:
        vue = journal_cabinet(
            session,
            tenant_id,
            page=page,
            taille=TAILLE_MAX,
            action=action,
            acteur=acteur,
        )
        total = int(vue.get("total") or 0)
        lot = list(vue.get("entrees") or [])
        if not lot:
            break
        entrees.extend(lot[: borne - len(entrees)])
        if page * TAILLE_MAX >= total:
            break
        page += 1
    return {
        "total": total,
        "entrees": entrees,
        "filtres": {"action": action or None, "acteur": acteur or None},
        "note": MENTION_NOTE,
    }
