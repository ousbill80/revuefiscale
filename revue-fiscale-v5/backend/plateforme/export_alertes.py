"""Export téléchargeable du centre d'alertes cabinet — texte + CSV.

POURQUOI : la réunion hebdomadaire du cabinet se prépare avec un
support diffusable en interne — l'associé veut EMPORTER le centre
d'alertes (imprimé ou partagé sur le réseau interne), pas seulement le
consulter à l'écran. Ce module REND le corps DÉJÀ assemblé par
:func:`backend.plateforme.centre_alertes.centre_alertes_cabinet` en
deux formats : texte français lisible (réunion) et CSV point-virgule
(tri sous Excel FR).

Aucun recalcul : fonctions PURES de mise en forme, mêmes données que
GET /cabinet/alertes — assemblage déterministe et CONSULTATIF (aucun
LLM, aucun email), note consultative reprise en pied de document.
Pattern texte : :mod:`backend.plateforme.ordre_du_jour`.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Final

from backend.plateforme.centre_alertes import GRAVITES

#: Libellés français des types d'alertes — MÊME mapping que le
#: frontend (CentreAlertesVue.tsx, constante LIBELLES_TYPE) : les
#: intitulés lus en réunion sont ceux affichés à l'écran.
LIBELLES_TYPE: Final[dict[str, str]] = {
    "point_convenu": "Point convenu",
    "echeance_fiscale": "Échéance fiscale",
    "budget_temps": "Budget temps",
    "delai_lpf": "Délai LPF",
    "completude_declarative": "Complétude déclarative",
    "coherence_ca": "Cohérence du chiffre d'affaires",
    "deficits_reportables": "Déficits reportables",
    "rapprochement_acomptes": "Rapprochement des acomptes IS",
    "qualite_balance": "Qualité de balance",
    "evolution_charge_fiscale": "Évolution de la charge fiscale",
}

#: Titres français des groupes de gravité, dans l'ordre de lecture.
LIBELLES_GRAVITE: Final[dict[str, str]] = {
    "critique": "Critique",
    "vigilance": "Vigilance",
    "info": "Information",
}

#: Colonnes du CSV — ordre stable, tri naturel sous Excel.
COLONNES_CSV: Final[tuple[str, ...]] = (
    "gravite", "type", "client", "mission", "libelle", "echeance",
)


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    parties = brut.split("-")
    if len(parties) != 3 or not all(parties):
        return ""
    a, m, j = parties
    return f"{j}/{m}/{a}"


def _libelle_type(type_alerte: object) -> str:
    """Libellé français du type — le code brut si type inconnu."""
    brut = str(type_alerte or "")
    return LIBELLES_TYPE.get(brut, brut)


def rendre_alertes_texte(corps: dict[str, Any]) -> str:
    """PUR — centre d'alertes en texte français lisible (réunion).

    En-tête cabinet + date d'édition, alertes groupées par gravité
    (critique / vigilance / info) avec libellé français du type,
    client, échéance si présente ; synthèse par type ; sources en
    échec signalées ; note consultative en pied. Tolérant : un corps
    vide ou partiel produit un document valide.
    """
    alertes = list(corps.get("alertes") or [])
    synthese = dict(corps.get("synthese") or {})
    sources_en_echec = list(corps.get("sources_en_echec") or [])
    date_fr = _date_fr(corps.get("aujourd_hui"))

    lignes: list[str] = [
        "CENTRE D'ALERTES DU CABINET",
        "",
    ]
    if date_fr:
        lignes.append(f"Date d'édition : {date_fr}")
    total = int(synthese.get("total") or len(alertes))
    lignes += [
        f"Signaux à l'attention du cabinet : {total}",
        "",
    ]

    # ── Groupes par gravité, ordre critique → info ────────────────
    for gravite in GRAVITES:
        groupe = [
            a for a in alertes if str(a.get("gravite") or "") == gravite
        ]
        titre = LIBELLES_GRAVITE.get(gravite, gravite)
        lignes.append(f"── {titre} ({len(groupe)}) " + "─" * 20)
        if not groupe:
            lignes.append("  Aucun signal.")
        for a in groupe:
            partie = f"  - [{_libelle_type(a.get('type'))}]"
            client = str(a.get("client") or "")
            if client:
                partie += f" {client} —"
            partie += f" {str(a.get('libelle') or '')}"
            echeance = _date_fr(a.get("echeance"))
            if echeance:
                partie += f" (échéance {echeance})"
            lignes.append(partie)
        lignes.append("")

    # ── Synthèse par type ─────────────────────────────────────────
    par_type = dict(synthese.get("par_type") or {})
    presents = [(t, n) for t, n in par_type.items() if int(n or 0) > 0]
    lignes.append("Synthèse par type :")
    if presents:
        for t, n in presents:
            lignes.append(f"  - {_libelle_type(t)} : {int(n)}")
    else:
        lignes.append("  Aucun signal.")
    lignes.append("")

    # ── Sources momentanément indisponibles ───────────────────────
    if sources_en_echec:
        lignes += [
            "Sources momentanément indisponibles : "
            + ", ".join(str(s) for s in sources_en_echec)
            + " — les autres signaux restent présentés.",
            "",
        ]

    # ── Note consultative en pied ─────────────────────────────────
    note = str(corps.get("note") or "")
    if note:
        lignes += ["Note : " + note]
    return "\n".join(lignes).rstrip() + "\n"


def rendre_alertes_csv(corps: dict[str, Any]) -> str:
    """PUR — centre d'alertes en CSV point-virgule pour Excel FR.

    BOM UTF-8 en tête (encodage reconnu par Excel), délimiteur « ; »,
    échappement délégué au module :mod:`csv` de la stdlib — jamais de
    concaténation manuelle. Colonnes stables :data:`COLONNES_CSV`.
    """
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for a in list(corps.get("alertes") or []):
        mission = a.get("mission_id")
        ecrivain.writerow([
            str(a.get("gravite") or ""),
            _libelle_type(a.get("type")),
            str(a.get("client") or ""),
            "" if mission is None else str(mission),
            str(a.get("libelle") or ""),
            str(a.get("echeance") or ""),
        ])
    return "\ufeff" + tampon.getvalue()
