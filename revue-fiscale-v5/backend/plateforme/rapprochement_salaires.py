"""Rapprochement des impôts sur salaires — déclaré (DGI) / comptabilisé.

POURQUOI : le réviseur des impôts sur salaires rapproche la masse
salariale portée sur les déclarations de salaires déposées (masse
salariale brute, ITS retenu — part salariale —, contribution
employeur) de la masse salariale enregistrée en comptabilité —
comptes SYSCOHADA 66x « Charges de personnel » (soldes débiteurs
nets). Une masse comptable SUPÉRIEURE au déclaré peut révéler des
salaires non déclarés (avantages en nature omis, personnel occasionnel,
gratifications hors bulletin…) — signal consultatif, jamais une
conclusion. Les comptes 447x « État, impôts retenus à la source »
et 42x « Personnel » sont restitués à titre informatif.

DONNÉES : aucune table ne stockait les déclarations de salaires — la
migration ``052_declaration_salaires.sql`` crée
``declaration_salaires`` (une ligne par période mensuelle AAAA-MM,
saisie par le fiscaliste depuis les déclarations du client). La masse
salariale comptabilisée est lue dans ``solde_compte`` (balance
importée par la source active).

LIMITE ASSUMÉE (même que la TVA) : la balance est ANNUELLE (un solde
par compte, sans mensualisation) — le rapprochement chiffre donc
l'écart en CUMUL sur l'exercice ; le détail déclaré par période est
restitué pour lecture, sans rapprochement mois par mois.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — les
écarts éclairent, l'humain décide. Fonctions pures testables sans base
+ accès RLS via ``contexte_tenant`` (pattern
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

# Préfixes SYSCOHADA lus dans la balance.
PREFIXE_CHARGES_PERSONNEL: Final = "66"  # Charges de personnel (débiteur)
PREFIXE_ETAT_RETENUES: Final = "447"     # État, impôts retenus à la source
PREFIXE_PERSONNEL: Final = "42"          # Personnel (comptes de tiers)

# Seuil de signification par défaut : un écart cumulé annuel au-delà de
# 100 000 FCFA (en valeur absolue) est signalé « significatif ».
SEUIL_SIGNIFICATION_FCFA: Final = Decimal("100000")

NATURE_MASSE_SALARIALE: Final = "masse_salariale"
NATURE_ETAT_RETENUES: Final = "etat_retenues_source"
NATURE_PERSONNEL: Final = "personnel"

LIBELLE_MASSE_SALARIALE: Final = (
    "Masse salariale brute (déclarée vs comptes 66x)"
)

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_COHERENT: Final = "coherent"
STATUT_ECARTS: Final = "ecarts_a_expliquer"

# Commentaire consultatif quand la masse comptable dépasse le déclaré.
COMMENTAIRE_MASSE_SUPERIEURE: Final = (
    "La masse salariale comptabilisée (comptes 66x) excède la masse "
    "déclarée : cet écart peut révéler des salaires non déclarés "
    "(avantages en nature, personnel occasionnel, gratifications hors "
    "bulletin…) ou de simples décalages de rattachement — à expliquer, "
    "l'humain apprécie et décide."
)

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_RAPPROCHEMENT_SALAIRES: Final = (
    "Rapprochement consultatif des impôts sur salaires : masse "
    "salariale des déclarations déposées (saisie depuis les "
    "déclarations du client) rapprochée de la masse salariale "
    "comptabilisée (comptes 66x « Charges de personnel » de la balance "
    "annuelle) ; ITS retenu et contribution employeur restitués en "
    "cumul, comptes 447x/42x liés au personnel restitués à titre "
    "informatif. Un écart au-delà du seuil de signification appelle "
    "une explication (période omise, salaires non déclarés, décalage "
    "de rattachement…) — l'humain apprécie et décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_SAISIE_DECLARATION: Final = "saisie_declaration_salaires"
ACTION_CONSULTATION: Final = "consultation_rapprochement_salaires"


class ErreurRapprochementSalaires(Exception):
    """Échec du rapprochement des impôts sur salaires."""


class ErreurRapprochementSalairesIntrouvable(ErreurRapprochementSalaires):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurRapprochementSalairesInvalide(ErreurRapprochementSalaires):
    """Saisie invalide (période, montant) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_periode(periode: object) -> str:
    """PUR — valide une période mensuelle « AAAA-MM ».

    Invalide → :class:`ErreurRapprochementSalairesInvalide` (422 côté
    route).
    """
    texte_periode = str(periode or "").strip()
    parties = texte_periode.split("-")
    if len(parties) != 2 or [len(p) for p in parties] != [4, 2]:
        raise ErreurRapprochementSalairesInvalide(
            f"période invalide « {texte_periode} » — format attendu : "
            "AAAA-MM"
        )
    try:
        annee, mois = int(parties[0]), int(parties[1])
    except ValueError as e:
        raise ErreurRapprochementSalairesInvalide(
            f"période invalide « {texte_periode} » — format attendu : "
            "AAAA-MM"
        ) from e
    if not 1 <= mois <= 12 or annee < 1900:
        raise ErreurRapprochementSalairesInvalide(
            f"période invalide « {texte_periode} » — mois attendu entre "
            "01 et 12"
        )
    return texte_periode


def valider_montant(montant: object, champ: str) -> Decimal:
    """PUR — montant FCFA ≥ 0 arrondi au centime (Decimal).

    ``None``/vide → 0. Illisible ou négatif →
    :class:`ErreurRapprochementSalairesInvalide` (422 côté route).
    """
    if montant is None or str(montant).strip() == "":
        return Decimal("0.00")
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurRapprochementSalairesInvalide(
            f"montant illisible pour « {champ} » : {montant!r}"
        ) from e
    if valeur < 0:
        raise ErreurRapprochementSalairesInvalide(
            f"montant négatif interdit pour « {champ} » : {valeur}"
        )
    return valeur.quantize(Decimal("0.01"))


def extraire_salaires_balance(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — masse salariale comptabilisée depuis les soldes de balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``masse_salariale`` : soldes débiteurs nets des comptes 66x
      « Charges de personnel » ;
    - ``solde_etat_retenues`` : solde créditeur net des comptes 447x
      « État, impôts retenus à la source » (informatif, dépend des
      règlements) ;
    - ``solde_personnel`` : solde créditeur net des comptes 42x
      « Personnel » (informatif) ;
    - ``comptes`` : détail par compte (nature, solde signé).
    """
    masse = Decimal("0")
    solde_447 = Decimal("0")
    solde_42 = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        if compte.startswith(PREFIXE_CHARGES_PERSONNEL):
            nature = NATURE_MASSE_SALARIALE
            solde = debit - credit
            masse += solde
        elif compte.startswith(PREFIXE_ETAT_RETENUES):
            nature = NATURE_ETAT_RETENUES
            solde = credit - debit
            solde_447 += solde
        elif compte.startswith(PREFIXE_PERSONNEL):
            nature = NATURE_PERSONNEL
            solde = credit - debit
            solde_42 += solde
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
        "masse_salariale": masse,
        "solde_etat_retenues": solde_447,
        "solde_personnel": solde_42,
        "comptes": comptes,
    }


def totaliser_declarations(
    declarations: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """PUR — totaux déclarés (masse, ITS, contribution) en Decimal."""
    masse = Decimal("0")
    its = Decimal("0")
    contribution = Decimal("0")
    for d in declarations:
        masse += Decimal(str(d.get("masse_salariale_brute") or 0))
        its += Decimal(str(d.get("its_retenu") or 0))
        contribution += Decimal(
            str(d.get("contribution_employeur") or 0)
        )
    return {
        "masse_salariale_brute": masse,
        "its_retenu": its,
        "contribution_employeur": contribution,
    }


def rapprocher_salaires(
    declarations: list[dict[str, Any]],
    soldes: list[dict[str, Any]],
    seuil: Decimal = SEUIL_SIGNIFICATION_FCFA,
) -> dict[str, Any]:
    """PUR — rapproche masse salariale déclarée et comptabilisée.

    ``declarations`` : lignes ``{periode, masse_salariale_brute,
    its_retenu, contribution_employeur}`` ; ``soldes`` : lignes de
    balance ``{compte, libelle, debit, credit}``. Montants restitués en
    ``str`` (Decimal). Clés TOUJOURS présentes ; ``disponible`` est
    vrai seulement si au moins une déclaration ET au moins un compte
    66x en balance existent — l'écart ne se chiffre que sur données
    complètes. Écart = déclaré - comptabilisé ; « significatif » si sa
    valeur absolue dépasse strictement ``seuil``. Un écart significatif
    NÉGATIF (masse comptable > déclarée) porte un commentaire
    consultatif (salaires non déclarés possibles).
    """
    compta = extraire_salaires_balance(soldes)
    totaux = totaliser_declarations(declarations)

    lignes_declarations = [
        {
            "periode": str(d.get("periode") or ""),
            "masse_salariale_brute": str(
                Decimal(str(d.get("masse_salariale_brute") or 0))
            ),
            "its_retenu": str(
                Decimal(str(d.get("its_retenu") or 0))
            ),
            "contribution_employeur": str(
                Decimal(str(d.get("contribution_employeur") or 0))
            ),
        }
        for d in sorted(
            declarations, key=lambda d: str(d.get("periode") or "")
        )
    ]

    comptes_66 = [
        c for c in compta["comptes"]
        if c["nature"] == NATURE_MASSE_SALARIALE
    ]
    disponible = bool(declarations) and bool(comptes_66)

    declare = totaux["masse_salariale_brute"]
    comptabilise = compta["masse_salariale"]
    ecart = declare - comptabilise
    significatif = disponible and abs(ecart) > seuil
    commentaire = ""
    if significatif and ecart < 0:
        commentaire = COMMENTAIRE_MASSE_SUPERIEURE
    ecarts = [
        {
            "nature": NATURE_MASSE_SALARIALE,
            "libelle": LIBELLE_MASSE_SALARIALE,
            "declare": str(declare),
            "comptabilise": str(comptabilise),
            "ecart": str(ecart),
            "significatif": significatif,
            "commentaire": commentaire,
        }
    ]
    nb_significatifs = 1 if significatif else 0

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
        "totaux_declares": {k: str(v) for k, v in totaux.items()},
        "comptabilise": {
            "masse_salariale": str(compta["masse_salariale"]),
            "solde_etat_retenues": str(compta["solde_etat_retenues"]),
            "solde_personnel": str(compta["solde_personnel"]),
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
            "nb_comptes_66_balance": len(comptes_66),
            "nb_ecarts_significatifs": nb_significatifs,
        },
        "note": NOTE_RAPPROCHEMENT_SALAIRES,
    }


def _serialiser_declaration(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB ``declaration_salaires`` → charge JSON (str)."""
    cree = row.get("cree_le")
    maj = row.get("mis_a_jour_le")
    return {
        "id": int(row["id"]),
        "periode": str(row.get("periode") or ""),
        "masse_salariale_brute": str(
            Decimal(str(row.get("masse_salariale_brute") or 0))
        ),
        "its_retenu": str(Decimal(str(row.get("its_retenu") or 0))),
        "contribution_employeur": str(
            Decimal(str(row.get("contribution_employeur") or 0))
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
        raise ErreurRapprochementSalairesIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def saisir_declaration_salaires(
    session: Session,
    tenant_id: int,
    mission_id: int,
    periode: object,
    masse_salariale_brute: object,
    its_retenu: object,
    contribution_employeur: object,
    acteur: str,
) -> dict[str, Any]:
    """Saisit (ou corrige) la déclaration de salaires d'une période.

    Upsert sur ``(mission_id, periode)`` : re-saisir une période déjà
    connue REMPLACE ses montants (correction humaine, pas d'addition).
    Période ou montant invalides →
    :class:`ErreurRapprochementSalairesInvalide` (422) ; mission hors
    tenant → :class:`ErreurRapprochementSalairesIntrouvable` (404).
    Journalise :data:`ACTION_SAISIE_DECLARATION`. Retourne la
    déclaration enregistrée (montants ``str``) + note consultative.
    """
    from backend.moteur.journal import append_journal

    periode_ok = valider_periode(periode)
    masse = valider_montant(masse_salariale_brute, "masse_salariale_brute")
    its = valider_montant(its_retenu, "its_retenu")
    contribution = valider_montant(
        contribution_employeur, "contribution_employeur"
    )
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "INSERT INTO declaration_salaires (tenant_id, "
                "mission_id, periode, masse_salariale_brute, "
                "its_retenu, contribution_employeur) "
                "VALUES (:t, :m, :p, :ms, :its, :ce) "
                "ON CONFLICT (mission_id, periode) DO UPDATE SET "
                "masse_salariale_brute = EXCLUDED.masse_salariale_brute, "
                "its_retenu = EXCLUDED.its_retenu, "
                "contribution_employeur = EXCLUDED.contribution_employeur, "
                "mis_a_jour_le = now() "
                "RETURNING id, periode, masse_salariale_brute, "
                "its_retenu, contribution_employeur, cree_le, "
                "mis_a_jour_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "p": periode_ok,
                "ms": masse,
                "its": its,
                "ce": contribution,
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
                "masse_salariale_brute": str(masse),
                "its_retenu": str(its),
                "contribution_employeur": str(contribution),
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "declaration": declaration,
        "note": NOTE_RAPPROCHEMENT_SALAIRES,
    }


def _declarations_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, periode, masse_salariale_brute, its_retenu, "
            "contribution_employeur, cree_le, mis_a_jour_le "
            "FROM declaration_salaires WHERE mission_id = :m "
            "ORDER BY periode"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _soldes_salaires_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND (compte LIKE :p66 OR compte LIKE :p447 "
            "OR compte LIKE :p42) ORDER BY compte"
        ),
        {
            "m": mission_id,
            "p66": PREFIXE_CHARGES_PERSONNEL + "%",
            "p447": PREFIXE_ETAT_RETENUES + "%",
            "p42": PREFIXE_PERSONNEL + "%",
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def rapprochement_salaires_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rapprochement des impôts sur salaires — lecture seule, RLS.

    Mission hors tenant →
    :class:`ErreurRapprochementSalairesIntrouvable` (404 côté route).
    Se construit toujours : sans déclaration saisie ou sans compte 66x
    en balance, ``disponible=false`` et
    ``synthese.statut="indisponible"`` — les clés restent présentes.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        declarations = _declarations_mission(session, mission_id)
        soldes = _soldes_salaires_mission(session, mission_id)

    vue = rapprocher_salaires(declarations, soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
