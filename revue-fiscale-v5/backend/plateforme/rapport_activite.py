"""Rapport d'activité mensuel du cabinet — synthèse de réunion.

POURQUOI : la réunion mensuelle du cabinet se prépare aujourd'hui en
ouvrant plusieurs vues (missions, points convenus, centre d'alertes,
journal) — l'associé veut UNE synthèse chiffrée du mois écoulé :
missions créées et clôturées, points convenus créés et soldés,
répartition ACTUELLE des alertes par gravité et volume d'activité au
journal par grande famille d'actions.

POSTURE : synthèse DÉTERMINISTE et CONSULTATIVE (aucun LLM, aucun
email) destinée au pilotage COLLECTIF du cabinet — AUCUN indicateur de
performance individuelle : pas de compteur par collaborateur, pas de
classement, pas de score. L'équipe examine les chiffres en réunion et
décide.

PÉRIMÈTRE DES DONNÉES (choix documentés) :
- missions créées : ``mission.cree_le`` dans le mois ;
- missions clôturées : entrées ``changement_statut`` du journal
  d'audit dont le nouveau statut est « cloturee » dans le mois (la
  table mission ne porte pas de date de clôture — le journal fait
  foi) ;
- points convenus créés : ``point_convenu.cree_le`` dans le mois ;
- points convenus soldés : points au statut « fait » dont
  ``mis_a_jour_le`` tombe dans le mois (approximation assumée : la
  dernière mise à jour d'un point « fait » est son passage à ce
  statut) ;
- alertes par gravité : INSTANTANÉ du centre d'alertes au jour
  d'édition (:mod:`backend.plateforme.centre_alertes`) — PAS un
  historique du mois, la mention figure dans le document ;
- journal : entrées du mois groupées par grande famille d'actions
  (imports, exports, consultations, modifications), familles déduites
  des actions du référentiel
  :data:`backend.plateforme.journal_cabinet.LIBELLES_ACTION`, plafond
  raisonnable d'actions distinctes examinées.

Lecture seule sous RLS via ``contexte_tenant`` — AUCUNE écriture,
AUCUNE migration. Pattern texte :
:mod:`backend.plateforme.export_journal_cabinet`.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.centre_alertes import (
    GRAVITES,
    centre_alertes_cabinet,
)
from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Mois français (index 1 à 12) — en-tête du rapport.
MOIS_FR: Final[tuple[str, ...]] = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

#: Grandes familles d'actions du journal, dans l'ordre de lecture.
FAMILLES: Final[tuple[str, ...]] = (
    "imports", "exports", "consultations", "modifications",
)

#: Libellés français des familles — compteurs AGRÉGÉS, jamais par
#: personne (le rapport pilote le cabinet, il n'évalue personne).
LIBELLES_FAMILLE: Final[dict[str, str]] = {
    "imports": "Imports et dépôts",
    "exports": "Exports et documents produits",
    "consultations": "Consultations",
    "modifications": "Modifications et décisions",
}

#: Préfixes d'action → famille — déduits du référentiel
#: :data:`backend.plateforme.journal_cabinet.LIBELLES_ACTION` : les
#: actions « import_* » et « depot_* » sont des imports, les actions
#: « export_* », « telechargement_* » et « generation_* » produisent
#: ou emportent un document, les « consultation_* » sont des lectures ;
#: tout le reste (créations, saisies, décisions…) est une modification.
_PREFIXES_FAMILLE: Final[tuple[tuple[str, str], ...]] = (
    ("import_", "imports"),
    ("depot_", "imports"),
    ("export_", "exports"),
    ("telechargement_", "exports"),
    ("generation_", "exports"),
    ("consultation_", "consultations"),
)

#: Plafond d'actions DISTINCTES examinées au journal du mois —
#: synthèse de réunion, pas un dump de base.
PLAFOND_ACTIONS_DISTINCTES: Final[int] = 200

#: Libellés français des gravités du centre d'alertes.
LIBELLES_GRAVITE: Final[dict[str, str]] = {
    "critique": "Critique",
    "vigilance": "Vigilance",
    "info": "Information",
}

#: Mention DOUCE d'une section dont la source a échoué.
MENTION_SECTION_INDISPONIBLE: Final[str] = (
    "Section indisponible ce jour — les autres sections du rapport "
    "restent présentées."
)

#: Mention explicite : les alertes sont un INSTANTANÉ, pas un
#: historique du mois.
MENTION_INSTANTANE_ALERTES: Final[str] = (
    "Répartition des alertes ACTUELLES du centre d'alertes au jour "
    "d'édition — instantané, pas un historique du mois."
)

NOTE_RAPPORT: Final[str] = (
    "Rapport d'activité consultatif du cabinet, préparé pour la "
    "réunion mensuelle : compteurs agrégés du mois (missions, points "
    "convenus, activité enregistrée au journal) et instantané du "
    "centre d'alertes au jour d'édition. Document de pilotage "
    "COLLECTIF : aucun indicateur de performance individuelle, aucun "
    "classement — l'équipe examine les chiffres et décide. Aucun "
    "email n'est envoyé."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_mois(mois: Any) -> tuple[int, int]:
    """PUR — « AAAA-MM » → (année, mois) ; illisible → ``ValueError``.

    Format STRICT (4 chiffres, tiret, 2 chiffres), mois dans [1, 12],
    année dans [2000, 2100] — un rapport de réunion porte sur une
    période plausible, pas sur une saisie fantaisiste.
    """
    brut = str(mois or "").strip()
    parties = brut.split("-")
    if len(parties) != 2 or len(parties[0]) != 4 or len(parties[1]) != 2:
        raise ValueError("mois attendu au format AAAA-MM")
    if not (parties[0].isdigit() and parties[1].isdigit()):
        raise ValueError("mois attendu au format AAAA-MM")
    annee, numero = int(parties[0]), int(parties[1])
    if not 1 <= numero <= 12:
        raise ValueError("mois attendu entre 01 et 12")
    if not 2000 <= annee <= 2100:
        raise ValueError("année attendue entre 2000 et 2100")
    return annee, numero


def bornes_mois(annee: int, numero: int) -> tuple[date, date]:
    """PUR — [début du mois, début du mois suivant[ (bornes franches)."""
    debut = date(annee, numero, 1)
    fin = (
        date(annee + 1, 1, 1)
        if numero == 12
        else date(annee, numero + 1, 1)
    )
    return debut, fin


def libelle_mois_fr(annee: int, numero: int) -> str:
    """PUR — « juillet 2026 » depuis (2026, 7)."""
    return f"{MOIS_FR[numero - 1]} {annee}"


def famille_action(action: Any) -> str:
    """PUR — grande famille d'une action du journal (jamais bloquant).

    Préfixes du référentiel ; action inconnue ou illisible →
    « modifications » (famille par défaut : le rapport reste complet
    même si le code évolue).
    """
    brute = str(action or "")
    for prefixe, famille in _PREFIXES_FAMILLE:
        if brute.startswith(prefixe):
            return famille
    return "modifications"


def rendre_rapport_texte(corps: dict[str, Any]) -> str:
    """PUR — rapport d'activité en texte français lisible (réunion).

    En-tête « RAPPORT D'ACTIVITÉ DU CABINET — <mois en français
    AAAA> », sections missions / points convenus / alertes actuelles
    (mention explicite d'instantané) / activité au journal, note
    consultative finale. Compteurs AGRÉGÉS uniquement — aucune
    statistique par personne. Tolérant : corps vide ou partiel →
    document valide.
    """
    missions = dict(corps.get("missions") or {})
    points = dict(corps.get("points_convenus") or {})
    alertes = dict(corps.get("alertes_actuelles") or {})
    journal = dict(corps.get("journal") or {})
    mois_libelle = str(corps.get("mois_libelle") or "")

    titre = "RAPPORT D'ACTIVITÉ DU CABINET"
    if mois_libelle:
        titre += f" — {mois_libelle}"
    lignes: list[str] = [titre, ""]

    # ── Missions du mois ──────────────────────────────────────────
    lignes += [
        "── Missions " + "─" * 30,
        f"  Missions créées dans le mois : {missions.get('creees', '0')}",
        "  Missions clôturées dans le mois : "
        f"{missions.get('cloturees', '0')}",
        "",
    ]

    # ── Points convenus du mois ───────────────────────────────────
    lignes += [
        "── Points convenus " + "─" * 23,
        "  Points convenus créés dans le mois : "
        f"{points.get('crees', '0')}",
        "  Points convenus soldés dans le mois : "
        f"{points.get('soldes', '0')}",
        "",
    ]

    # ── Alertes actuelles — INSTANTANÉ, pas un historique ─────────
    lignes += [
        "── Alertes actuelles par gravité " + "─" * 9,
        f"  {MENTION_INSTANTANE_ALERTES}",
    ]
    if alertes.get("disponible") is False:
        lignes.append(f"  {MENTION_SECTION_INDISPONIBLE}")
    else:
        par_gravite = dict(alertes.get("par_gravite") or {})
        for gravite in GRAVITES:
            lignes.append(
                f"  {LIBELLES_GRAVITE.get(gravite, gravite)} : "
                f"{par_gravite.get(gravite, '0')}"
            )
        lignes.append(f"  Total : {alertes.get('total', '0')}")
    lignes.append("")

    # ── Activité enregistrée au journal ───────────────────────────
    lignes += [
        "── Activité enregistrée au journal " + "─" * 7,
        "  Entrées de journal dans le mois : "
        f"{journal.get('total', '0')}",
    ]
    par_famille = dict(journal.get("par_famille") or {})
    for famille in FAMILLES:
        lignes.append(
            f"  {LIBELLES_FAMILLE[famille]} : "
            f"{par_famille.get(famille, '0')}"
        )
    if journal.get("plafond_atteint"):
        lignes.append(
            "  Décompte plafonné aux actions les plus fréquentes — "
            "volumes indicatifs."
        )
    lignes.append("")

    # ── Note consultative en pied — l'humain décide ───────────────
    note = str(corps.get("note") or "")
    if note:
        lignes.append("Note : " + note)
    return "\n".join(lignes).rstrip() + "\n"


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def rapport_activite_cabinet(
    session: Session,
    tenant_id: int,
    mois: str | None = None,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Rapport d'activité mensuel — LECTURE SEULE, RLS, agrégats.

    ``mois`` au format « AAAA-MM » (défaut : mois courant) —
    ``ValueError`` si illisible (la route traduit en 422). Compteurs
    en ``str`` (contrat homogène avec les autres synthèses), AUCUNE
    donnée nominative dans les agrégats. Le centre d'alertes est
    toléré : en échec, sa section est marquée indisponible — jamais
    bloquant.
    """
    jour = aujourd_hui or date.today()
    annee, numero = valider_mois(mois or f"{jour.year:04d}-{jour.month:02d}")
    debut, fin = bornes_mois(annee, numero)
    params = {"debut": debut.isoformat(), "fin": fin.isoformat()}

    with contexte_tenant(session, tenant_id):
        nb_missions_creees = session.execute(
            text(
                "SELECT COUNT(*) FROM mission "
                "WHERE cree_le >= :debut AND cree_le < :fin"
            ),
            params,
        ).scalar_one()
        # Clôtures : la table mission ne porte pas de date de clôture —
        # le journal d'audit (changement_statut → cloturee) fait foi.
        nb_missions_cloturees = session.execute(
            text(
                "SELECT COUNT(DISTINCT mission_id) FROM journal_audit "
                "WHERE action = 'changement_statut' "
                "AND charge_utile->>'statut' = 'cloturee' "
                "AND mission_id IS NOT NULL "
                "AND horodatage >= :debut AND horodatage < :fin"
            ),
            params,
        ).scalar_one()
        nb_points_crees = session.execute(
            text(
                "SELECT COUNT(*) FROM point_convenu "
                "WHERE cree_le >= :debut AND cree_le < :fin"
            ),
            params,
        ).scalar_one()
        nb_points_soldes = session.execute(
            text(
                "SELECT COUNT(*) FROM point_convenu "
                "WHERE statut = 'fait' "
                "AND mis_a_jour_le >= :debut AND mis_a_jour_le < :fin"
            ),
            params,
        ).scalar_one()
        total_journal = session.execute(
            text(
                "SELECT COUNT(*) FROM journal_audit "
                "WHERE horodatage >= :debut AND horodatage < :fin"
            ),
            params,
        ).scalar_one()
        groupes = session.execute(
            text(
                "SELECT action, COUNT(*) AS nb FROM journal_audit "
                "WHERE horodatage >= :debut AND horodatage < :fin "
                "GROUP BY action ORDER BY nb DESC, action "
                "LIMIT :plafond"
            ),
            {**params, "plafond": PLAFOND_ACTIONS_DISTINCTES},
        ).mappings().all()

    par_famille = dict.fromkeys(FAMILLES, 0)
    for g in groupes:
        par_famille[famille_action(g["action"])] += int(g["nb"])

    # Instantané du centre d'alertes — TOLÉRÉ : un échec de cette
    # source annexe ne bloque jamais le rapport de réunion.
    alertes_actuelles: dict[str, Any]
    try:
        centre = centre_alertes_cabinet(session, tenant_id, jour)
        synthese = dict(centre.get("synthese") or {})
        brut = dict(synthese.get("par_gravite") or {})
        alertes_actuelles = {
            "disponible": True,
            "au": jour.isoformat(),
            "total": str(int(synthese.get("total") or 0)),
            "par_gravite": {
                g: str(int(brut.get(g) or 0)) for g in GRAVITES
            },
            "mention": MENTION_INSTANTANE_ALERTES,
        }
    except Exception:  # noqa: BLE001 — source annexe tolérée
        alertes_actuelles = {
            "disponible": False,
            "au": jour.isoformat(),
            "total": "0",
            "par_gravite": dict.fromkeys(GRAVITES, "0"),
            "mention": MENTION_INSTANTANE_ALERTES,
        }

    return {
        "mois": f"{annee:04d}-{numero:02d}",
        "mois_libelle": libelle_mois_fr(annee, numero),
        "missions": {
            "creees": str(int(nb_missions_creees)),
            "cloturees": str(int(nb_missions_cloturees)),
        },
        "points_convenus": {
            "crees": str(int(nb_points_crees)),
            "soldes": str(int(nb_points_soldes)),
        },
        "alertes_actuelles": alertes_actuelles,
        "journal": {
            "total": str(int(total_journal)),
            "par_famille": {f: str(n) for f, n in par_famille.items()},
            "plafond_atteint": len(groupes) >= PLAFOND_ACTIONS_DISTINCTES,
        },
        "note": NOTE_RAPPORT,
    }
