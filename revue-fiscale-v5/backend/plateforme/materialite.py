"""Seuil de matérialité et ciblage des travaux — depuis la balance.

POURQUOI : avant de dérouler le programme de travail, l'auditeur fixe
un SEUIL DE SIGNIFICATION (matérialité) qui délimite les comptes
méritant une revue détaillée. Ce module PROPOSE des seuils calculés de
façon déterministe depuis la balance importée (``solde_compte``) selon
les référentiels d'audit usuels (pratique ISA 320) :

- 1 % du CHIFFRE D'AFFAIRES (comptes 70x, soldes créditeurs nets) —
  référentiel privilégié pour une revue fiscale (assiettes déclaratives
  assises sur le CA) ;
- 5 % du RÉSULTAT courant approché (classe 7 - classe 6, en valeur
  absolue) ;
- 1 % du TOTAL BILAN approché (somme des soldes débiteurs nets des
  comptes de classes 1 à 5 — actif approché).

Le fiscaliste CONFIRME une proposition ou la REMPLACE par un seuil
manuel (clic humain, POST) ; les comptes dont le solde (en valeur
absolue) dépasse strictement le seuil retenu sont restitués, groupés
par classe SYSCOHADA, avec le taux de couverture des masses.

LIMITES ASSUMÉES : la balance est ANNUELLE et non retraitée — le
résultat approché ignore la classe 8 (HAO) et le total bilan approché
est la somme des soldes débiteurs nets (pas un bilan après
affectation). Ces approximations sont documentées à l'écran ; seul
l'œil humain arrête le seuil définitif.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
ciblage éclaire le programme de travail, l'humain décide. Fonctions
pures testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.rapprochement_tva`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente, ``disponible=false`` sans balance.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

# Référentiels de calcul du seuil proposé (pratique d'audit usuelle,
# ISA 320) : code → (libellé, taux appliqué à la base).
REFERENTIEL_CA: Final = "ca"
REFERENTIEL_RESULTAT: Final = "resultat"
REFERENTIEL_BILAN: Final = "bilan"

TAUX_REFERENTIELS: Final[dict[str, Decimal]] = {
    REFERENTIEL_CA: Decimal("0.01"),        # 1 % du chiffre d'affaires
    REFERENTIEL_RESULTAT: Decimal("0.05"),  # 5 % du résultat courant
    REFERENTIEL_BILAN: Decimal("0.01"),     # 1 % du total bilan
}

LIBELLES_REFERENTIELS: Final[dict[str, str]] = {
    REFERENTIEL_CA: "1 % du chiffre d'affaires (comptes 70x)",
    REFERENTIEL_RESULTAT: (
        "5 % du résultat courant approché (classe 7 - classe 6)"
    ),
    REFERENTIEL_BILAN: (
        "1 % du total bilan approché (soldes débiteurs classes 1 à 5)"
    ),
}

SOURCE_PROPOSITION: Final = "proposition"
SOURCE_MANUEL: Final = "manuel"

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_SEUIL_A_RETENIR: Final = "seuil_a_retenir"
STATUT_TRAVAUX_CIBLES: Final = "travaux_cibles"

# Libellés des classes SYSCOHADA (1er caractère du numéro de compte).
LIBELLES_CLASSES: Final[dict[str, str]] = {
    "1": "Classe 1 — Ressources durables",
    "2": "Classe 2 — Actif immobilisé",
    "3": "Classe 3 — Stocks",
    "4": "Classe 4 — Tiers",
    "5": "Classe 5 — Trésorerie",
    "6": "Classe 6 — Charges",
    "7": "Classe 7 — Produits",
    "8": "Classe 8 — Autres charges et produits (HAO)",
    "9": "Classe 9 — Comptabilité analytique",
}

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_MATERIALITE: Final = (
    "Seuil de matérialité et ciblage consultatifs : les seuils proposés "
    "sont calculés depuis la balance annuelle selon les référentiels "
    "d'audit usuels (1 % du CA, 5 % du résultat courant approché, 1 % "
    "du total bilan approché) — le fiscaliste confirme ou remplace par "
    "un seuil manuel. Les comptes dont le solde dépasse le seuil retenu "
    "méritent une revue détaillée ; le ciblage éclaire le programme de "
    "travail, l'humain décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_RETENUE_SEUIL: Final = "retenue_seuil_materialite"
ACTION_CONSULTATION: Final = "consultation_materialite"


class ErreurMaterialite(Exception):
    """Échec du calcul de matérialité."""


class ErreurMaterialiteIntrouvable(ErreurMaterialite):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurMaterialiteInvalide(ErreurMaterialite):
    """Saisie invalide (source, montant, référentiel) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _solde_signe(ligne: dict[str, Any]) -> Decimal:
    """PUR — solde signé débit - crédit d'une ligne de balance."""
    debit = Decimal(str(ligne.get("debit") or 0))
    credit = Decimal(str(ligne.get("credit") or 0))
    return debit - credit


def agreger_balance(soldes: list[dict[str, Any]]) -> dict[str, Decimal]:
    """PUR — agrégats de la balance servant de bases aux seuils.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne en :class:`Decimal` :

    - ``chiffre_affaires`` : soldes créditeurs nets des comptes 70x ;
    - ``resultat`` : classe 7 (crédit - débit) - classe 6 (débit -
      crédit) — résultat courant approché, HAO (classe 8) exclu ;
    - ``total_bilan`` : somme des soldes débiteurs nets des comptes de
      classes 1 à 5 (actif approché avant affectation).
    """
    chiffre_affaires = Decimal("0")
    produits = Decimal("0")
    charges = Decimal("0")
    total_bilan = Decimal("0")
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte:
            continue
        solde = _solde_signe(ligne)
        classe = compte[0]
        if compte.startswith("70"):
            chiffre_affaires += -solde
        if classe == "7":
            produits += -solde
        elif classe == "6":
            charges += solde
        elif classe in "12345" and solde > 0:
            total_bilan += solde
    return {
        "chiffre_affaires": chiffre_affaires,
        "resultat": produits - charges,
        "total_bilan": total_bilan,
    }


def proposer_seuils(soldes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — seuils de signification proposés par référentiel.

    Une proposition par référentiel, TOUJOURS les trois, dans un ordre
    stable (ca, resultat, bilan). ``calculable=false`` (et
    ``seuil_propose=None``) si la base est nulle ou négative — un seuil
    doit être strictement positif. Le résultat est pris en VALEUR
    ABSOLUE (une perte reste une base de matérialité). Seuils arrondis
    au franc CFA entier (ROUND_HALF_UP).
    """
    agregats = agreger_balance(soldes)
    bases = {
        REFERENTIEL_CA: agregats["chiffre_affaires"],
        REFERENTIEL_RESULTAT: abs(agregats["resultat"]),
        REFERENTIEL_BILAN: agregats["total_bilan"],
    }
    propositions: list[dict[str, Any]] = []
    for code in (REFERENTIEL_CA, REFERENTIEL_RESULTAT, REFERENTIEL_BILAN):
        base = bases[code]
        seuil = (base * TAUX_REFERENTIELS[code]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        calculable = seuil > 0
        propositions.append(
            {
                "referentiel": code,
                "libelle": LIBELLES_REFERENTIELS[code],
                "taux": str(TAUX_REFERENTIELS[code]),
                "base": base,
                "seuil_propose": seuil if calculable else None,
                "calculable": calculable,
            }
        )
    return propositions


def valider_seuil_manuel(montant: object) -> Decimal:
    """PUR — seuil manuel FCFA strictement positif (Decimal).

    Illisible, vide, nul ou négatif →
    :class:`ErreurMaterialiteInvalide` (422 côté route).
    """
    if montant is None or str(montant).strip() == "":
        raise ErreurMaterialiteInvalide(
            "seuil manuel requis : montant en FCFA strictement positif"
        )
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurMaterialiteInvalide(
            f"seuil manuel illisible : {montant!r}"
        ) from e
    if valeur <= 0:
        raise ErreurMaterialiteInvalide(
            f"seuil manuel strictement positif requis : {valeur}"
        )
    return valeur.quantize(Decimal("0.01"))


def cibler_comptes(
    soldes: list[dict[str, Any]], seuil: Decimal
) -> list[dict[str, Any]]:
    """PUR — comptes dont |solde| dépasse STRICTEMENT le seuil.

    Ces comptes méritent une revue détaillée (ciblage des travaux).
    Tri : classe puis |solde| décroissant. Chaque ligne porte le solde
    signé (débit - crédit) en :class:`Decimal`.
    """
    cibles = [
        {
            "compte": str(ligne.get("compte") or "").strip(),
            "libelle": str(ligne.get("libelle") or ""),
            "classe": str(ligne.get("compte") or "").strip()[:1],
            "solde": _solde_signe(ligne),
        }
        for ligne in soldes
        if str(ligne.get("compte") or "").strip()
        and abs(_solde_signe(ligne)) > seuil
    ]
    return sorted(cibles, key=lambda c: (c["classe"], -abs(c["solde"])))


def _taux_pct(part: Decimal, masse: Decimal) -> str:
    """PUR — taux part/masse en pourcentage (1 décimale, str)."""
    if masse <= 0:
        return "0.0"
    return str(
        (part / masse * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


def couverture_par_classe(
    soldes: list[dict[str, Any]], cibles: list[dict[str, Any]]
) -> dict[str, Any]:
    """PUR — couverture des masses par les comptes ciblés, par classe.

    Masse d'une classe = somme des |solde| de ses comptes ; couverture
    = part de cette masse portée par les comptes ciblés. Retourne
    ``{par_classe: [...], taux_global: str}`` — classes triées, seules
    les classes présentes en balance apparaissent.
    """
    masses: dict[str, Decimal] = {}
    nb_comptes: dict[str, int] = {}
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte:
            continue
        classe = compte[0]
        masses[classe] = masses.get(classe, Decimal("0")) + abs(
            _solde_signe(ligne)
        )
        nb_comptes[classe] = nb_comptes.get(classe, 0) + 1

    couvert: dict[str, Decimal] = {}
    nb_cibles: dict[str, int] = {}
    for c in cibles:
        classe = c["classe"]
        couvert[classe] = couvert.get(classe, Decimal("0")) + abs(
            c["solde"]
        )
        nb_cibles[classe] = nb_cibles.get(classe, 0) + 1

    par_classe = [
        {
            "classe": classe,
            "libelle": LIBELLES_CLASSES.get(
                classe, f"Classe {classe}"
            ),
            "nb_comptes": nb_comptes[classe],
            "nb_comptes_cibles": nb_cibles.get(classe, 0),
            "masse": masses[classe],
            "masse_ciblee": couvert.get(classe, Decimal("0")),
            "taux_couverture": _taux_pct(
                couvert.get(classe, Decimal("0")), masses[classe]
            ),
        }
        for classe in sorted(masses)
    ]
    masse_totale = sum(masses.values(), Decimal("0"))
    masse_ciblee = sum(couvert.values(), Decimal("0"))
    return {
        "par_classe": par_classe,
        "masse_totale": masse_totale,
        "masse_ciblee": masse_ciblee,
        "taux_global": _taux_pct(masse_ciblee, masse_totale),
    }


def construire_vue_materialite(
    soldes: list[dict[str, Any]],
    seuil_retenu: dict[str, Any] | None,
) -> dict[str, Any]:
    """PUR — vue complète matérialité + ciblage (montants ``str``).

    ``seuil_retenu`` : ligne ``materialite_mission`` sérialisée (ou
    ``None`` si l'humain n'a encore rien retenu). Clés TOUJOURS
    présentes ; ``disponible`` vrai seulement si la balance porte au
    moins un compte. Le ciblage n'est chiffré que si un seuil est
    retenu ET la balance disponible.
    """
    disponible = bool(soldes)
    propositions = proposer_seuils(soldes)
    agregats = agreger_balance(soldes)

    montant_retenu = (
        Decimal(str(seuil_retenu["seuil_retenu"]))
        if seuil_retenu is not None
        else None
    )
    cibles = (
        cibler_comptes(soldes, montant_retenu)
        if disponible and montant_retenu is not None
        else []
    )
    couverture = couverture_par_classe(soldes, cibles)

    if not disponible:
        statut = STATUT_INDISPONIBLE
    elif montant_retenu is None:
        statut = STATUT_SEUIL_A_RETENIR
    else:
        statut = STATUT_TRAVAUX_CIBLES

    return {
        "disponible": disponible,
        "agregats": {k: str(v) for k, v in agregats.items()},
        "propositions": [
            {
                "referentiel": p["referentiel"],
                "libelle": p["libelle"],
                "taux": p["taux"],
                "base": str(p["base"]),
                "seuil_propose": (
                    str(p["seuil_propose"])
                    if p["seuil_propose"] is not None
                    else None
                ),
                "calculable": p["calculable"],
            }
            for p in propositions
        ],
        "seuil_retenu": seuil_retenu,
        "comptes_cibles": [
            {
                "compte": c["compte"],
                "libelle": c["libelle"],
                "classe": c["classe"],
                "solde": str(c["solde"]),
            }
            for c in cibles
        ],
        "couverture": {
            "par_classe": [
                {
                    "classe": ligne["classe"],
                    "libelle": ligne["libelle"],
                    "nb_comptes": ligne["nb_comptes"],
                    "nb_comptes_cibles": ligne["nb_comptes_cibles"],
                    "masse": str(ligne["masse"]),
                    "masse_ciblee": str(ligne["masse_ciblee"]),
                    "taux_couverture": ligne["taux_couverture"],
                }
                for ligne in couverture["par_classe"]
            ],
            "masse_totale": str(couverture["masse_totale"]),
            "masse_ciblee": str(couverture["masse_ciblee"]),
            "taux_global": couverture["taux_global"],
        },
        "synthese": {
            "statut": statut,
            "nb_comptes_balance": len(soldes),
            "nb_comptes_cibles": len(cibles),
            "taux_couverture_global": couverture["taux_global"],
        },
        "note": NOTE_MATERIALITE,
    }


def _serialiser_seuil(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB ``materialite_mission`` → charge JSON (str)."""
    cree = row.get("cree_le")
    maj = row.get("mis_a_jour_le")
    return {
        "seuil_retenu": str(Decimal(str(row["seuil_retenu"]))),
        "source": str(row.get("source") or ""),
        "referentiel": str(row.get("referentiel") or ""),
        "commentaire": str(row.get("commentaire") or ""),
        "decide_par": str(row.get("decide_par") or ""),
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
        raise ErreurMaterialiteIntrouvable(
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


def _seuil_retenu_mission(
    session: Session, mission_id: int
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT seuil_retenu, source, referentiel, commentaire, "
            "decide_par, cree_le, mis_a_jour_le "
            "FROM materialite_mission WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).mappings().one_or_none()
    return _serialiser_seuil(dict(row)) if row is not None else None


def materialite_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Matérialité + ciblage de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurMaterialiteIntrouvable` (404
    côté route). Se construit toujours : sans balance importée,
    ``disponible=false`` et ``synthese.statut="indisponible"`` — les
    clés restent présentes.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        soldes = _soldes_mission(session, mission_id)
        seuil = _seuil_retenu_mission(session, mission_id)

    vue = construire_vue_materialite(soldes, seuil)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue


def retenir_seuil(
    session: Session,
    tenant_id: int,
    mission_id: int,
    source: object,
    montant: object,
    referentiel: object,
    commentaire: object,
    acteur: str,
) -> dict[str, Any]:
    """Retient le seuil de matérialité de la mission — clic humain.

    ``source="proposition"`` : confirme le seuil proposé du
    ``referentiel`` (ca, resultat, bilan) recalculé depuis la balance —
    422 si référentiel inconnu ou proposition non calculable (balance
    absente ou base nulle). ``source="manuel"`` : ``montant`` FCFA
    strictement positif requis (422 sinon). Upsert sur ``mission_id`` :
    re-retenir REMPLACE la décision (correction humaine). Mission hors
    tenant → 404. Journalise :data:`ACTION_RETENUE_SEUIL`. Retourne le
    seuil retenu + note consultative.
    """
    from backend.moteur.journal import append_journal

    source_ok = str(source or "").strip()
    if source_ok not in (SOURCE_PROPOSITION, SOURCE_MANUEL):
        raise ErreurMaterialiteInvalide(
            f"source invalide « {source_ok} » — attendu : "
            f"{SOURCE_PROPOSITION} ou {SOURCE_MANUEL}"
        )
    commentaire_ok = str(commentaire or "").strip()

    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)

        if source_ok == SOURCE_MANUEL:
            seuil = valider_seuil_manuel(montant)
            referentiel_ok = ""
        else:
            referentiel_ok = str(referentiel or "").strip()
            if referentiel_ok not in TAUX_REFERENTIELS:
                raise ErreurMaterialiteInvalide(
                    f"référentiel inconnu « {referentiel_ok} » — "
                    "attendu : ca, resultat ou bilan"
                )
            soldes = _soldes_mission(session, mission_id)
            par_code = {
                p["referentiel"]: p for p in proposer_seuils(soldes)
            }
            proposition = par_code[referentiel_ok]
            if not proposition["calculable"]:
                raise ErreurMaterialiteInvalide(
                    f"proposition « {referentiel_ok} » non calculable "
                    "(balance absente ou base nulle) — saisissez un "
                    "seuil manuel"
                )
            seuil = Decimal(str(proposition["seuil_propose"])).quantize(
                Decimal("0.01")
            )

        row = session.execute(
            text(
                "INSERT INTO materialite_mission (tenant_id, "
                "mission_id, seuil_retenu, source, referentiel, "
                "commentaire, decide_par) "
                "VALUES (:t, :m, :s, :src, :ref, :com, :par) "
                "ON CONFLICT (mission_id) DO UPDATE SET "
                "seuil_retenu = EXCLUDED.seuil_retenu, "
                "source = EXCLUDED.source, "
                "referentiel = EXCLUDED.referentiel, "
                "commentaire = EXCLUDED.commentaire, "
                "decide_par = EXCLUDED.decide_par, "
                "mis_a_jour_le = now() "
                "RETURNING seuil_retenu, source, referentiel, "
                "commentaire, decide_par, cree_le, mis_a_jour_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "s": seuil,
                "src": source_ok,
                "ref": referentiel_ok,
                "com": commentaire_ok,
                "par": acteur,
            },
        ).mappings().one()
        retenu = _serialiser_seuil(dict(row))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_RETENUE_SEUIL,
            charge_utile={
                "seuil_retenu": str(seuil),
                "source": source_ok,
                "referentiel": referentiel_ok,
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "seuil_retenu": retenu,
        "note": NOTE_MATERIALITE,
    }
