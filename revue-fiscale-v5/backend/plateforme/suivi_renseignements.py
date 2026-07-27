"""Suivi de circularisation de la demande de renseignements.

En cabinet, après l'envoi de la « Demande de renseignements et de
documents », il faut suivre les réponses du client : quels items sont
reçus, lesquels restent en attente, lesquels sont à relancer. La liste
des items est RECONSTRUITE à chaque lecture depuis les mêmes sources que
le livrable .docx (``demande_renseignements.collecter_items``) puis
fusionnée (LEFT JOIN logique) avec les statuts saisis dans la table
``suivi_demande_renseignements``. Aucun taux ni seuil fiscal ici.

Passerelle civisme → demande : le fiscaliste peut, d'un clic explicite,
ajouter un item par échéance « manquante » de l'analyse de civisme
fiscal (:func:`ajouter_items_depuis_civisme`). Ces items sont PERSISTÉS
dans ``suivi_demande_renseignements`` (préfixe ``civisme:``) car ils ne
sont pas reconstructibles depuis les sources du .docx.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.demande_renseignements import collecter_items

STATUTS_SUIVI: Final = ("en_attente", "recu", "sans_objet")
STATUT_DEFAUT: Final = "en_attente"

# Préfixe des clés d'items ajoutés depuis l'analyse de civisme fiscal.
PREFIXE_CIVISME: Final = "civisme:"


class ErreurSuiviRenseignements(Exception):
    """Echec du suivi (mission introuvable, statut ou item invalide…)."""


class ErreurSuiviIntrouvable(ErreurSuiviRenseignements):
    """Mission ou item hors périmètre du tenant — 404 côté route."""


class ErreurSuiviMissionCloturee(ErreurSuiviRenseignements):
    """Mission clôturée — écriture refusée (409 côté route)."""


class ErreurSuiviDateInvalide(ErreurSuiviRenseignements):
    """Date de relance invalide (passée…) — 422 côté route."""


class ErreurSuiviItemDejaRecu(ErreurSuiviRenseignements):
    """Item déjà reçu ou sans objet — relance sans objet (409 côté route)."""


def _mission_existe(session: Session, mission_id: int) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        is not None
    )


def _items_civisme_persistes(
    session: Session, mission_id: int
) -> list[dict[str, str]]:
    """Items « civisme » persistés — [{cle_item, libelle}] dans l'ordre d'ajout.

    Contrairement aux items reconstruits (``collecter_items``), les items
    ajoutés depuis l'analyse de civisme n'existent que dans la table de
    suivi. Contexte tenant déjà posé par l'appelant.
    """
    rows = session.execute(
        text(
            "SELECT cle_item, libelle FROM suivi_demande_renseignements "
            "WHERE mission_id = :m AND cle_item LIKE :p ORDER BY id"
        ),
        {"m": mission_id, "p": f"{PREFIXE_CIVISME}%"},
    ).mappings().all()
    return [
        {"cle_item": str(r["cle_item"]), "libelle": str(r["libelle"] or "")}
        for r in rows
    ]


def _statuts_enregistres(
    session: Session, mission_id: int
) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT cle_item, statut, date_relance, derniere_relance_le, "
            "nb_relances, note, maj_le "
            "FROM suivi_demande_renseignements WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).mappings().all()
    return {str(r["cle_item"]): dict(r) for r in rows}


def _fusionner(
    items: list[dict[str, str]], suivis: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Items courants + statuts saisis — défaut ``en_attente`` sans saisie."""
    fusion: list[dict[str, Any]] = []
    for item in items:
        cle = item["cle_item"]
        s = suivis.get(cle)
        fusion.append(
            {
                "cle_item": cle,
                "libelle": item["libelle"],
                "statut": str(s["statut"]) if s else STATUT_DEFAUT,
                "date_relance": (
                    s["date_relance"].isoformat()
                    if s and s.get("date_relance")
                    else None
                ),
                "derniere_relance_le": (
                    s["derniere_relance_le"].isoformat()
                    if s and s.get("derniere_relance_le")
                    else None
                ),
                "nb_relances": int(s.get("nb_relances") or 0) if s else 0,
                "note": (s.get("note") if s else None) or None,
                "maj_le": (
                    s["maj_le"].isoformat() if s and s.get("maj_le") else None
                ),
            }
        )
    return fusion


def lister_items(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    """Liste courante des items demandables fusionnée avec leurs statuts.

    [{cle_item, libelle, statut, date_relance, note, maj_le}] — mêmes
    sources et même ordre que le .docx, suivis des items « civisme »
    persistés (ajout explicite du fiscaliste). RLS via
    ``contexte_tenant`` : mission d'un autre tenant →
    :class:`ErreurSuiviIntrouvable`.
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        items = collecter_items(session, mission_id)
        items += _items_civisme_persistes(session, mission_id)
        suivis = _statuts_enregistres(session, mission_id)
    return _fusionner(items, suivis)


def maj_item(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_item: str,
    statut: str,
    date_relance: date | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """UPSERT du statut d'un item — retourne l'item fusionné à jour.

    Le statut est validé contre :data:`STATUTS_SUIVI` ; la clé doit
    appartenir à la liste courante des items demandables (sinon 404).
    """
    statut = str(statut or "").strip()
    if statut not in STATUTS_SUIVI:
        raise ErreurSuiviRenseignements(
            f"statut invalide « {statut} » — attendus : "
            + ", ".join(STATUTS_SUIVI)
        )
    cle_item = str(cle_item or "").strip()
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        items = collecter_items(session, mission_id)
        items += _items_civisme_persistes(session, mission_id)
        par_cle = {i["cle_item"]: i for i in items}
        if cle_item not in par_cle:
            raise ErreurSuiviIntrouvable(
                f"item « {cle_item} » inconnu pour la mission {mission_id}"
            )
        row = session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance, note) "
                "VALUES (:t, :m, :c, :l, :s, :d, :n) "
                "ON CONFLICT (tenant_id, mission_id, cle_item) DO UPDATE SET "
                "statut = EXCLUDED.statut, "
                "date_relance = EXCLUDED.date_relance, "
                "note = EXCLUDED.note, "
                "libelle = EXCLUDED.libelle, "
                "maj_le = now() "
                "RETURNING cle_item, statut, date_relance, "
                "derniere_relance_le, nb_relances, note, maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_item,
                "l": par_cle[cle_item]["libelle"],
                "s": statut,
                "d": date_relance,
                "n": (note or "").strip() or None,
            },
        ).mappings().one()
    # Pas de commit ici : la transaction (et son SET LOCAL tenant) reste
    # ouverte — get_session committe en fin de requête.
    return _fusionner(
        [par_cle[cle_item]], {cle_item: dict(row)}
    )[0]


def planifier_relances(
    session: Session,
    tenant_id: int,
    mission_id: int,
    date_relance: date,
    *,
    remplacer: bool = False,
) -> dict[str, int]:
    """Planifie en un clic la relance des items encore « en_attente ».

    Fixe ``date_relance`` sur tous les items au statut ``en_attente`` qui
    n'ont pas déjà de date de relance (avec ``remplacer=True`` : tous les
    ``en_attente``, dates existantes écrasées). Les items sans saisie
    préalable sont persistés (UPSERT, statut ``en_attente`` conservé,
    note inchangée). Déclenché par un clic explicite du fiscaliste.
    Mission clôturée → :class:`ErreurSuiviMissionCloturee` (409) ;
    mission hors tenant → :class:`ErreurSuiviIntrouvable` (404) ; date
    passée → :class:`ErreurSuiviDateInvalide` (422).

    Retourne ``{planifiees, deja_planifiees}``.
    """
    if date_relance < date.today():
        raise ErreurSuiviDateInvalide(
            f"date de relance {date_relance.isoformat()} déjà passée — "
            "choisissez une date à partir d'aujourd'hui"
        )
    planifiees = 0
    deja = 0
    with contexte_tenant(session, tenant_id):
        statut_mission = session.execute(
            text("SELECT statut FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if statut_mission is None:
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        if str(statut_mission).lower() == "cloturee":
            raise ErreurSuiviMissionCloturee(
                f"mission {mission_id} clôturée — réouvrez-la avant de "
                "planifier des relances"
            )
        items = collecter_items(session, mission_id)
        items += _items_civisme_persistes(session, mission_id)
        suivis = _statuts_enregistres(session, mission_id)
        for item in items:
            cle = item["cle_item"]
            s = suivis.get(cle)
            statut = str(s["statut"]) if s else STATUT_DEFAUT
            if statut != STATUT_DEFAUT:
                continue
            if s is not None and s.get("date_relance") and not remplacer:
                deja += 1
                continue
            session.execute(
                text(
                    "INSERT INTO suivi_demande_renseignements "
                    "(tenant_id, mission_id, cle_item, libelle, statut, "
                    "date_relance, note) "
                    "VALUES (:t, :m, :c, :l, :s, :d, :n) "
                    "ON CONFLICT (tenant_id, mission_id, cle_item) "
                    "DO UPDATE SET date_relance = EXCLUDED.date_relance, "
                    "maj_le = now()"
                ),
                {
                    "t": tenant_id,
                    "m": mission_id,
                    "c": cle,
                    "l": item["libelle"],
                    "s": STATUT_DEFAUT,
                    "d": date_relance,
                    "n": (s.get("note") if s else None) or None,
                },
            )
            planifiees += 1
    # Pas de commit ici : get_session committe en fin de requête.
    return {"planifiees": planifiees, "deja_planifiees": deja}


def _item_pour_relance(
    session: Session, mission_id: int, cle_item: str
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """(item courant, suivi enregistré ou None) — gardes communes.

    Contexte tenant déjà posé par l'appelant. Mission introuvable →
    :class:`ErreurSuiviIntrouvable` ; mission clôturée →
    :class:`ErreurSuiviMissionCloturee` ; item inconnu → 404 ; item déjà
    ``recu`` ou ``sans_objet`` → :class:`ErreurSuiviItemDejaRecu` (409).
    """
    statut_mission = session.execute(
        text("SELECT statut FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).scalar_one_or_none()
    if statut_mission is None:
        raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
    if str(statut_mission).lower() == "cloturee":
        raise ErreurSuiviMissionCloturee(
            f"mission {mission_id} clôturée — réouvrez-la avant de "
            "gérer les relances"
        )
    items = collecter_items(session, mission_id)
    items += _items_civisme_persistes(session, mission_id)
    par_cle = {i["cle_item"]: i for i in items}
    if cle_item not in par_cle:
        raise ErreurSuiviIntrouvable(
            f"item « {cle_item} » inconnu pour la mission {mission_id}"
        )
    s = _statuts_enregistres(session, mission_id).get(cle_item)
    statut = str(s["statut"]) if s else STATUT_DEFAUT
    if statut != STATUT_DEFAUT:
        raise ErreurSuiviItemDejaRecu(
            f"item « {cle_item} » déjà au statut « {statut} » — "
            "aucune relance à effectuer"
        )
    return par_cle[cle_item], s


def relance_effectuee(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_item: str,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Marque la relance d'un item comme EFFECTUÉE par le fiscaliste.

    Trace ``derniere_relance_le`` (aujourd'hui), incrémente
    ``nb_relances`` et efface ``date_relance`` (plus rien de planifié :
    à re-planifier ou reporter). L'item reste ``en_attente`` — seul le
    client peut le faire passer « reçu ». Mission hors tenant ou item
    inconnu → :class:`ErreurSuiviIntrouvable` (404) ; mission clôturée →
    :class:`ErreurSuiviMissionCloturee` (409) ; item déjà reçu / sans
    objet → :class:`ErreurSuiviItemDejaRecu` (409).

    Retourne l'item fusionné à jour.
    """
    jour = aujourd_hui or date.today()
    cle_item = str(cle_item or "").strip()
    with contexte_tenant(session, tenant_id):
        item, _s = _item_pour_relance(session, mission_id, cle_item)
        row = session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "derniere_relance_le, nb_relances) "
                "VALUES (:t, :m, :c, :l, :s, :j, 1) "
                "ON CONFLICT (tenant_id, mission_id, cle_item) DO UPDATE SET "
                "date_relance = NULL, "
                "derniere_relance_le = EXCLUDED.derniere_relance_le, "
                "nb_relances = suivi_demande_renseignements.nb_relances + 1, "
                "maj_le = now() "
                "RETURNING cle_item, statut, date_relance, "
                "derniere_relance_le, nb_relances, note, maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_item,
                "l": item["libelle"],
                "s": STATUT_DEFAUT,
                "j": jour,
            },
        ).mappings().one()
    # Pas de commit ici : get_session committe en fin de requête.
    return _fusionner([item], {cle_item: dict(row)})[0]


def reporter_relance(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_item: str,
    nouvelle_date: date,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Reporte la relance d'un item à une nouvelle date.

    Nouvelle date passée → :class:`ErreurSuiviDateInvalide` (422) ;
    mission hors tenant ou item inconnu →
    :class:`ErreurSuiviIntrouvable` (404) ; mission clôturée →
    :class:`ErreurSuiviMissionCloturee` (409) ; item déjà reçu / sans
    objet → :class:`ErreurSuiviItemDejaRecu` (409).

    Retourne l'item fusionné à jour.
    """
    jour = aujourd_hui or date.today()
    if nouvelle_date < jour:
        raise ErreurSuiviDateInvalide(
            f"date de relance {nouvelle_date.isoformat()} déjà passée — "
            "choisissez une date à partir d'aujourd'hui"
        )
    cle_item = str(cle_item or "").strip()
    with contexte_tenant(session, tenant_id):
        item, _s = _item_pour_relance(session, mission_id, cle_item)
        row = session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance) "
                "VALUES (:t, :m, :c, :l, :s, :d) "
                "ON CONFLICT (tenant_id, mission_id, cle_item) DO UPDATE SET "
                "date_relance = EXCLUDED.date_relance, "
                "maj_le = now() "
                "RETURNING cle_item, statut, date_relance, "
                "derniere_relance_le, nb_relances, note, maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_item,
                "l": item["libelle"],
                "s": STATUT_DEFAUT,
                "d": nouvelle_date,
            },
        ).mappings().one()
    # Pas de commit ici : get_session committe en fin de requête.
    return _fusionner([item], {cle_item: dict(row)})[0]


def synthese_depuis_items(items: list[dict[str, Any]]) -> dict[str, int]:
    """Compteurs {total, en_attente, recu, sans_objet, a_relancer}."""
    aujourd_hui = date.today().isoformat()
    compte = {"total": len(items), "en_attente": 0, "recu": 0, "sans_objet": 0}
    a_relancer = 0
    for it in items:
        statut = str(it.get("statut") or STATUT_DEFAUT)
        if statut in compte:
            compte[statut] += 1
        relance = it.get("date_relance")
        if statut == STATUT_DEFAUT and relance and str(relance) <= aujourd_hui:
            a_relancer += 1
    compte["a_relancer"] = a_relancer
    return compte


def synthese(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, int]:
    """Synthèse du suivi — recalculée depuis la liste fusionnée."""
    return synthese_depuis_items(lister_items(session, tenant_id, mission_id))


# ── Passerelle civisme fiscal → demande de renseignements ────────────


def _libelle_echeance_manquante(echeance: dict[str, Any]) -> str:
    """Libellé clair d'une échéance manquante — ex. « Déclaration TVA —
    janvier 2025 (échéance 15/02/2025) »."""
    obligation = str(echeance.get("obligation") or "").strip()
    impot = str(echeance.get("impot") or "").strip()
    periode = str(echeance.get("periode") or "").strip()
    date_limite = date.fromisoformat(str(echeance["date_limite"]))
    tete = obligation or impot or "Obligation déclarative"
    corps = f"{tete} — {periode}" if periode else tete
    return f"{corps} (échéance {date_limite.strftime('%d/%m/%Y')})"


def _cle_civisme(echeance: dict[str, Any]) -> str:
    """Clé stable d'un item civisme : civisme:{impot}|{periode}|{date}."""
    return (
        f"{PREFIXE_CIVISME}{echeance.get('impot')}"
        f"|{echeance.get('periode')}|{echeance.get('date_limite')}"
    )


def ajouter_items_depuis_civisme(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, int]:
    """Ajoute un item de demande par échéance « manquante » du civisme.

    Déclenché par un clic explicite du fiscaliste. IDEMPOTENT : une
    échéance dont le libellé figure déjà dans la liste courante des
    items (reconstruits ou persistés) est ignorée — le second appel ne
    crée aucun doublon. Mission clôturée →
    :class:`ErreurSuiviMissionCloturee` (409) ; mission hors tenant →
    :class:`ErreurSuiviIntrouvable` (404).

    Retourne ``{crees, ignores_existants, total_manquantes}``.
    """
    from backend.plateforme.civisme_fiscal import (
        STATUT_MANQUANTE,
        ErreurCivismeIntrouvable,
        analyse_mission,
    )

    # analyse_mission ouvre son propre contexte_tenant : appel HORS de
    # tout autre with contexte_tenant.
    try:
        analyse = analyse_mission(
            session, tenant_id, mission_id, aujourd_hui=aujourd_hui
        )
    except ErreurCivismeIntrouvable as e:
        raise ErreurSuiviIntrouvable(str(e)) from e

    manquantes = [
        e
        for e in analyse["rapprochement"]
        if e.get("statut") == STATUT_MANQUANTE
    ]

    crees = 0
    ignores = 0
    with contexte_tenant(session, tenant_id):
        statut_mission = session.execute(
            text("SELECT statut FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if statut_mission is None:
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        if str(statut_mission).lower() == "cloturee":
            raise ErreurSuiviMissionCloturee(
                f"mission {mission_id} clôturée — réouvrez-la avant "
                "d'ajouter des items à la demande de renseignements"
            )

        libelles_existants = {
            i["libelle"]
            for i in collecter_items(session, mission_id)
        } | {
            i["libelle"]
            for i in _items_civisme_persistes(session, mission_id)
        }
        for echeance in manquantes:
            libelle = _libelle_echeance_manquante(echeance)
            if libelle in libelles_existants:
                ignores += 1
                continue
            # ON CONFLICT DO NOTHING : ceinture et bretelles sur la clé
            # unique (tenant_id, mission_id, cle_item).
            insere = session.execute(
                text(
                    "INSERT INTO suivi_demande_renseignements "
                    "(tenant_id, mission_id, cle_item, libelle, statut) "
                    "VALUES (:t, :m, :c, :l, :s) "
                    "ON CONFLICT (tenant_id, mission_id, cle_item) "
                    "DO NOTHING RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "m": mission_id,
                    "c": _cle_civisme(echeance),
                    "l": libelle,
                    "s": STATUT_DEFAUT,
                },
            ).scalar_one_or_none()
            if insere is None:
                ignores += 1
            else:
                crees += 1
                libelles_existants.add(libelle)
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "crees": crees,
        "ignores_existants": ignores,
        "total_manquantes": len(manquantes),
    }
