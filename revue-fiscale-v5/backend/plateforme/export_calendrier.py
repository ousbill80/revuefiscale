"""Export téléchargeable du calendrier fiscal du cabinet — texte + CSV.

POURQUOI : la réunion hebdomadaire du cabinet planifie la charge des
prochains mois avec un support diffusable en interne — l'associé veut
EMPORTER le calendrier fiscal (imprimé ou partagé sur le réseau
interne), pas seulement le consulter à l'écran. Ce module REND le
corps DÉJÀ assemblé par
:func:`backend.plateforme.calendrier_cabinet.calendrier_cabinet` en
deux formats : texte français lisible (réunion) et CSV point-virgule
(tri sous Excel FR).

Aucun recalcul : fonctions PURES de mise en forme, mêmes données que
GET /cabinet/calendrier — assemblage déterministe et CONSULTATIF
(aucun LLM, aucun email), note consultative reprise en pied de
document. Pattern : :mod:`backend.plateforme.export_alertes`.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Final

#: Libellés français des types d'éléments — MÊME mapping que le
#: frontend (CalendrierCabinetVue.tsx, constante LIBELLES_TYPE) : les
#: intitulés lus en réunion sont ceux affichés à l'écran.
LIBELLES_TYPE: Final[dict[str, str]] = {
    "echeance_fiscale": "Échéance fiscale",
    "point_convenu": "Point convenu",
}

#: Formulation DOUCE d'une date déjà passée — constat de calendrier,
#: jamais un reproche (doctrine consultative du produit).
MENTION_DEPASSEE: Final[str] = "date passée — à reprogrammer si besoin"

#: Colonnes du CSV — ordre stable, tri naturel sous Excel.
COLONNES_CSV: Final[tuple[str, ...]] = (
    "mois", "date", "type", "client", "mission", "libelle", "depassee",
)


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    parties = brut.split("-")
    if len(parties) != 3 or not all(parties):
        return ""
    a, m, j = parties
    return f"{j}/{m}/{a}"


def _libelle_type(type_element: object) -> str:
    """Libellé français du type — le code brut si type inconnu."""
    brut = str(type_element or "")
    return LIBELLES_TYPE.get(brut, brut)


def rendre_calendrier_texte(corps: dict[str, Any]) -> str:
    """PUR — calendrier du cabinet en texte français lisible (réunion).

    En-tête cabinet + date d'édition, une section par mois (libellé
    français « Août 2026 ») avec, par ligne, la date JJ/MM/AAAA, le
    type en français, le client et le libellé — mention douce « date
    passée » le cas échéant ; compteurs ; sources en échec signalées ;
    note consultative en pied. Tolérant : un corps vide ou partiel
    produit un document valide.
    """
    mois = list(corps.get("mois") or [])
    compteurs = dict(corps.get("compteurs") or {})
    sources_en_echec = list(corps.get("sources_en_echec") or [])
    date_fr = _date_fr(corps.get("aujourd_hui"))

    lignes: list[str] = [
        "CALENDRIER FISCAL DU CABINET",
        "",
    ]
    if date_fr:
        lignes.append(f"Date d'édition : {date_fr}")
    horizon = corps.get("horizon_mois")
    if horizon:
        partie = f"Horizon : {int(horizon)} mois"
        fin = _date_fr(corps.get("fin_horizon"))
        if fin:
            partie += f" (jusqu'au {fin})"
        lignes.append(partie)
    nb_total = int(compteurs.get("nb_total") or 0)
    nb_depassees = int(compteurs.get("nb_depassees") or 0)
    nb_a_venir = int(compteurs.get("nb_a_venir") or 0)
    lignes += [
        f"Échéances et points sur l'horizon : {nb_total} "
        f"(à venir : {nb_a_venir}, dates déjà passées : {nb_depassees})",
        "",
    ]

    # ── Sections mensuelles, ordre chronologique du corps ─────────
    if not mois:
        lignes += ["Aucune échéance sur l'horizon choisi.", ""]
    for m in mois:
        titre = str(m.get("libelle_mois") or m.get("mois") or "")
        elements = list(m.get("elements") or [])
        lignes.append(f"── {titre} ({len(elements)}) " + "─" * 20)
        if not elements:
            lignes.append("  Aucun élément.")
        for e in elements:
            partie = f"  - {_date_fr(e.get('date'))}"
            partie += f" — [{_libelle_type(e.get('type'))}]"
            client = str(e.get("client") or "")
            if client:
                partie += f" {client} —"
            partie += f" {str(e.get('libelle') or '')}"
            if bool(e.get("depassee")):
                partie += f" ({MENTION_DEPASSEE})"
            lignes.append(partie)
        lignes.append("")

    # ── Sources momentanément indisponibles ───────────────────────
    if sources_en_echec:
        lignes += [
            "Sources momentanément indisponibles : "
            + ", ".join(str(s) for s in sources_en_echec)
            + " — le reste du calendrier reste présenté.",
            "",
        ]

    # ── Note consultative en pied ─────────────────────────────────
    note = str(corps.get("note") or "")
    if note:
        lignes += ["Note : " + note]
    return "\n".join(lignes).rstrip() + "\n"


def rendre_calendrier_csv(corps: dict[str, Any]) -> str:
    """PUR — calendrier du cabinet en CSV point-virgule pour Excel FR.

    BOM UTF-8 en tête (encodage reconnu par Excel), délimiteur « ; »,
    échappement délégué au module :mod:`csv` de la stdlib — jamais de
    concaténation manuelle. Colonnes stables :data:`COLONNES_CSV` —
    une ligne par élément, le mois « AAAA-MM » en première colonne
    pour trier/filtrer.
    """
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for m in list(corps.get("mois") or []):
        mois = str(m.get("mois") or "")
        for e in list(m.get("elements") or []):
            mission = e.get("mission_id")
            ecrivain.writerow([
                mois,
                str(e.get("date") or ""),
                _libelle_type(e.get("type")),
                str(e.get("client") or ""),
                "" if mission is None else str(mission),
                str(e.get("libelle") or ""),
                "oui" if bool(e.get("depassee")) else "non",
            ])
    return "\ufeff" + tampon.getvalue()
