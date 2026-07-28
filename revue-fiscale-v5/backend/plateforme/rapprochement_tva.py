"""Rapprochement TVA — déclaré (DGI) / comptabilisé (balance).

POURQUOI : le premier réflexe du réviseur TVA est de rapprocher la TVA
portée sur les déclarations déposées (collectée et déductible) de la
TVA enregistrée en comptabilité — comptes SYSCOHADA 443x « État, TVA
facturée » (collectée, solde créditeur), 445x « État, TVA récupérable »
(déductible, solde débiteur) et 444x « État, TVA due ou crédit de
TVA » (position nette, informatif). Un écart au-delà du seuil de
signification appelle une explication (déclaration omise, TVA facturée
non déclarée, déductions non reprises…).

DONNÉES : aucune table ne stockait la TVA déclarée — la migration
``048_declaration_tva.sql`` crée ``declaration_tva`` (une ligne par
période mensuelle AAAA-MM, saisie par le fiscaliste depuis les
déclarations du client). La TVA comptabilisée est lue dans
``solde_compte`` (balance importée par la source active).

LIMITE ASSUMÉE : la balance est ANNUELLE (un solde par compte, sans
mensualisation) — le rapprochement chiffre donc les écarts PAR NATURE
(collectée, déductible, nette) en CUMUL sur l'exercice ; le détail
déclaré par période est restitué pour lecture, sans rapprochement mois
par mois. Les soldes 443x/445x incluent d'éventuels reports d'ouverture
que seul l'œil humain sait neutraliser.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — les
écarts éclairent, l'humain décide. Fonctions pures testables sans base
+ accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.revue_analytique`). Montants sérialisés en
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

# Préfixes SYSCOHADA des comptes de TVA lus dans la balance.
PREFIXE_TVA_COLLECTEE: Final = "443"    # État, TVA facturée (créditeur)
PREFIXE_TVA_NETTE: Final = "444"        # État, TVA due / crédit de TVA
PREFIXE_TVA_DEDUCTIBLE: Final = "445"   # État, TVA récupérable (débiteur)

# Seuil de signification par défaut : un écart cumulé annuel au-delà de
# 100 000 FCFA (en valeur absolue) est signalé « significatif ».
SEUIL_SIGNIFICATION_FCFA: Final = Decimal("100000")

NATURE_COLLECTEE: Final = "tva_collectee"
NATURE_DEDUCTIBLE: Final = "tva_deductible"
NATURE_NETTE: Final = "tva_nette"

LIBELLES_NATURE: Final[dict[str, str]] = {
    NATURE_COLLECTEE: "TVA collectée (déclarée vs comptes 443x)",
    NATURE_DEDUCTIBLE: "TVA déductible (déclarée vs comptes 445x)",
    NATURE_NETTE: "TVA nette (collectée - déductible)",
}

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_COHERENT: Final = "coherent"
STATUT_ECARTS: Final = "ecarts_a_expliquer"

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_RAPPROCHEMENT_TVA: Final = (
    "Rapprochement consultatif de la TVA déclarée (saisie depuis les "
    "déclarations du client) et de la TVA comptabilisée (comptes 443x "
    "collectée et 445x déductible de la balance annuelle). Un écart "
    "au-delà du seuil de signification appelle une explication "
    "(déclaration omise, TVA facturée non déclarée, déductions non "
    "reprises, reports d'ouverture…) — l'humain apprécie et décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_SAISIE_DECLARATION: Final = "saisie_declaration_tva"
ACTION_CONSULTATION: Final = "consultation_rapprochement_tva"


class ErreurRapprochementTva(Exception):
    """Échec du rapprochement TVA."""


class ErreurRapprochementTvaIntrouvable(ErreurRapprochementTva):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurRapprochementTvaInvalide(ErreurRapprochementTva):
    """Saisie invalide (période, montant) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_periode(periode: object) -> str:
    """PUR — valide une période mensuelle « AAAA-MM ».

    Invalide → :class:`ErreurRapprochementTvaInvalide` (422 côté route).
    """
    texte_periode = str(periode or "").strip()
    parties = texte_periode.split("-")
    if len(parties) != 2 or [len(p) for p in parties] != [4, 2]:
        raise ErreurRapprochementTvaInvalide(
            f"période invalide « {texte_periode} » — format attendu : "
            "AAAA-MM"
        )
    try:
        annee, mois = int(parties[0]), int(parties[1])
    except ValueError as e:
        raise ErreurRapprochementTvaInvalide(
            f"période invalide « {texte_periode} » — format attendu : "
            "AAAA-MM"
        ) from e
    if not 1 <= mois <= 12 or annee < 1900:
        raise ErreurRapprochementTvaInvalide(
            f"période invalide « {texte_periode} » — mois attendu entre "
            "01 et 12"
        )
    return texte_periode


def valider_montant(montant: object, champ: str) -> Decimal:
    """PUR — montant FCFA ≥ 0 arrondi au centime (Decimal).

    ``None``/vide → 0. Illisible ou négatif →
    :class:`ErreurRapprochementTvaInvalide` (422 côté route).
    """
    if montant is None or str(montant).strip() == "":
        return Decimal("0.00")
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurRapprochementTvaInvalide(
            f"montant illisible pour « {champ} » : {montant!r}"
        ) from e
    if valeur < 0:
        raise ErreurRapprochementTvaInvalide(
            f"montant négatif interdit pour « {champ} » : {valeur}"
        )
    return valeur.quantize(Decimal("0.01"))


def extraire_tva_balance(soldes: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — TVA comptabilisée depuis les soldes de balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``tva_collectee`` : soldes créditeurs nets des comptes 443x ;
    - ``tva_deductible`` : soldes débiteurs nets des comptes 445x ;
    - ``tva_nette`` : collectée - déductible (comparable au déclaré) ;
    - ``solde_tva_due_ou_credit`` : solde créditeur net des comptes
      444x (TVA due / crédit de TVA — informatif, dépend des
      règlements) ;
    - ``comptes`` : détail par compte TVA (nature, solde signé).
    """
    collectee = Decimal("0")
    deductible = Decimal("0")
    solde_444 = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        if compte.startswith(PREFIXE_TVA_COLLECTEE):
            nature = NATURE_COLLECTEE
            solde = credit - debit
            collectee += solde
        elif compte.startswith(PREFIXE_TVA_DEDUCTIBLE):
            nature = NATURE_DEDUCTIBLE
            solde = debit - credit
            deductible += solde
        elif compte.startswith(PREFIXE_TVA_NETTE):
            nature = NATURE_NETTE
            solde = credit - debit
            solde_444 += solde
        else:
            continue
        comptes.append(
            {
                "compte": compte,
                "libelle": str(ligne.get("libelle") or ""),
                "nature": nature,
                "solde": solde,
            }
        )
    return {
        "tva_collectee": collectee,
        "tva_deductible": deductible,
        "tva_nette": collectee - deductible,
        "solde_tva_due_ou_credit": solde_444,
        "comptes": comptes,
    }


def totaliser_declarations(
    declarations: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """PUR — totaux déclarés (collectée, déductible, nette) en Decimal."""
    collectee = Decimal("0")
    deductible = Decimal("0")
    for d in declarations:
        collectee += Decimal(str(d.get("tva_collectee") or 0))
        deductible += Decimal(str(d.get("tva_deductible") or 0))
    return {
        "tva_collectee": collectee,
        "tva_deductible": deductible,
        "tva_nette": collectee - deductible,
    }


def rapprocher_tva(
    declarations: list[dict[str, Any]],
    soldes: list[dict[str, Any]],
    seuil: Decimal = SEUIL_SIGNIFICATION_FCFA,
) -> dict[str, Any]:
    """PUR — rapproche TVA déclarée et TVA comptabilisée.

    ``declarations`` : lignes ``{periode, tva_collectee,
    tva_deductible}`` ; ``soldes`` : lignes de balance ``{compte,
    libelle, debit, credit}``. Montants restitués en ``str`` (Decimal).
    Clés TOUJOURS présentes ; ``disponible`` est vrai seulement si au
    moins une déclaration ET au moins un compte TVA en balance
    existent — les écarts ne se chiffrent que sur données complètes.
    Écart = déclaré - comptabilisé ; « significatif » si sa valeur
    absolue dépasse strictement ``seuil``.
    """
    compta = extraire_tva_balance(soldes)
    totaux = totaliser_declarations(declarations)

    lignes_declarations = [
        {
            "periode": str(d.get("periode") or ""),
            "tva_collectee": str(
                Decimal(str(d.get("tva_collectee") or 0))
            ),
            "tva_deductible": str(
                Decimal(str(d.get("tva_deductible") or 0))
            ),
            "tva_nette": str(
                Decimal(str(d.get("tva_collectee") or 0))
                - Decimal(str(d.get("tva_deductible") or 0))
            ),
        }
        for d in sorted(
            declarations, key=lambda d: str(d.get("periode") or "")
        )
    ]

    disponible = bool(declarations) and bool(compta["comptes"])

    ecarts: list[dict[str, Any]] = []
    nb_significatifs = 0
    for nature in (NATURE_COLLECTEE, NATURE_DEDUCTIBLE, NATURE_NETTE):
        declare = totaux[nature]
        comptabilise = compta[nature]
        ecart = declare - comptabilise
        significatif = disponible and abs(ecart) > seuil
        if significatif:
            nb_significatifs += 1
        ecarts.append(
            {
                "nature": nature,
                "libelle": LIBELLES_NATURE[nature],
                "declare": str(declare),
                "comptabilise": str(comptabilise),
                "ecart": str(ecart),
                "significatif": significatif,
            }
        )

    if not disponible:
        statut = STATUT_INDISPONIBLE
    elif nb_significatifs:
        statut = STATUT_ECARTS
    else:
        statut = STATUT_COHERENT

    return {
        "disponible": disponible,
        "seuil_signification": str(seuil),
        "declarations": lignes_declarations,
        "totaux_declares": {
            k: str(v) for k, v in totaux.items()
        },
        "comptabilise": {
            "tva_collectee": str(compta["tva_collectee"]),
            "tva_deductible": str(compta["tva_deductible"]),
            "tva_nette": str(compta["tva_nette"]),
            "solde_tva_due_ou_credit": str(
                compta["solde_tva_due_ou_credit"]
            ),
            "comptes": [
                {
                    "compte": c["compte"],
                    "libelle": c["libelle"],
                    "nature": c["nature"],
                    "solde": str(c["solde"]),
                }
                for c in compta["comptes"]
            ],
        },
        "ecarts": ecarts,
        "synthese": {
            "statut": statut,
            "nb_periodes_declarees": len(lignes_declarations),
            "nb_comptes_tva_balance": len(compta["comptes"]),
            "nb_ecarts_significatifs": nb_significatifs,
        },
        "note": NOTE_RAPPROCHEMENT_TVA,
    }


def _serialiser_declaration(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB ``declaration_tva`` → charge JSON (montants str)."""
    cree = row.get("cree_le")
    maj = row.get("mis_a_jour_le")
    return {
        "id": int(row["id"]),
        "periode": str(row.get("periode") or ""),
        "tva_collectee": str(
            Decimal(str(row.get("tva_collectee") or 0))
        ),
        "tva_deductible": str(
            Decimal(str(row.get("tva_deductible") or 0))
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
        raise ErreurRapprochementTvaIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def saisir_declaration_tva(
    session: Session,
    tenant_id: int,
    mission_id: int,
    periode: object,
    tva_collectee: object,
    tva_deductible: object,
    acteur: str,
) -> dict[str, Any]:
    """Saisit (ou corrige) la TVA déclarée d'une période — clic humain.

    Upsert sur ``(mission_id, periode)`` : re-saisir une période déjà
    connue REMPLACE ses montants (correction humaine, pas d'addition).
    Période ou montant invalides →
    :class:`ErreurRapprochementTvaInvalide` (422) ; mission hors tenant
    → :class:`ErreurRapprochementTvaIntrouvable` (404). Journalise
    :data:`ACTION_SAISIE_DECLARATION`. Retourne la déclaration
    enregistrée (montants ``str``) + note consultative.
    """
    from backend.moteur.journal import append_journal

    periode_ok = valider_periode(periode)
    collectee = valider_montant(tva_collectee, "tva_collectee")
    deductible = valider_montant(tva_deductible, "tva_deductible")
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "INSERT INTO declaration_tva (tenant_id, mission_id, "
                "periode, tva_collectee, tva_deductible) "
                "VALUES (:t, :m, :p, :c, :d) "
                "ON CONFLICT (mission_id, periode) DO UPDATE SET "
                "tva_collectee = EXCLUDED.tva_collectee, "
                "tva_deductible = EXCLUDED.tva_deductible, "
                "mis_a_jour_le = now() "
                "RETURNING id, periode, tva_collectee, tva_deductible, "
                "cree_le, mis_a_jour_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "p": periode_ok,
                "c": collectee,
                "d": deductible,
            },
        ).mappings().one()
        declaration = _serialiser_declaration(dict(row))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_SAISIE_DECLARATION,
            charge_utile={
                "periode": periode_ok,
                "tva_collectee": str(collectee),
                "tva_deductible": str(deductible),
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "declaration": declaration,
        "note": NOTE_RAPPROCHEMENT_TVA,
    }


def _declarations_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, periode, tva_collectee, tva_deductible, "
            "cree_le, mis_a_jour_le "
            "FROM declaration_tva WHERE mission_id = :m ORDER BY periode"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _soldes_tva_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND (compte LIKE :p443 OR compte LIKE :p444 "
            "OR compte LIKE :p445) ORDER BY compte"
        ),
        {
            "m": mission_id,
            "p443": PREFIXE_TVA_COLLECTEE + "%",
            "p444": PREFIXE_TVA_NETTE + "%",
            "p445": PREFIXE_TVA_DEDUCTIBLE + "%",
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def rapprochement_tva_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement TVA de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurRapprochementTvaIntrouvable`
    (404 côté route). Se construit toujours : sans déclaration saisie
    ou sans compte TVA en balance, ``disponible=false`` et
    ``synthese.statut="indisponible"`` — les clés restent présentes.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        declarations = _declarations_mission(session, mission_id)
        soldes = _soldes_tva_mission(session, mission_id)

    vue = rapprocher_tva(declarations, soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
