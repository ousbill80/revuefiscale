"""Suivi des acomptes IS et position de solde — versé / dû estimé.

POURQUOI : en fin d'exercice, le fiscaliste ivoirien projette la
position d'impôt sur les bénéfices de la mission : total des acomptes
IS versés dans l'exercice, retenues à la source subies et crédits
d'impôt reportés de l'exercice précédent, rapprochés de l'IS dû estimé.
Le solde résiduel (à payer ou crédit d'impôt à reporter) éclaire la
trésorerie de la déclaration de résultat et la position à porter sur
l'état de liquidation.

DONNÉES : aucune table ne stockait les acomptes versés — la migration
``051_acompte_impot.sql`` crée ``acompte_impot`` (une ligne par
versement : nature, date, montant, référence de quittance facultative,
saisie par le fiscaliste depuis les quittances du client) et
``is_du_estime_mission`` (IS dû estimé, une valeur par mission). Le
moteur n'expose PAS d'IS estimé (aucun calcul d'impôt sur les sociétés
dans ``backend/moteur``) : le dû est SAISI par le fiscaliste. Les
comptes 441x « État, impôt sur les bénéfices » et 444x « État,
autres impôts et taxes » de la balance (``solde_compte``) sont
restitués à titre INFORMATIF.

LIMITE ASSUMÉE : l'IS dû estimé est une saisie humaine (calcul de
liquidation hors périmètre du moteur) ; les soldes 441x/444x de la
balance annuelle mêlent acomptes, liquidations antérieures et autres
impôts que seul l'œil humain sait ventiler — aucune écriture n'est
proposée.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — la
position projetée éclaire, l'humain décide. Fonctions pures testables
sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.rapprochement_tva`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

NATURE_ACOMPTE_IS: Final = "acompte_is"
NATURE_RETENUE_SOURCE: Final = "retenue_source"
NATURE_CREDIT_REPORTE: Final = "credit_reporte"

# Saisie spéciale : l'IS dû estimé de l'exercice (une valeur par
# mission, remplacée à chaque re-saisie — le moteur ne l'expose pas).
NATURE_IS_DU_ESTIME: Final = "is_du_estime"

NATURES_VERSEMENT: Final = (
    NATURE_ACOMPTE_IS,
    NATURE_RETENUE_SOURCE,
    NATURE_CREDIT_REPORTE,
)

LIBELLES_NATURE: Final[dict[str, str]] = {
    NATURE_ACOMPTE_IS: "Acomptes IS versés",
    NATURE_RETENUE_SOURCE: "Retenues à la source subies",
    NATURE_CREDIT_REPORTE: "Crédits d'impôt reportés",
}

# Préfixes SYSCOHADA des comptes d'impôt lus dans la balance —
# INFORMATIF (441 État, impôt sur les bénéfices ; 444 État, autres
# impôts et taxes).
PREFIXE_IMPOT_BENEFICES: Final = "441"
PREFIXE_AUTRES_IMPOTS: Final = "444"

# Seuil de signification : un solde résiduel projeté au-delà de
# 100 000 FCFA (valeur absolue) est signalé « important ».
SEUIL_SOLDE_RESIDUEL_FCFA: Final = Decimal("100000")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_SOLDE_A_PAYER: Final = "solde_a_payer"
STATUT_CREDIT_A_REPORTER: Final = "credit_a_reporter"
STATUT_EQUILIBRE: Final = "equilibre"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Position indisponible — saisissez l'IS dû estimé de l'exercice"
    ),
    STATUT_SOLDE_A_PAYER: "Solde d'IS à payer",
    STATUT_CREDIT_A_REPORTER: "Crédit d'impôt à reporter",
    STATUT_EQUILIBRE: "Position équilibrée",
}

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_ACOMPTES_IS: Final = (
    "Suivi consultatif des acomptes d'impôt versés (acomptes IS, "
    "retenues à la source, crédits reportés — saisis depuis les "
    "quittances du client) rapprochés de l'IS dû estimé saisi par le "
    "fiscaliste (le moteur n'expose pas d'IS estimé). La position "
    "projetée (solde à payer ou crédit d'impôt à reporter) et les "
    "soldes 441x/444x de la balance sont restitués à titre "
    "informatif — l'humain liquide, apprécie et décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_SAISIE_ACOMPTE: Final = "saisie_acompte_impot"
ACTION_SAISIE_IS_DU: Final = "saisie_is_du_estime"
ACTION_CONSULTATION: Final = "consultation_acomptes_is"


class ErreurAcomptes(Exception):
    """Échec du suivi des acomptes IS."""


class ErreurAcomptesIntrouvable(ErreurAcomptes):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurAcomptesInvalide(ErreurAcomptes):
    """Saisie invalide (nature, date, montant) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_nature(nature: object) -> str:
    """PUR — nature de saisie (versement ou IS dû estimé).

    Invalide → :class:`ErreurAcomptesInvalide` (422 côté route).
    """
    texte_nature = str(nature or "").strip()
    if texte_nature not in (*NATURES_VERSEMENT, NATURE_IS_DU_ESTIME):
        attendues = ", ".join((*NATURES_VERSEMENT, NATURE_IS_DU_ESTIME))
        raise ErreurAcomptesInvalide(
            f"nature invalide « {texte_nature} » — natures attendues : "
            f"{attendues}"
        )
    return texte_nature


def valider_date_versement(valeur: object) -> date:
    """PUR — date de versement « AAAA-MM-JJ ».

    Invalide → :class:`ErreurAcomptesInvalide` (422 côté route).
    """
    if isinstance(valeur, date):
        return valeur
    texte_date = str(valeur or "").strip()
    try:
        return date.fromisoformat(texte_date)
    except ValueError as e:
        raise ErreurAcomptesInvalide(
            f"date de versement invalide « {texte_date} » — format "
            "attendu : AAAA-MM-JJ"
        ) from e


def valider_montant(montant: object, champ: str) -> Decimal:
    """PUR — montant FCFA ≥ 0 arrondi au centime (Decimal).

    ``None``/vide → 0. Illisible ou négatif →
    :class:`ErreurAcomptesInvalide` (422 côté route).
    """
    if montant is None or str(montant).strip() == "":
        return Decimal("0.00")
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurAcomptesInvalide(
            f"montant illisible pour « {champ} » : {montant!r}"
        ) from e
    if valeur < 0:
        raise ErreurAcomptesInvalide(
            f"montant négatif interdit pour « {champ} » : {valeur}"
        )
    return valeur.quantize(Decimal("0.01"))


def totaliser_acomptes(
    acomptes: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """PUR — total versé par nature + total général (Decimal).

    Clés TOUJOURS présentes pour les trois natures + ``total``.
    """
    totaux = {nature: Decimal("0") for nature in NATURES_VERSEMENT}
    for a in acomptes:
        nature = str(a.get("nature") or "")
        if nature in totaux:
            totaux[nature] += Decimal(str(a.get("montant") or 0))
    totaux["total"] = sum(
        (totaux[n] for n in NATURES_VERSEMENT), Decimal("0")
    )
    return totaux


def extraire_soldes_impot_balance(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — comptes d'impôt 441x/444x de la balance (informatif).

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal`, les
    soldes créditeurs nets ``solde_441x`` (État, impôt sur les
    bénéfices) et ``solde_444x`` (État, autres impôts et taxes) +
    ``comptes`` (détail par compte, solde signé créditeur net).
    """
    solde_441 = Decimal("0")
    solde_444 = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        solde = credit - debit
        if compte.startswith(PREFIXE_IMPOT_BENEFICES):
            prefixe = PREFIXE_IMPOT_BENEFICES
            solde_441 += solde
        elif compte.startswith(PREFIXE_AUTRES_IMPOTS):
            prefixe = PREFIXE_AUTRES_IMPOTS
            solde_444 += solde
        else:
            continue
        comptes.append(
            {
                "compte": compte,
                "libelle": str(ligne.get("libelle") or ""),
                "prefixe": prefixe,
                "solde": solde,
            }
        )
    return {
        "solde_441x": solde_441,
        "solde_444x": solde_444,
        "comptes": comptes,
    }


def calculer_position_is(
    acomptes: list[dict[str, Any]],
    is_du_estime: Decimal | None,
    soldes: list[dict[str, Any]],
    seuil: Decimal = SEUIL_SOLDE_RESIDUEL_FCFA,
) -> dict[str, Any]:
    """PUR — position de solde IS projetée de l'exercice.

    ``acomptes`` : lignes ``{nature, date_versement, montant,
    reference_quittance}`` ; ``is_du_estime`` : IS dû estimé saisi par
    le fiscaliste (``None`` si non saisi) ; ``soldes`` : lignes de
    balance (informatif). Montants restitués en ``str`` (Decimal).
    Clés TOUJOURS présentes ; ``disponible`` est vrai seulement si
    l'IS dû estimé est saisi — sans dû, la position ne se projette
    pas (les totaux versés restent chiffrés).
    Position = IS dû estimé - total versé : positive → solde à payer ;
    négative → crédit d'impôt à reporter ; « importante » si sa valeur
    absolue dépasse strictement ``seuil``.
    """
    totaux = totaliser_acomptes(acomptes)
    compta = extraire_soldes_impot_balance(soldes)

    lignes_acomptes = [
        {
            "id": int(a["id"]) if a.get("id") is not None else None,
            "nature": str(a.get("nature") or ""),
            "libelle_nature": LIBELLES_NATURE.get(
                str(a.get("nature") or ""), str(a.get("nature") or "")
            ),
            "date_versement": str(a.get("date_versement") or ""),
            "montant": str(Decimal(str(a.get("montant") or 0))),
            "reference_quittance": (
                str(a["reference_quittance"])
                if a.get("reference_quittance")
                else None
            ),
        }
        for a in sorted(
            acomptes,
            key=lambda a: (
                str(a.get("date_versement") or ""),
                str(a.get("nature") or ""),
            ),
        )
    ]

    disponible = is_du_estime is not None
    if disponible:
        position = Decimal(str(is_du_estime)) - totaux["total"]
        if position > 0:
            statut = STATUT_SOLDE_A_PAYER
        elif position < 0:
            statut = STATUT_CREDIT_A_REPORTER
        else:
            statut = STATUT_EQUILIBRE
        solde_important = abs(position) > seuil
    else:
        position = Decimal("0")
        statut = STATUT_INDISPONIBLE
        solde_important = False

    return {
        "disponible": disponible,
        "seuil_solde_residuel": str(seuil),
        "acomptes": lignes_acomptes,
        "totaux_verses": {
            nature: str(totaux[nature]) for nature in NATURES_VERSEMENT
        }
        | {"total": str(totaux["total"])},
        "is_du_estime": (
            str(Decimal(str(is_du_estime))) if disponible else None
        ),
        "is_du_source": "saisie_fiscaliste",
        "position": {
            "statut": statut,
            "libelle": LIBELLES_STATUT[statut],
            "montant": str(abs(position)),
            "solde_signe": str(position),
            "solde_important": solde_important,
        },
        "balance": {
            "solde_441x": str(compta["solde_441x"]),
            "solde_444x": str(compta["solde_444x"]),
            "comptes": [
                {
                    "compte": c["compte"],
                    "libelle": c["libelle"],
                    "prefixe": c["prefixe"],
                    "solde": str(c["solde"]),
                }
                for c in compta["comptes"]
            ],
        },
        "synthese": {
            "statut": statut,
            "nb_versements": len(lignes_acomptes),
            "nb_comptes_impot_balance": len(compta["comptes"]),
            "solde_important": solde_important,
        },
        "note": NOTE_ACOMPTES_IS,
    }


def _serialiser_acompte(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB ``acompte_impot`` → charge JSON (montants str)."""
    d = row.get("date_versement")
    cree = row.get("cree_le")
    maj = row.get("mis_a_jour_le")
    return {
        "id": int(row["id"]),
        "nature": str(row.get("nature") or ""),
        "libelle_nature": LIBELLES_NATURE.get(
            str(row.get("nature") or ""), str(row.get("nature") or "")
        ),
        "date_versement": (
            d.isoformat() if isinstance(d, date) else str(d or "")
        ),
        "montant": str(Decimal(str(row.get("montant") or 0))),
        "reference_quittance": (
            str(row["reference_quittance"])
            if row.get("reference_quittance")
            else None
        ),
        "cree_le": (
            cree.isoformat() if isinstance(cree, datetime) else None
        ),
        "mis_a_jour_le": (
            maj.isoformat() if isinstance(maj, datetime) else None
        ),
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurAcomptesIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def saisir_acompte(
    session: Session,
    tenant_id: int,
    mission_id: int,
    nature: object,
    montant: object,
    acteur: str,
    date_versement: object = None,
    reference_quittance: object = None,
) -> dict[str, Any]:
    """Saisit (ou corrige) un versement OU l'IS dû estimé — clic humain.

    ``nature`` versement (``acompte_is``, ``retenue_source``,
    ``credit_reporte``) : upsert sur ``(mission_id, nature,
    date_versement)`` — re-saisir une même nature à la même date
    REMPLACE le montant et la référence (correction humaine, pas
    d'addition) ; la date est requise, la référence de quittance
    facultative. ``nature`` = ``is_du_estime`` : remplace l'IS dû
    estimé de la mission (une valeur, la date est ignorée).
    Saisie invalide → :class:`ErreurAcomptesInvalide` (422) ; mission
    hors tenant → :class:`ErreurAcomptesIntrouvable` (404).
    Journalise :data:`ACTION_SAISIE_ACOMPTE` ou
    :data:`ACTION_SAISIE_IS_DU`. Retourne la saisie enregistrée
    (montants ``str``) + note consultative.
    """
    from backend.moteur.journal import append_journal

    nature_ok = valider_nature(nature)
    montant_ok = valider_montant(montant, "montant")

    if nature_ok == NATURE_IS_DU_ESTIME:
        with contexte_tenant(session, tenant_id):
            _mission_ou_404(session, mission_id)
            row = session.execute(
                text(
                    "INSERT INTO is_du_estime_mission (tenant_id, "
                    "mission_id, montant) VALUES (:t, :m, :mt) "
                    "ON CONFLICT (mission_id) DO UPDATE SET "
                    "montant = EXCLUDED.montant, mis_a_jour_le = now() "
                    "RETURNING id, montant, cree_le, mis_a_jour_le"
                ),
                {"t": tenant_id, "m": mission_id, "mt": montant_ok},
            ).mappings().one()
            append_journal(
                session,
                tenant_id=tenant_id,
                mission_id=mission_id,
                acteur=acteur,
                action=ACTION_SAISIE_IS_DU,
                charge_utile={"is_du_estime": str(montant_ok)},
            )
        # Pas de commit ici : get_session committe en fin de requête.
        return {
            "mission_id": mission_id,
            "is_du_estime": str(
                Decimal(str(row["montant"]))
            ),
            "note": NOTE_ACOMPTES_IS,
        }

    date_ok = valider_date_versement(date_versement)
    reference = str(reference_quittance or "").strip() or None
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "INSERT INTO acompte_impot (tenant_id, mission_id, "
                "nature, date_versement, montant, reference_quittance) "
                "VALUES (:t, :m, :n, :d, :mt, :r) "
                "ON CONFLICT (mission_id, nature, date_versement) "
                "DO UPDATE SET montant = EXCLUDED.montant, "
                "reference_quittance = EXCLUDED.reference_quittance, "
                "mis_a_jour_le = now() "
                "RETURNING id, nature, date_versement, montant, "
                "reference_quittance, cree_le, mis_a_jour_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "n": nature_ok,
                "d": date_ok,
                "mt": montant_ok,
                "r": reference,
            },
        ).mappings().one()
        acompte = _serialiser_acompte(dict(row))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_SAISIE_ACOMPTE,
            charge_utile={
                "nature": nature_ok,
                "date_versement": date_ok.isoformat(),
                "montant": str(montant_ok),
                "reference_quittance": reference,
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "acompte": acompte,
        "note": NOTE_ACOMPTES_IS,
    }


def _acomptes_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, nature, date_versement, montant, "
            "reference_quittance, cree_le, mis_a_jour_le "
            "FROM acompte_impot WHERE mission_id = :m "
            "ORDER BY date_versement, nature"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _is_du_estime_mission(
    session: Session, mission_id: int
) -> Decimal | None:
    montant = session.execute(
        text(
            "SELECT montant FROM is_du_estime_mission "
            "WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()
    return None if montant is None else Decimal(str(montant))


def _soldes_impot_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND (compte LIKE :p441 OR compte LIKE :p444) "
            "ORDER BY compte"
        ),
        {
            "m": mission_id,
            "p441": PREFIXE_IMPOT_BENEFICES + "%",
            "p444": PREFIXE_AUTRES_IMPOTS + "%",
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_acomptes_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Vue complète des acomptes IS de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurAcomptesIntrouvable` (404 côté
    route). Se construit toujours : sans IS dû estimé saisi,
    ``disponible=false`` et ``synthese.statut="indisponible"`` — les
    totaux versés restent chiffrés et les clés présentes.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        acomptes = [
            _serialiser_acompte(a)
            for a in _acomptes_mission(session, mission_id)
        ]
        is_du = _is_du_estime_mission(session, mission_id)
        soldes = _soldes_impot_mission(session, mission_id)

    vue = calculer_position_is(acomptes, is_du, soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
