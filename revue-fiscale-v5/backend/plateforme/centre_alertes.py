"""Centre d'alertes in-app au niveau cabinet — agrégat lecture seule.

POURQUOI : les signaux d'attention du cabinet vivent dans des vues
séparées du tableau de bord (points convenus en attente, échéances
fiscales, budget temps, délais LPF des contrôles fiscaux). L'associé
veut UNE liste unique, triée par gravité, de tout ce qui réclame son
attention — sans ouvrir chaque bloc ni chaque mission.

Assemblage DÉTERMINISTE et CONSULTATIF (aucun LLM, AUCUN email, aucune
notification sortante) : chaque source est le MODULE EXISTANT qui
alimente déjà son endpoint dédié —
:mod:`backend.plateforme.points_convenus_cabinet` (points en retard ou
anciens > 30 j), :mod:`backend.plateforme.echeances_cabinet` (dates
limites des 30 prochains jours),
:mod:`backend.plateforme.rentabilite_mission` (budget temps en
vigilance / dépassement), :mod:`backend.plateforme.controles_fiscaux`
(délais de riposte LPF proches ou dépassés) et
:mod:`backend.plateforme.completude_declarative` (périodes mensuelles
échues sans déclaration saisie). Aucun calcul métier n'est
dupliqué : seules des fonctions PURES de conversion, tri, plafond et
synthèse s'ajoutent ici.

TOLÉRANCE : une source qui échoue est simplement ignorée (listée dans
``sources_en_echec``) — jamais bloquant, même pattern que
:mod:`backend.plateforme.dossier_mission`. Montants sérialisés en
``str`` (Decimal) par les modules réutilisés. Lecture seule sous RLS
via ``contexte_tenant`` — AUCUNE écriture, AUCUNE migration.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Gravités admises, de la plus grave à la plus bénigne.
GRAVITES: Final[tuple[str, ...]] = ("critique", "vigilance", "info")

#: Rang de tri par gravité — critique d'abord.
_RANG_GRAVITE: Final[dict[str, int]] = {g: i for i, g in enumerate(GRAVITES)}

#: Types d'alertes émis par les sources agrégées.
TYPES_ALERTE: Final[tuple[str, ...]] = (
    "point_convenu",
    "echeance_fiscale",
    "budget_temps",
    "delai_lpf",
    "completude_declarative",
)

# Plafond d'alertes restituées — vue de pilotage, pas un export.
PLAFOND_ALERTES: Final[int] = 100

# Plafond d'événements de contrôle fiscal examinés (coût borné).
PLAFOND_EVENEMENTS_LPF: Final[int] = 200

# Plafond de missions examinées pour la complétude déclarative
# (chaque mission déclenche une lecture — coût borné).
PLAFOND_MISSIONS_COMPLETUDE: Final[int] = 200

MENTION_NOTE: Final[str] = (
    "Centre d'alertes consultatif du cabinet — agrégation déterministe "
    "des signaux déjà calculés par les tableaux de bord existants : "
    "points convenus en retard ou anciens, échéances fiscales des 30 "
    "prochains jours, budget temps en vigilance ou dépassement, délais "
    "de riposte LPF proches ou dépassés, périodes mensuelles échues "
    "sans déclaration saisie. Aucune alerte n'est envoyée "
    "par email : tout reste dans l'application. Ces signaux éclairent "
    "la priorisation — le fiscaliste apprécie et décide, rien n'est "
    "automatique."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def normaliser_alerte(brute: dict[str, Any]) -> dict[str, Any]:
    """PUR — alerte au contrat stable, clés TOUJOURS présentes.

    ``type`` et ``gravite`` hors référentiel → « info » (défensif,
    jamais bloquant) ; ``echeance`` : date ISO ou ``None`` ; ``lien`` :
    volet logique de l'application où agir (texte court).
    """
    gravite = str(brute.get("gravite") or "")
    type_alerte = str(brute.get("type") or "")
    mission = brute.get("mission_id")
    echeance = brute.get("echeance")
    return {
        "type": type_alerte if type_alerte in TYPES_ALERTE else "info",
        "gravite": gravite if gravite in GRAVITES else "info",
        "client": str(brute.get("client") or ""),
        "mission_id": int(mission) if mission is not None else None,
        "libelle": str(brute.get("libelle") or ""),
        "echeance": str(echeance) if echeance else None,
        "lien": str(brute.get("lien") or ""),
    }


def trier_alertes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — gravité (critique d'abord) puis échéance croissante.

    À gravité égale, l'échéance la plus proche d'abord (alerte sans
    échéance en queue), puis client et mission — tri stable et
    déterministe.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        echeance = i.get("echeance")
        return (
            _RANG_GRAVITE.get(str(i.get("gravite")), len(GRAVITES)),
            (1, "") if not echeance else (0, str(echeance)),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
            str(i.get("libelle") or ""),
        )

    return sorted(items, key=_cle)


def plafonner_alertes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — tronque à :data:`PLAFOND_ALERTES` (liste déjà triée).

    Le plafond ne coupe donc que les alertes les moins graves / les
    plus lointaines — les critiques restent visibles.
    """
    return list(items)[:PLAFOND_ALERTES]


def synthese_alertes(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs : total, par gravité, par type, clients."""
    par_gravite = {g: 0 for g in GRAVITES}
    par_type = {t: 0 for t in TYPES_ALERTE}
    for i in items:
        g = str(i.get("gravite") or "")
        t = str(i.get("type") or "")
        if g in par_gravite:
            par_gravite[g] += 1
        if t in par_type:
            par_type[t] += 1
    clients = {str(i.get("client") or "") for i in items if i.get("client")}
    return {
        "total": len(items),
        "par_gravite": par_gravite,
        "par_type": par_type,
        "clients": len(clients),
    }


def assembler_centre(
    alertes: list[dict[str, Any]],
    sources_en_echec: list[str],
    aujourd_hui: date,
) -> dict[str, Any]:
    """PUR — vue finale : normalisation, tri, plafond, synthèse, note."""
    normalisees = [normaliser_alerte(a) for a in alertes]
    retenues = plafonner_alertes(trier_alertes(normalisees))
    return {
        "aujourd_hui": aujourd_hui.isoformat(),
        "alertes": retenues,
        "synthese": synthese_alertes(retenues),
        "sources_en_echec": sorted(sources_en_echec),
        "note": MENTION_NOTE,
    }


# ── Conversions pures par source (items DÉJÀ calculés en amont) ──────


def alertes_depuis_points(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — points convenus « à faire » → alertes point_convenu.

    Reprend les signaux déjà calculés par
    :func:`backend.plateforme.points_convenus_cabinet.points_convenus_cabinet`
    : « en retard » (date cible dépassée) → critique ; ancien
    > :data:`~backend.plateforme.points_convenus_cabinet.SEUIL_ANCIEN_JOURS`
    jours → vigilance ; les autres points ne remontent pas au centre.
    """
    from backend.plateforme.points_convenus_cabinet import SEUIL_ANCIEN_JOURS

    alertes: list[dict[str, Any]] = []
    for i in items:
        en_retard = bool(i.get("en_retard"))
        anciennete = int(i.get("anciennete_jours") or 0)
        if not en_retard and anciennete <= SEUIL_ANCIEN_JOURS:
            continue
        libelle = str(i.get("libelle") or "")
        detail = (
            "point convenu en retard"
            if en_retard
            else f"point convenu ancien ({anciennete} j)"
        )
        alertes.append(
            {
                "type": "point_convenu",
                "gravite": "critique" if en_retard else "vigilance",
                "client": i.get("client"),
                "mission_id": i.get("mission_id"),
                "libelle": f"{detail} — {libelle}" if libelle else detail,
                "echeance": i.get("date_cible"),
                "lien": "points_convenus",
            }
        )
    return alertes


def alertes_depuis_echeances(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — échéances fiscales de la fenêtre 30 j → alertes.

    Reprend la fenêtre et les jours restants déjà calculés par
    :func:`backend.plateforme.echeances_cabinet.echeances_cabinet` :
    ≤ :data:`~backend.plateforme.echeances_cabinet.SEUIL_SEMAINE_JOURS`
    jours (cette semaine) → vigilance, sinon → info.
    """
    from backend.plateforme.echeances_cabinet import SEUIL_SEMAINE_JOURS

    alertes: list[dict[str, Any]] = []
    for i in items:
        restants = int(i.get("jours_restants") or 0)
        impot = str(i.get("impot") or "")
        obligation = str(i.get("obligation") or "")
        alertes.append(
            {
                "type": "echeance_fiscale",
                "gravite": (
                    "vigilance"
                    if restants <= SEUIL_SEMAINE_JOURS
                    else "info"
                ),
                "client": i.get("client"),
                "mission_id": i.get("mission_id"),
                "libelle": (
                    f"échéance fiscale dans {restants} j — {impot}"
                    + (f" ({obligation})" if obligation else "")
                ),
                "echeance": i.get("date_limite"),
                "lien": "echeancier_fiscal",
            }
        )
    return alertes


def alertes_depuis_budget(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — missions sous tension budgétaire → alertes budget_temps.

    Reprend les seuils déjà calculés par
    :func:`backend.plateforme.rentabilite_mission.rentabilite_cabinet`
    (items déjà restreints à vigilance / dépassement) : « depassement »
    → critique, « vigilance » → vigilance ; autre seuil ignoré.
    """
    alertes: list[dict[str, Any]] = []
    for i in items:
        seuil = str(i.get("seuil") or "")
        if seuil not in ("vigilance", "depassement"):
            continue
        pct = i.get("pourcentage_consomme")
        detail = (
            "budget temps dépassé"
            if seuil == "depassement"
            else "budget temps en vigilance"
        )
        alertes.append(
            {
                "type": "budget_temps",
                "gravite": (
                    "critique" if seuil == "depassement" else "vigilance"
                ),
                "client": i.get("client"),
                "mission_id": i.get("mission_id"),
                "libelle": (
                    f"{detail} — {pct} % des honoraires consommés"
                    if pct not in (None, "")
                    else detail
                ),
                "echeance": None,
                "lien": "rentabilite",
            }
        )
    return alertes


def alertes_depuis_lpf(
    chronologies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — délais LPF proches ou dépassés → alertes delai_lpf.

    ``chronologies`` : entrées ``{client, mission_id, evenements}`` où
    ``evenements`` est la chronologie déjà construite par
    :func:`backend.plateforme.controles_fiscaux.construire_chronologie`
    (statut d'échéance et jours restants inclus). Dépassé → critique,
    proche (≤ 7 j) → vigilance ; à venir ou sans délai → rien.
    """
    from backend.plateforme.controles_fiscaux import (
        STATUT_DEPASSEE,
        STATUT_PROCHE,
    )

    alertes: list[dict[str, Any]] = []
    for m in chronologies:
        for e in m.get("evenements") or []:
            etat = e.get("echeance") or {}
            statut = str(etat.get("statut") or "")
            if statut not in (STATUT_PROCHE, STATUT_DEPASSEE):
                continue
            restants = etat.get("jours_restants")
            libelle_acte = str(e.get("libelle") or "")
            if statut == STATUT_DEPASSEE:
                detail = (
                    f"délai LPF dépassé depuis {abs(int(restants or 0))} j"
                )
            else:
                detail = f"délai LPF dans {int(restants or 0)} j"
            alertes.append(
                {
                    "type": "delai_lpf",
                    "gravite": (
                        "critique"
                        if statut == STATUT_DEPASSEE
                        else "vigilance"
                    ),
                    "client": m.get("client"),
                    "mission_id": m.get("mission_id"),
                    "libelle": (
                        f"{detail} — {libelle_acte}"
                        if libelle_acte
                        else detail
                    ),
                    "echeance": (e.get("delai_riposte") or {}).get(
                        "echeance"
                    ),
                    "lien": "controles_fiscaux",
                }
            )
    return alertes


def alertes_depuis_completude(
    vues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — complétudes déclaratives lacunaires → alertes.

    ``vues`` : entrées ``{client, mission_id, completude}`` où
    ``completude`` est la vue déjà construite par
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    (aucun recalcul ici). Statut global « aucune_saisie » (aucune
    période couverte alors que des périodes sont échues) → critique,
    « lacunaire » → vigilance ; complet, sans période échue ou vue
    indisponible → rien.
    """
    from backend.plateforme.completude_declarative import (
        STATUT_AUCUNE_SAISIE,
        STATUT_LACUNAIRE,
    )

    noms_courts = {"tva": "TVA", "salaires": "impôts sur salaires"}
    alertes: list[dict[str, Any]] = []
    for m in vues:
        vue = m.get("completude") or {}
        if not vue.get("disponible"):
            continue
        statut = str(
            (vue.get("synthese") or {}).get("statut_global") or ""
        )
        if statut not in (STATUT_LACUNAIRE, STATUT_AUCUNE_SAISIE):
            continue
        exercice = vue.get("exercice")
        details: list[str] = []
        for cle in sorted(vue.get("impots") or {}):
            bloc = (vue.get("impots") or {}).get(cle) or {}
            if not bloc.get("disponible"):
                continue
            nb = int(bloc.get("nb_manquantes") or 0)
            if nb <= 0:
                continue
            s = "s" if nb > 1 else ""
            details.append(
                f"{noms_courts.get(cle, cle)} : {nb} période{s} "
                f"manquante{s}"
            )
        detail = (
            "aucune déclaration mensuelle saisie"
            if statut == STATUT_AUCUNE_SAISIE
            else "complétude déclarative lacunaire"
        )
        libelle = f"{detail} — exercice {exercice}"
        if details:
            libelle += f" ({', '.join(details)})"
        alertes.append(
            {
                "type": "completude_declarative",
                "gravite": (
                    "critique"
                    if statut == STATUT_AUCUNE_SAISIE
                    else "vigilance"
                ),
                "client": m.get("client"),
                "mission_id": m.get("mission_id"),
                "libelle": libelle,
                "echeance": None,
                "lien": "completude_declarative",
            }
        )
    return alertes


# ── Sources (chacune réutilise un module existant, RLS) ──────────────


def _source_points(
    session: Session, tenant_id: int, jour: date
) -> list[dict[str, Any]]:
    """Points convenus en attente — module points_convenus_cabinet."""
    from backend.plateforme.points_convenus_cabinet import (
        points_convenus_cabinet,
    )

    vue = points_convenus_cabinet(session, tenant_id, jour)
    return alertes_depuis_points(vue.get("items") or [])


def _source_echeances(
    session: Session, tenant_id: int, jour: date
) -> list[dict[str, Any]]:
    """Échéances fiscales de la fenêtre — module echeances_cabinet."""
    from backend.plateforme.echeances_cabinet import echeances_cabinet

    vue = echeances_cabinet(session, tenant_id, jour)
    return alertes_depuis_echeances(vue.get("items") or [])


def _source_budget(
    session: Session, tenant_id: int, jour: date
) -> list[dict[str, Any]]:
    """Budget temps sous tension — module rentabilite_mission."""
    from backend.plateforme.rentabilite_mission import rentabilite_cabinet

    vue = rentabilite_cabinet(session, tenant_id)
    return alertes_depuis_budget(vue.get("items") or [])


def _source_lpf(
    session: Session, tenant_id: int, jour: date
) -> list[dict[str, Any]]:
    """Délais LPF des contrôles fiscaux — agrégat tenant, lecture seule.

    Les événements consignés sur les missions non clôturées du tenant
    (plafonnés à :data:`PLAFOND_EVENEMENTS_LPF`), regroupés par mission
    puis passés à la fonction pure EXISTANTE
    :func:`backend.plateforme.controles_fiscaux.construire_chronologie`
    (aucun recalcul des délais ici). Une mission dont la chronologie
    échoue est simplement omise.
    """
    from backend.plateforme.controles_fiscaux import construire_chronologie
    from backend.plateforme.missions import STATUT_CLOTUREE

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT e.id, e.mission_id, e.type_evenement, "
                "e.date_evenement, e.montant_en_jeu, "
                "c.denomination AS client "
                "FROM evenement_controle_fiscal e "
                "JOIN mission m ON m.id = e.mission_id "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut <> :clos "
                "ORDER BY e.mission_id, e.date_evenement, e.id "
                "LIMIT :lim"
            ),
            {"clos": STATUT_CLOTUREE, "lim": PLAFOND_EVENEMENTS_LPF},
        ).mappings().all()

    par_mission: dict[int, dict[str, Any]] = {}
    for r in rows:
        mid = int(r["mission_id"])
        entree = par_mission.setdefault(
            mid,
            {
                "client": str(r["client"] or ""),
                "mission_id": mid,
                "bruts": [],
            },
        )
        entree["bruts"].append(dict(r))

    chronologies: list[dict[str, Any]] = []
    for entree in par_mission.values():
        # Tolérance par mission : une chronologie illisible n'empêche
        # pas les alertes des autres missions.
        try:
            chronologie = construire_chronologie(entree["bruts"], jour)
        except Exception:  # noqa: BLE001 — mission annexe tolérée
            continue
        chronologies.append(
            {
                "client": entree["client"],
                "mission_id": entree["mission_id"],
                "evenements": chronologie,
            }
        )
    return alertes_depuis_lpf(chronologies)


def _source_completude(
    session: Session, tenant_id: int, jour: date
) -> list[dict[str, Any]]:
    """Complétude déclarative des missions — module completude_declarative.

    Missions non clôturées du tenant (plafonnées à
    :data:`PLAFOND_MISSIONS_COMPLETUDE`) : pour chacune, la vue est
    celle DÉJÀ construite par
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    (aucun recalcul des périodes ici). Une mission disparue entre les
    deux lectures est simplement omise.
    """
    from backend.plateforme.completude_declarative import (
        ErreurCompletudeDeclarativeIntrouvable,
        completude_declarative_mission,
    )
    from backend.plateforme.missions import STATUT_CLOTUREE

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, "
                "c.denomination AS client "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut <> :clos "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"clos": STATUT_CLOTUREE, "lim": PLAFOND_MISSIONS_COMPLETUDE},
        ).mappings().all()

    vues: list[dict[str, Any]] = []
    for r in rows:
        try:
            vue = completude_declarative_mission(
                session, tenant_id, int(r["mission_id"])
            )
        except ErreurCompletudeDeclarativeIntrouvable:
            continue
        vues.append(
            {
                "client": str(r["client"] or ""),
                "mission_id": int(r["mission_id"]),
                "completude": vue,
            }
        )
    return alertes_depuis_completude(vues)


#: Sources agrégées : (nom, constructeur) — chacune est TOLÉRANTE.
_SOURCES: Final[
    tuple[
        tuple[str, Callable[[Session, int, date], list[dict[str, Any]]]],
        ...,
    ]
] = (
    ("points_convenus", _source_points),
    ("echeances_fiscales", _source_echeances),
    ("budget_temps", _source_budget),
    ("delais_lpf", _source_lpf),
    ("completude_declarative", _source_completude),
)


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def centre_alertes_cabinet(
    session: Session, tenant_id: int, aujourd_hui: date | None = None
) -> dict[str, Any]:
    """Centre d'alertes du cabinet — LECTURE SEULE, RLS, jamais bloquant.

    Chaque source est tentée indépendamment (try/except) : une source
    en échec est ignorée et listée dans ``sources_en_echec`` — pattern
    :mod:`backend.plateforme.dossier_mission`. Se construit toujours
    (tenant sans signal → liste vide, clés stables, note présente).
    Aucun email, aucune écriture.
    """
    jour = aujourd_hui or date.today()
    alertes: list[dict[str, Any]] = []
    en_echec: list[str] = []
    for nom, construire in _SOURCES:
        # Tolérance par source : un module en échec n'empêche jamais
        # la restitution du centre d'alertes.
        try:
            alertes.extend(construire(session, tenant_id, jour))
        except Exception:  # noqa: BLE001 — source annexe tolérée
            en_echec.append(nom)
    return assembler_centre(alertes, en_echec, jour)
