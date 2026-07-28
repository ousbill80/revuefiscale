"""Brief du cabinet — assemblage texte des trois rendus cabinet.

POURQUOI : la réunion hebdomadaire du cabinet se prépare aujourd'hui
avec TROIS exports séparés (centre d'alertes, calendrier fiscal,
portefeuille déclaratif) — l'associé veut UN SEUL document texte à
imprimer ou diffuser en interne : le « brief du cabinet ».

Aucun recalcul et AUCUNE génération : ce module ASSEMBLE les corps
DÉJÀ construits par les vues existantes et réutilise TELS QUELS
:func:`backend.plateforme.export_alertes.rendre_alertes_texte` et
:func:`backend.plateforme.export_calendrier.rendre_calendrier_texte`
— déterministe et CONSULTATIF (aucun LLM, aucun email), formulations
douces, note consultative finale : l'équipe arbitre en réunion.

TOLÉRANCE : chaque section est optionnelle — une source en échec
(``None``) est remplacée par une mention douce « section indisponible
ce jour », jamais une exception. Pattern texte :
:mod:`backend.plateforme.export_alertes`.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from backend.plateforme.export_alertes import rendre_alertes_texte
from backend.plateforme.export_calendrier import rendre_calendrier_texte
from backend.plateforme.portefeuille_declaratif import STATUT_A_COMPLETER

#: Mention DOUCE d'une section dont la source a échoué — constat
#: factuel, jamais un reproche ni une erreur technique exposée.
MENTION_SECTION_INDISPONIBLE: Final[str] = (
    "Section indisponible ce jour — les autres sections du brief "
    "restent présentées."
)

#: Note consultative finale COMMUNE — ferme toujours le brief.
NOTE_BRIEF: Final[str] = (
    "Brief consultatif préparé pour la réunion hebdomadaire du "
    "cabinet : il assemble, sans les recalculer, le centre "
    "d'alertes, le calendrier fiscal et le suivi déclaratif du "
    "portefeuille. Document préparatoire de réunion — l'équipe "
    "examine chaque point et arbitre les priorités."
)

#: Titres français des trois sections, dans l'ordre de lecture.
TITRES_SECTIONS: Final[tuple[str, str, str]] = (
    "Centre d'alertes",
    "Calendrier fiscal",
    "Portefeuille déclaratif",
)

#: Séparateur net entre sections — repère visuel à l'impression.
SEPARATEUR: Final[str] = "═" * 60


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    parties = brut.split("-")
    if len(parties) != 3 or not all(parties):
        return ""
    a, m, j = parties
    return f"{j}/{m}/{a}"


def _periode_fr(periode: object) -> str:
    """« MM/AAAA » depuis une période « AAAA-MM » — brut si inconnu."""
    brut = str(periode or "").strip()
    parties = brut.split("-")
    if len(parties) != 2 or not all(parties):
        return brut
    a, m = parties
    return f"{m}/{a}"


def _manquantes_compactes(bloc: dict[str, Any] | None) -> str:
    """PUR — périodes manquantes d'un bloc en liste compacte FR."""
    manquantes = list((bloc or {}).get("manquantes") or [])
    return ", ".join(_periode_fr(p) for p in manquantes)


def rendre_portefeuille_texte(corps: dict[str, Any]) -> str:
    """PUR — portefeuille déclaratif en texte français lisible.

    Synthèse (compteurs), missions à compléter avec leurs périodes
    manquantes compactes (TVA / salaires), note consultative en pied.
    Formulations factuelles, jamais accusatoires — tolérant : un
    corps vide ou partiel produit un document valide.
    """
    synthese = dict(corps.get("synthese") or {})
    missions = list(corps.get("missions") or [])
    date_fr = _date_fr(corps.get("aujourd_hui"))

    lignes: list[str] = [
        "PORTEFEUILLE DÉCLARATIF DU CABINET",
        "",
    ]
    if date_fr:
        lignes.append(f"Date d'édition : {date_fr}")
    nb_missions = int(synthese.get("nb_missions") or len(missions))
    nb_a_jour = int(synthese.get("nb_a_jour") or 0)
    nb_a_completer = int(synthese.get("nb_a_completer") or 0)
    nb_indispo = int(synthese.get("nb_indisponibles") or 0)
    lignes += [
        f"Missions suivies : {nb_missions} "
        f"(à jour : {nb_a_jour}, collecte à organiser : "
        f"{nb_a_completer}, indisponibles : {nb_indispo})",
        "",
    ]

    # ── Missions où la collecte est à organiser ───────────────────
    a_completer = [
        m for m in missions
        if str(m.get("statut") or "") == STATUT_A_COMPLETER
    ]
    lignes.append(
        f"── Collecte à organiser ({len(a_completer)}) " + "─" * 20
    )
    if not a_completer:
        lignes.append(
            "  Aucune période à saisir sur le portefeuille."
        )
    for m in a_completer:
        entete = f"  - {str(m.get('client') or '')}"
        exercice = m.get("exercice")
        if exercice:
            entete += f" (exercice {int(exercice)})"
        parties: list[str] = []
        tva = _manquantes_compactes(m.get("tva"))
        if tva:
            parties.append(f"TVA à saisir : {tva}")
        salaires = _manquantes_compactes(m.get("salaires"))
        if salaires:
            parties.append(f"impôts sur salaires à saisir : {salaires}")
        if parties:
            entete += " — " + " ; ".join(parties)
        lignes.append(entete)
    lignes.append("")

    # ── Note consultative en pied ─────────────────────────────────
    note = str(corps.get("note") or "")
    if note:
        lignes += ["Note : " + note]
    return "\n".join(lignes).rstrip() + "\n"


def _section(
    titre: str, corps: dict[str, Any] | None, rendu
) -> list[str]:
    """PUR — une section du brief, TOLÉRANTE (jamais d'exception).

    ``corps`` absent (source en échec) ou rendu qui lève → mention
    douce :data:`MENTION_SECTION_INDISPONIBLE` à la place du contenu.
    """
    lignes = [SEPARATEUR, titre.upper(), SEPARATEUR, ""]
    if corps is None:
        lignes += [MENTION_SECTION_INDISPONIBLE, ""]
        return lignes
    try:
        lignes += [str(rendu(corps)).rstrip(), ""]
    except Exception:  # noqa: BLE001 — section annexe tolérée
        lignes += [MENTION_SECTION_INDISPONIBLE, ""]
    return lignes


def _compteur_sommaire(
    corps: dict[str, Any] | None, extraire
) -> str:
    """PUR — compteur du sommaire, « indisponible » si source échouée."""
    if corps is None:
        return "section indisponible ce jour"
    try:
        return str(extraire(corps))
    except Exception:  # noqa: BLE001 — sommaire annexe toléré
        return "section indisponible ce jour"


def rendre_brief_texte(
    alertes: dict[str, Any] | None,
    calendrier: dict[str, Any] | None,
    portefeuille: dict[str, Any] | None,
    aujourd_hui: date | None = None,
) -> str:
    """PUR — brief du cabinet : page de garde + trois sections.

    Page de garde (titre, date d'édition JJ/MM/AAAA, sommaire avec
    compteurs clés), puis le centre d'alertes et le calendrier rendus
    par les fonctions d'export EXISTANTES (aucune duplication) et le
    portefeuille par :func:`rendre_portefeuille_texte` — séparateurs
    nets, note consultative finale commune. Chaque section est
    tolérante : source ``None`` → mention douce, jamais d'exception.
    """
    jour = aujourd_hui or date.today()

    def _c_alertes(c: dict[str, Any]) -> str:
        total = int(dict(c.get("synthese") or {}).get("total") or 0)
        return f"{total} signal(aux)"

    def _c_calendrier(c: dict[str, Any]) -> str:
        nb = int(dict(c.get("compteurs") or {}).get("nb_total") or 0)
        return f"{nb} échéance(s) et point(s)"

    def _c_portefeuille(c: dict[str, Any]) -> str:
        s = dict(c.get("synthese") or {})
        return (
            f"{int(s.get('nb_missions') or 0)} mission(s), "
            f"collecte à organiser : {int(s.get('nb_a_completer') or 0)}"
        )

    lignes: list[str] = [
        SEPARATEUR,
        "BRIEF DU CABINET",
        SEPARATEUR,
        "",
        f"Date d'édition : {_date_fr(jour.isoformat())}",
        "",
        "Sommaire :",
        f"  1. {TITRES_SECTIONS[0]} — "
        + _compteur_sommaire(alertes, _c_alertes),
        f"  2. {TITRES_SECTIONS[1]} — "
        + _compteur_sommaire(calendrier, _c_calendrier),
        f"  3. {TITRES_SECTIONS[2]} — "
        + _compteur_sommaire(portefeuille, _c_portefeuille),
        "",
    ]

    lignes += _section(
        f"1. {TITRES_SECTIONS[0]}", alertes, rendre_alertes_texte
    )
    lignes += _section(
        f"2. {TITRES_SECTIONS[1]}", calendrier, rendre_calendrier_texte
    )
    lignes += _section(
        f"3. {TITRES_SECTIONS[2]}",
        portefeuille,
        rendre_portefeuille_texte,
    )

    lignes += [SEPARATEUR, "", "Note : " + NOTE_BRIEF]
    return "\n".join(lignes).rstrip() + "\n"
