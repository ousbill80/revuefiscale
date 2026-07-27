"""Agenda fiscal du cabinet — échéances à venir des missions actives.

Vue TRANSVERSE pour le fiscaliste : sur toutes les missions actives du
tenant (statuts non clôturés — ``cadrage`` et ``en_cours``), les
échéances fiscales dont la date limite tombe dans une fenêtre à venir
(défaut 30 jours, maximum 90). Chaque échéance est confrontée aux
pièces déjà collectées en data room (même correspondance déterministe
que le civisme fiscal) : « couverte » si une pièce correspond,
« à préparer » sinon — la liste de travail du cabinet pour anticiper
les dépôts de ses clients et éviter pénalités et intérêts de retard.

Réutilise :func:`backend.plateforme.echeancier_fiscal.construire_echeancier`
(échéancier théorique de l'exercice revu, hypothèses documentées là-bas)
et :mod:`backend.plateforme.civisme_fiscal` (rapprochement pièces).

Analyse CONSULTATIVE : une échéance « à préparer » signale seulement
qu'aucune pièce correspondante n'a été collectée — le fiscaliste
vérifie auprès du client. Aucun LLM, aucun calcul d'impôt : fonctions
pures + lecture seule sous RLS.
"""
from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.civisme_fiscal import (
    STATUT_COUVERTE,
    elements_depuis_pieces,
    rapprocher,
)
from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeancier_fiscal import (
    _profil_mission,
    _releve_de_la_dge,
    construire_echeancier,
    normaliser_regime,
)

# ── Constantes ───────────────────────────────────────────────────────

STATUT_A_PREPARER: Final[str] = "a_preparer"
JOURS_DEFAUT: Final[int] = 30
JOURS_MAX: Final[int] = 90

MENTION_NOTE: Final[str] = (
    "Agenda consultatif — échéancier théorique (référentiel indicatif, "
    "vérifier le calendrier officiel DGI) rapproché des pièces de la "
    "data room de mission : une échéance « à préparer » signifie "
    "seulement qu'aucune pièce correspondante n'a été collectée. "
    "À vérifier par le fiscaliste avant toute conclusion."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def _jours_bornes(jours: int) -> int:
    """Fenêtre bornée à [1, 90] jours (défensif — la route valide déjà)."""
    return max(1, min(int(jours), JOURS_MAX))


def echeances_dans_fenetre(
    echeances: list[dict[str, Any]], aujourd_hui: date, jours: int
) -> list[dict[str, Any]]:
    """PUR — échéances dont la date limite tombe dans la fenêtre à venir.

    Fenêtre [aujourd_hui, aujourd_hui + jours], bornes incluses : une
    échéance du jour même est encore actionnable. Les échéances passées
    sont hors agenda (elles relèvent du civisme fiscal de la mission).
    """
    fin = aujourd_hui + timedelta(days=_jours_bornes(jours))
    return [
        e
        for e in echeances
        if aujourd_hui <= date.fromisoformat(str(e["date_limite"])) <= fin
    ]


def construire_agenda(
    missions: list[dict[str, Any]], aujourd_hui: date, jours: int = JOURS_DEFAUT
) -> list[dict[str, Any]]:
    """PUR — agenda des échéances à venir sur un jeu de missions actives.

    Chaque mission : ``{mission_id, client, exercice, regime, dge,
    pieces}`` (pièces au format ``piece_mission`` : type_piece,
    nom_fichier). Pour chacune : échéancier théorique de l'exercice
    (:func:`construire_echeancier`), fenêtre à venir, puis rapprochement
    avec les pièces collectées (:func:`rapprocher`) — statut
    ``couverte`` si une pièce correspond, ``a_preparer`` sinon.

    Résultat trié par date limite croissante (puis client, impôt,
    obligation — ordre stable et lisible). Items : ``{date_limite,
    impot, obligation, periode, mission_id, client, statut}``.
    """
    items: list[dict[str, Any]] = []
    for mission in missions:
        exercice = int(mission["exercice"])
        echeances = construire_echeancier(
            exercice,
            str(mission.get("regime") or ""),
            dge=bool(mission.get("dge")),
        )
        a_venir = echeances_dans_fenetre(echeances, aujourd_hui, jours)
        if not a_venir:
            continue
        elements = elements_depuis_pieces(
            list(mission.get("pieces") or []), exercice
        )
        for r in rapprocher(a_venir, elements, aujourd_hui):
            items.append(
                {
                    "date_limite": r["date_limite"],
                    "impot": r["impot"],
                    "obligation": r["obligation"],
                    "periode": r["periode"],
                    "mission_id": int(mission["mission_id"]),
                    "client": str(mission.get("client") or ""),
                    "statut": (
                        STATUT_COUVERTE
                        if r["statut"] == STATUT_COUVERTE
                        else STATUT_A_PREPARER
                    ),
                }
            )
    items.sort(
        key=lambda e: (
            e["date_limite"],
            e["client"],
            e["impot"],
            e["obligation"],
        )
    )
    return items


def synthese_agenda(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs + prochaine échéance à préparer (ISO ou None)."""
    couvertes = sum(1 for i in items if i["statut"] == STATUT_COUVERTE)
    a_preparer = len(items) - couvertes
    prochaine = next(
        (
            i["date_limite"]
            for i in items
            if i["statut"] == STATUT_A_PREPARER
        ),
        None,
    )
    return {
        "total": len(items),
        "a_preparer": a_preparer,
        "couvertes": couvertes,
        "prochaine_echeance": prochaine,
    }


# ── Export iCalendar (RFC 5545, texte brut, sans dépendance) ─────────

_ICS_PRODID: Final[str] = "-//Revue Fiscale//Agenda fiscal cabinet//FR"
_ICS_FIN_LIGNE: Final[str] = "\r\n"


def _echapper_ics(valeur: str) -> str:
    """PUR — échappe une valeur texte iCalendar (RFC 5545 §3.3.11).

    Antislash d'abord (sinon double échappement), puis point-virgule,
    virgule et retours à la ligne (``\\n`` littéral).
    """
    return (
        str(valeur)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _plier_ligne_ics(ligne: str) -> list[str]:
    """PUR — plie une ligne de contenu à 75 octets (RFC 5545 §3.1).

    Les lignes de continuation commencent par un espace et comptent 74
    octets utiles. Coupe sur des frontières d'octets UTF-8 valides (on
    recule si l'octet suivant est une continuation ``10xxxxxx``).
    """
    octets = ligne.encode("utf-8")
    if len(octets) <= 75:
        return [ligne]
    morceaux: list[str] = []
    debut, limite = 0, 75
    while debut < len(octets):
        fin = min(debut + limite, len(octets))
        # Ne pas couper au milieu d'un caractère multi-octets.
        while fin < len(octets) and (octets[fin] & 0xC0) == 0x80:
            fin -= 1
        prefixe = " " if morceaux else ""
        morceaux.append(prefixe + octets[debut:fin].decode("utf-8"))
        debut, limite = fin, 74
    return morceaux


def _uid_ics(echeance: dict[str, Any]) -> str:
    """PUR — UID déterministe et stable d'une échéance.

    ``{mission_id}-{impot normalisé}-{date}@revuefiscale`` : ne dépend
    que de la mission, de l'impôt et de la date limite (stable entre
    deux exports — les agendas mettent à jour l'événement au lieu de le
    dupliquer). L'impôt est réduit à un jeton ASCII sûr pour un UID.
    L'obligation normalisée est ajoutée si nécessaire pour distinguer
    deux obligations du même impôt à la même date.
    """
    impot = _jeton_uid(str(echeance["impot"]))
    obligation = _jeton_uid(str(echeance.get("obligation") or ""))
    base = f"{int(echeance['mission_id'])}-{impot}-{echeance['date_limite']}"
    if obligation:
        base = f"{base}-{obligation}"
    return f"{base}@revuefiscale"


def _jeton_uid(valeur: str) -> str:
    """PUR — réduit un libellé à un jeton ``[a-z0-9-]`` (UID lisible)."""
    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFKD", valeur.lower())
        if not unicodedata.combining(c)
    )
    jeton = "".join(c if c.isalnum() else "-" for c in sans_accents)
    while "--" in jeton:
        jeton = jeton.replace("--", "-")
    return jeton.strip("-")


def generer_ics(echeances: list[dict[str, Any]], aujourd_hui: date) -> str:
    """PUR — calendrier iCalendar (RFC 5545) des échéances de l'agenda.

    Un ``VEVENT`` par échéance : événement « journée entière »
    (``DTSTART;VALUE=DATE``), ``SUMMARY`` « [impot] obligation —
    client », ``DESCRIPTION`` avec période / mission / statut,
    ``CATEGORIES`` reprenant le statut et ``UID`` déterministe stable
    (:func:`_uid_ics`). ``DTSTAMP`` figé sur ``aujourd_hui`` à minuit
    UTC — sortie entièrement déterministe pour des entrées données.
    Texte brut, aucune dépendance ; lignes pliées à 75 octets, fins de
    ligne CRLF.
    """
    horodatage = f"{aujourd_hui.strftime('%Y%m%d')}T000000Z"
    lignes: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_ICS_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Agenda fiscal du cabinet",
    ]
    for e in echeances:
        date_limite = date.fromisoformat(str(e["date_limite"]))
        statut = str(e.get("statut") or STATUT_A_PREPARER)
        resume = (
            f"[{e['impot']}] {e['obligation']} — {e.get('client') or ''}"
        ).rstrip(" —")
        description = (
            f"Période : {e.get('periode') or '—'}\n"
            f"Mission : #{int(e['mission_id'])}"
            + (f" — {e['client']}" if e.get("client") else "")
            + "\nStatut : "
            + ("couverte" if statut == STATUT_COUVERTE else "à préparer")
        )
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{_uid_ics(e)}",
            f"DTSTAMP:{horodatage}",
            f"DTSTART;VALUE=DATE:{date_limite.strftime('%Y%m%d')}",
            f"SUMMARY:{_echapper_ics(resume)}",
            f"DESCRIPTION:{_echapper_ics(description)}",
            f"CATEGORIES:{_echapper_ics(statut)}",
            "END:VEVENT",
        ]
    lignes.append("END:VCALENDAR")
    pliees: list[str] = []
    for ligne in lignes:
        pliees.extend(_plier_ligne_ics(ligne))
    return _ICS_FIN_LIGNE.join(pliees) + _ICS_FIN_LIGNE


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def agenda_cabinet(
    session: Session,
    tenant_id: int,
    jours: int = JOURS_DEFAUT,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Agenda fiscal du cabinet (lecture seule, RLS stricte).

    Agrège les missions actives du tenant (statut ≠ ``cloturee``) avec
    leur client et leurs pièces de data room, puis délègue aux fonctions
    pures. Se construit toujours (tenant sans mission active → agenda
    vide, sans erreur).
    """
    jour = aujourd_hui or date.today()
    fenetre = _jours_bornes(jours)

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id, m.exercice, m.profil, "
                "c.denomination, c.centre_impots "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE COALESCE(m.statut, 'cadrage') <> 'cloturee' "
                "ORDER BY m.id"
            )
        ).mappings().all()
        pieces_par_mission: dict[int, list[dict[str, Any]]] = {}
        if rows:
            pieces = session.execute(
                text(
                    "SELECT mission_id, type_piece, nom_fichier "
                    "FROM piece_mission "
                    "WHERE mission_id = ANY(:missions) ORDER BY id"
                ),
                {"missions": [int(r["id"]) for r in rows]},
            ).mappings().all()
            for p in pieces:
                pieces_par_mission.setdefault(int(p["mission_id"]), []).append(
                    {
                        "type_piece": p["type_piece"],
                        "nom_fichier": p["nom_fichier"],
                    }
                )

    missions = [
        {
            "mission_id": int(r["id"]),
            "client": str(r["denomination"] or ""),
            "exercice": int(r["exercice"]),
            "regime": normaliser_regime(
                str(_profil_mission(r["profil"]).get("regime") or "")
            )
            or "reel",
            "dge": _releve_de_la_dge(r["centre_impots"]),
            "pieces": pieces_par_mission.get(int(r["id"]), []),
        }
        for r in rows
    ]
    echeances = construire_agenda(missions, jour, fenetre)
    return {
        "aujourd_hui": jour.isoformat(),
        "jours": fenetre,
        "fenetre_fin": (jour + timedelta(days=fenetre)).isoformat(),
        "missions_actives": len(missions),
        "echeances": echeances,
        "synthese": synthese_agenda(echeances),
        "note": MENTION_NOTE,
    }
