"""Export téléchargeable de la fiche client — texte français.

POURQUOI : avant un rendez-vous client, le fiscaliste veut EMPORTER
la fiche client consolidée (imprimée ou relue hors ligne), pas
seulement la consulter à l'écran. Ce module REND le corps DÉJÀ
assemblé par :func:`backend.plateforme.fiche_client.fiche_client` en
texte français lisible — document de PRÉPARATION de l'entretien.

Aucun recalcul : fonction PURE de mise en forme, mêmes données que
GET /contribuables/{id}/fiche — assemblage déterministe et
CONSULTATIF (aucun LLM, aucun email), formulations douces jamais
accusatoires, note consultative en pied de document. Pattern texte :
:mod:`backend.plateforme.export_calendrier`.
"""
from __future__ import annotations

from typing import Any, Final

#: Libellés français des statuts de mission — MÊME mapping que le
#: frontend (statuts.ts, constante LIBELLES) : les intitulés lus en
#: rendez-vous sont ceux affichés à l'écran.
LIBELLES_STATUT_MISSION: Final[dict[str, str]] = {
    "cadrage": "Cadrage",
    "en_cours": "En cours",
    "cloturee": "Clôturée",
}

#: Libellés français des formes de contribuable.
LIBELLES_FORME: Final[dict[str, str]] = {
    "pm": "Personne morale",
    "pp": "Personne physique",
}

#: Libellés français des gravités du centre d'alertes — même mapping
#: que :mod:`backend.plateforme.export_alertes`.
LIBELLES_GRAVITE: Final[dict[str, str]] = {
    "critique": "Critique",
    "vigilance": "Vigilance",
    "info": "Information",
}

#: Sens de variation en toutes lettres — descriptif, jamais un
#: jugement : une variation s'explique, elle ne se reproche pas.
LIBELLES_SENS: Final[dict[str, str]] = {
    "hausse": "en hausse",
    "baisse": "en baisse",
    "stable": "stable",
}

#: Formulation DOUCE d'une date cible déjà passée — constat de
#: calendrier, jamais un reproche (doctrine consultative du produit).
MENTION_DEPASSEE: Final[str] = "date passée — à reprogrammer si besoin"

#: Mention DOUCE d'une évolution non restituable ce jour.
MENTION_EVOLUTION_INDISPONIBLE: Final[str] = (
    "Évolution de la charge fiscale non disponible pour ce client à "
    "ce jour — les autres sections de la fiche restent présentées."
)

#: Note consultative finale — ferme toujours le document.
NOTE_EXPORT_FICHE: Final[str] = (
    "Document préparatoire de rendez-vous client : il reprend, sans "
    "les recalculer, les éléments déjà consolidés de la fiche client. "
    "Chaque point s'apprécie en entretien — l'expert analyse et "
    "décide des suites avec le client."
)


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    parties = brut.split("-")
    if len(parties) != 3 or not all(parties):
        return ""
    a, m, j = parties
    return f"{j}/{m}/{a}"


def _pct_fr(pct: object) -> str:
    """Pourcentage à VIRGULE française depuis le contrat machine.

    Le backend restitue « 12.5 » (point décimal, contrat machine) —
    le document français affiche « 12,5 % » ; signe « - » retiré (le
    sens en toutes lettres porte déjà la direction).
    """
    brut = str(pct).strip().lstrip("+-")
    return brut.replace(".", ",") + " %"


def _ligne_variation(v: dict[str, Any]) -> str | None:
    """PUR — une ligne de variation de charge propre, ou ``None``.

    Sens en toutes lettres, pourcentage à virgule française — sans
    pourcentage chiffrable (base nulle), le sens seul est restitué.
    Variation illisible → ``None`` (défensif, jamais bloquant).
    """
    total = v.get("total")
    if not isinstance(total, dict):
        return None
    sens = str(total.get("sens") or "")
    libelle_sens = LIBELLES_SENS.get(sens)
    if libelle_sens is None:
        return None
    partie = (
        f"  - De l'exercice {v.get('exercice_precedent')} à "
        f"l'exercice {v.get('exercice')} : charge fiscale propre "
        f"estimée {libelle_sens}"
    )
    pct = total.get("variation_relative_pct")
    if pct is not None and sens != "stable":
        partie += f" de {_pct_fr(pct)}"
    return partie


def rendre_fiche_texte(fiche: dict[str, Any]) -> str:
    """PUR — fiche client en texte français lisible (rendez-vous).

    En-tête (dénomination, forme, date d'édition JJ/MM/AAAA), missions
    par exercice décroissant avec statut français, points convenus
    ouverts (mention douce « date passée » le cas échéant), signaux du
    centre d'alertes (gravités françaises), évolution de la charge
    fiscale (variations avec pourcentage à virgule française et sens
    en toutes lettres — mention douce si indisponible), volets en
    échec signalés, note consultative en pied. Tolérant : une fiche
    vide ou partielle produit un document valide.
    """
    denomination = str(fiche.get("denomination") or "")
    forme = str(fiche.get("forme") or "")
    date_fr = _date_fr(fiche.get("aujourd_hui"))

    lignes: list[str] = [
        "FICHE CLIENT — " + denomination if denomination
        else "FICHE CLIENT",
        "",
    ]
    if forme:
        lignes.append(
            f"Forme : {LIBELLES_FORME.get(forme, forme)}"
        )
    if date_fr:
        lignes.append(f"Date d'édition : {date_fr}")
    lignes.append("")

    # ── Missions par exercice (décroissant, ordre de la fiche) ────
    missions = list(fiche.get("missions") or [])
    lignes.append(f"── Missions par exercice ({len(missions)}) " + "─" * 20)
    if not missions:
        lignes.append("  Aucune mission pour ce client.")
    for m in missions:
        statut = str(m.get("statut") or "")
        partie = f"  - Exercice {m.get('exercice')}"
        partie += f" — mission #{m.get('mission_id')}"
        if statut:
            partie += (
                f" — {LIBELLES_STATUT_MISSION.get(statut, statut)}"
            )
        lignes.append(partie)
    lignes.append("")

    # ── Points convenus encore ouverts ────────────────────────────
    points = list(fiche.get("points_ouverts") or [])
    lignes.append(
        f"── Points convenus encore ouverts ({len(points)}) " + "─" * 20
    )
    if not points:
        lignes.append(
            "  Aucun point convenu en attente pour ce client."
        )
    for p in points:
        partie = f"  - {str(p.get('libelle') or '')}"
        exercice = p.get("exercice")
        if exercice:
            partie += f" (exercice {exercice})"
        cible = _date_fr(p.get("date_cible"))
        if cible:
            partie += f" — date cible {cible}"
            if bool(p.get("depassee")):
                partie += f" ({MENTION_DEPASSEE})"
        else:
            partie += " — sans date cible"
        lignes.append(partie)
    lignes.append("")

    # ── Signaux du centre d'alertes ───────────────────────────────
    alertes = list(fiche.get("alertes") or [])
    lignes.append(
        f"── Signaux du centre d'alertes ({len(alertes)}) " + "─" * 20
    )
    if not alertes:
        lignes.append(
            "  Aucun signal du centre d'alertes ne concerne ce client."
        )
    for a in alertes:
        gravite = str(a.get("gravite") or "")
        partie = "  - "
        if gravite:
            partie += f"[{LIBELLES_GRAVITE.get(gravite, gravite)}] "
        partie += str(a.get("libelle") or "")
        echeance = _date_fr(a.get("echeance"))
        if echeance:
            partie += f" (échéance {echeance})"
        lignes.append(partie)
    lignes.append("")

    # ── Évolution de la charge fiscale estimée ────────────────────
    lignes.append(
        "── Évolution de la charge fiscale estimée " + "─" * 20
    )
    evolution = fiche.get("evolution_charge_fiscale")
    variations = (
        list(evolution.get("variations") or [])
        if isinstance(evolution, dict) and bool(evolution.get("disponible"))
        else []
    )
    rendues = [
        ligne
        for ligne in (_ligne_variation(v) for v in variations)
        if ligne is not None
    ]
    if rendues:
        lignes += rendues
        lignes.append(
            "  Chaque variation s'explique (activité, taux, assiettes, "
            "exonérations) — vue indicative, les liasses font foi."
        )
    else:
        lignes.append("  " + MENTION_EVOLUTION_INDISPONIBLE)
    lignes.append("")

    # ── Volets momentanément indisponibles ────────────────────────
    volets = list(fiche.get("volets_en_echec") or [])
    if volets:
        lignes += [
            "Volets momentanément indisponibles : "
            + ", ".join(str(v) for v in volets)
            + " — le reste de la fiche reste présenté.",
            "",
        ]

    # ── Note consultative en pied ─────────────────────────────────
    note = str(fiche.get("note") or "")
    if note:
        lignes.append("Note : " + note)
    lignes.append("Note : " + NOTE_EXPORT_FICHE)
    return "\n".join(lignes).rstrip() + "\n"
