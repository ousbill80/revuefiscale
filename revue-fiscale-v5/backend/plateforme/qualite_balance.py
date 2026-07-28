"""Contrôle qualité de la balance importée — vue consultative.

POURQUOI : avant toute revue fiscale, le fiscaliste apprécie la
FIABILITÉ DE LA MATIÈRE PREMIÈRE — la balance importée. Le présent
module restitue trois contrôles PURS et déterministes de qualité :

1. ÉQUILIBRE GLOBAL : total des débits = total des crédits (l'écart
   éventuel est restitué en montant, jamais interprété) ;
2. SOLDES DE SENS INHABITUEL sur les classes sensibles SYSCOHADA :
   caisse 57x créditrice, banques 52x créditrices (un découvert
   bancaire est possible — simple signalement, libellé prudent),
   fournisseurs 401x débiteurs, clients 411x créditeurs,
   amortissements 28x débiteurs, capital 101x débiteur ;
3. COMPTES HORS PLAN : numéros ne commençant pas par une classe 1 à 9
   ou de longueur aberrante.

DONNÉES : lecture seule de ``solde_compte`` — AUCUNE table nouvelle,
AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — chaque
observation ORIENTE la revue, elle ne conclut jamais : un sens
inhabituel peut être parfaitement justifié (découvert bancaire,
avoirs, acomptes fournisseurs, avances clients…), seul l'humain
examine et conclut. Fonctions pures testables sans base + accès RLS
via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.retenue_honoraires`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente. Formulations jamais accusatoires :
« solde de sens inhabituel — à examiner », jamais « erreur ».
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

#: Plafond d'observations restituées PAR CONTRÔLE — borne la réponse
#: sur les balances volumineuses ; le nombre TOTAL détecté reste
#: restitué (``nb_total``) pour que rien ne soit masqué en silence.
PLAFOND_OBSERVATIONS_PAR_CONTROLE: Final = 50

#: Nombre de contrôles de qualité restitués par la vue.
NB_CONTROLES: Final = 3

#: Longueurs plausibles d'un numéro de compte SYSCOHADA importé —
#: au-delà (ou en deçà), le numéro est signalé « hors plan » à
#: examiner (une convention interne du cabinet peut l'expliquer).
LONGUEUR_COMPTE_MIN: Final = 2
LONGUEUR_COMPTE_MAX: Final = 12

STATUT_EQUILIBREE_SANS_OBSERVATION: Final = "equilibree_sans_observation"
STATUT_OBSERVATIONS: Final = "observations_a_examiner"
STATUT_INDISPONIBLE: Final = "indisponible"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_EQUILIBREE_SANS_OBSERVATION: (
        "Balance équilibrée, aucune observation sur les contrôles "
        "restitués — la revue peut s'appuyer sur cette matière, "
        "l'humain reste juge de sa fiabilité"
    ),
    STATUT_OBSERVATIONS: (
        "Observations à examiner — chacune peut être justifiée "
        "(découvert bancaire, avoirs, acomptes…) : le fiscaliste "
        "examine et conclut"
    ),
    STATUT_INDISPONIBLE: (
        "Vue indisponible — importez la balance pour contrôler sa "
        "qualité avant la revue"
    ),
}

#: Règles de sens inhabituel sur les classes sensibles SYSCOHADA —
#: (préfixe, sens inhabituel du solde net, observation NON accusatoire).
#: ``sens`` : « crediteur » signale un solde net négatif (crédit >
#: débit), « debiteur » un solde net positif. Chaque libellé rappelle
#: qu'un sens inhabituel PEUT être justifié — jamais « erreur ».
REGLES_SENS_INHABITUEL: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "57",
        "crediteur",
        "Caisse de solde créditeur — solde de sens inhabituel, à "
        "examiner (séquence des écritures de caisse à revoir avec le "
        "client)",
    ),
    (
        "52",
        "crediteur",
        "Banque de solde créditeur — un découvert bancaire est "
        "possible : simple signalement, à rapprocher des relevés "
        "bancaires",
    ),
    (
        "401",
        "debiteur",
        "Fournisseur de solde débiteur — solde de sens inhabituel, à "
        "examiner (avances ou acomptes versés, avoirs à recevoir "
        "possibles)",
    ),
    (
        "411",
        "crediteur",
        "Client de solde créditeur — solde de sens inhabituel, à "
        "examiner (avances reçues, trop-perçus ou avoirs à établir "
        "possibles)",
    ),
    (
        "28",
        "debiteur",
        "Compte d'amortissements de solde débiteur — solde de sens "
        "inhabituel, à examiner (sorties d'immobilisations ou "
        "reclassements possibles)",
    ),
    (
        "101",
        "debiteur",
        "Capital de solde débiteur — solde de sens inhabituel, à "
        "examiner (opérations sur le capital à documenter)",
    ),
)

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_QUALITE_BALANCE: Final = (
    "Contrôle qualité consultatif de la balance importée : équilibre "
    "global (total débits / total crédits), soldes de sens inhabituel "
    "sur les classes sensibles SYSCOHADA (caisse, banques, "
    "fournisseurs, clients, amortissements, capital) et numéros de "
    "compte hors du plan attendu. Ces observations ORIENTENT la revue "
    "— un sens inhabituel peut être justifié (découvert bancaire, "
    "avoirs, acomptes fournisseurs, avances clients…), aucun "
    "signalement n'est une conclusion : seul l'humain examine, "
    "apprécie la fiabilité de la matière première et conclut."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_qualite_balance"


class ErreurQualiteBalance(Exception):
    """Échec de la vue contrôle qualité de la balance."""


class ErreurQualiteBalanceIntrouvable(ErreurQualiteBalance):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _decimal(valeur: Any) -> Decimal:
    return Decimal(str(valeur or 0))


def verifier_equilibre(soldes: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — équilibre global de la balance (totaux et écart).

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :
    ``total_debits``, ``total_credits``, ``ecart`` (valeur absolue) et
    ``equilibree`` (vrai si écart nul). L'écart est restitué tel quel,
    jamais interprété — un écart peut provenir d'arrondis d'import.
    """
    total_debits = Decimal("0")
    total_credits = Decimal("0")
    for ligne in soldes:
        total_debits += _decimal(ligne.get("debit"))
        total_credits += _decimal(ligne.get("credit"))
    ecart = abs(total_debits - total_credits)
    return {
        "total_debits": total_debits,
        "total_credits": total_credits,
        "ecart": ecart,
        "equilibree": ecart == 0,
    }


def detecter_sens_inhabituels(
    soldes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — soldes de sens inhabituel sur les classes sensibles.

    Applique :data:`REGLES_SENS_INHABITUEL` au solde net (débit −
    crédit) de chaque compte : première règle dont le préfixe
    correspond. Chaque cas restitué : ``{compte, libelle_compte,
    solde (Decimal, signé), observation}`` — observation NON
    accusatoire (« à examiner »), jamais « erreur ».
    """
    observations: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        solde = _decimal(ligne.get("debit")) - _decimal(ligne.get("credit"))
        for prefixe, sens, observation in REGLES_SENS_INHABITUEL:
            if not compte.startswith(prefixe):
                continue
            inhabituel = (
                solde > 0 if sens == "debiteur" else solde < 0
            )
            if inhabituel:
                observations.append(
                    {
                        "compte": compte,
                        "libelle_compte": str(ligne.get("libelle") or ""),
                        "solde": solde,
                        "observation": observation,
                    }
                )
            break  # première règle correspondante seulement
    return observations


def detecter_comptes_hors_plan(
    soldes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — numéros de compte hors du plan SYSCOHADA attendu.

    Signale les numéros ne commençant pas par une classe 1 à 9 (ou
    vides) et ceux de longueur aberrante (hors
    :data:`LONGUEUR_COMPTE_MIN` à :data:`LONGUEUR_COMPTE_MAX`
    caractères). Même forme de cas que les sens inhabituels —
    observation prudente : une convention interne peut l'expliquer.
    """
    observations: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        solde = _decimal(ligne.get("debit")) - _decimal(ligne.get("credit"))
        if not compte or compte[0] not in "123456789":
            observation = (
                "Numéro de compte ne commençant pas par une classe 1 à "
                "9 du plan SYSCOHADA — à examiner (compte auxiliaire ou "
                "convention interne possible)"
            )
        elif not (
            LONGUEUR_COMPTE_MIN <= len(compte) <= LONGUEUR_COMPTE_MAX
        ):
            observation = (
                "Numéro de compte de longueur inhabituelle pour un plan "
                "SYSCOHADA — à examiner (paramétrage d'import ou "
                "convention interne possible)"
            )
        else:
            continue
        observations.append(
            {
                "compte": compte,
                "libelle_compte": str(ligne.get("libelle") or ""),
                "solde": solde,
                "observation": observation,
            }
        )
    return observations


def _plafonner(
    observations: list[dict[str, Any]],
    plafond: int = PLAFOND_OBSERVATIONS_PAR_CONTROLE,
) -> dict[str, Any]:
    """PUR — borne un contrôle au plafond, sans masquer le total.

    Restitue ``{observations (sérialisées, solde en str), nb_total,
    plafonne}`` : ``nb_total`` reste le nombre réellement détecté.
    """
    return {
        "observations": [
            {
                "compte": o["compte"],
                "libelle_compte": o["libelle_compte"],
                "solde": str(o["solde"]),
                "observation": o["observation"],
            }
            for o in observations[:plafond]
        ],
        "nb_total": len(observations),
        "plafonne": len(observations) > plafond,
    }


def evaluer_qualite_balance(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — vue consultative du contrôle qualité de la balance.

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}``. Montants restitués en ``str`` (Decimal). Clés TOUJOURS
    présentes ; ``disponible`` est vrai seulement si la balance porte
    au moins une ligne — sans elle, rien n'est contrôlé (statut
    ``indisponible``, aucune observation inventée).

    Statut global : ``equilibree_sans_observation`` si la balance est
    équilibrée sans aucune observation, ``observations_a_examiner``
    sinon — jamais un verdict, seul l'humain conclut.
    """
    disponible = bool(soldes)
    equilibre = verifier_equilibre(soldes)
    sens = _plafonner(detecter_sens_inhabituels(soldes))
    hors_plan = _plafonner(detecter_comptes_hors_plan(soldes))

    nb_observations = (
        (0 if equilibre["equilibree"] else 1)
        + int(sens["nb_total"])
        + int(hors_plan["nb_total"])
    )
    if not disponible:
        statut = STATUT_INDISPONIBLE
    elif nb_observations == 0:
        statut = STATUT_EQUILIBREE_SANS_OBSERVATION
    else:
        statut = STATUT_OBSERVATIONS

    return {
        "disponible": disponible,
        "equilibre": {
            "total_debits": str(equilibre["total_debits"]),
            "total_credits": str(equilibre["total_credits"]),
            "ecart": str(equilibre["ecart"]),
            "equilibree": bool(equilibre["equilibree"]),
        },
        "sens_inhabituels": sens,
        "comptes_hors_plan": hors_plan,
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_controles": NB_CONTROLES,
            "nb_observations": nb_observations,
        },
        "note": NOTE_QUALITE_BALANCE,
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurQualiteBalanceIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _soldes_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m ORDER BY compte"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_qualite_balance_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Contrôle qualité de la balance de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurQualiteBalanceIntrouvable`
    (404 côté route). Se construit toujours : sans balance,
    ``disponible=false`` et ``statut="indisponible"`` — les clés
    restent présentes, aucune observation inventée. Tolérance par
    bloc : un échec de lecture de la balance dégrade en indisponible
    au lieu de faire échouer la vue.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        try:
            soldes = _soldes_mission(session, mission_id)
        except Exception:
            # Tolérance par bloc : balance illisible → vue
            # indisponible, servie quand même (clés stables).
            soldes = []

    vue = evaluer_qualite_balance(soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
