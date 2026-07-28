"""Tableau de passage résultat comptable → résultat fiscal — IS théorique.

POURQUOI : au terme de la revue, le fiscaliste ivoirien déroule le
tableau de passage : du résultat comptable de la balance, il RÉINTÈGRE
les charges non déductibles, DÉDUIT les produits non imposables et
déductions fiscales, impute l'éventuel report déficitaire antérieur et
obtient le résultat fiscal, base de l'IS théorique au taux normal.

RÉSULTAT COMPTABLE (choix documenté) : calculé de la balance
(``solde_compte``) comme la somme SIGNÉE des soldes créditeurs nets
des classes 6, 7 ET 8 — soit produits (classe 7, créditeurs) moins
charges (classe 6, débitrices), PLUS le solde net HAO de la classe 8
SYSCOHADA si des comptes 8x sont présents (la classe 8 porte charges
ET produits HAO ainsi que participation 87x et impôt 89x). Ce total
signé équivaut mathématiquement à « produits - charges ». ATTENTION :
si l'IS comptabilisé (89x) figure en balance, il diminue ce résultat
comptable et doit être RÉINTÉGRÉ par une ligne humaine (pratique
usuelle du tableau de passage) — le module ne le réintègre pas seul.

REPORT DÉFICITAIRE (règle retenue, documentée) : le report antérieur
saisi est imputé DANS LA LIMITE du bénéfice fiscal avant report
(``report_impute = min(report, max(résultat avant report, 0))``) — il
ne crée ni n'aggrave jamais un déficit ; le reliquat non imputé est
restitué. Les modalités fines du CGI ivoirien (durée de report,
plafonds particuliers) relèvent de l'appréciation humaine.

IS THÉORIQUE : taux normal ivoirien de 25 % (:data:`TAUX_IS_NORMAL`,
CGI, impôt BIC des personnes morales) appliqué au résultat fiscal
s'il est bénéficiaire, arrondi au franc. IMPÔT MINIMUM FORFAITAIRE :
mention strictement CONSULTATIVE — signalée si le résultat fiscal est
déficitaire ou si l'IS théorique est inférieur au minimum de
perception indicatif (:data:`IMF_MINIMUM_PERCEPTION_INDICATIF`) ;
l'IMF précis (assiette chiffre d'affaires TTC, taux, plancher,
plafond, exonérations) n'est PAS calculé ici.

EXISTANT : :mod:`backend.restitution.passage` agrège les conclusions
du MOTEUR (réintégrations/déductions issues des règles déclenchées) ;
le présent module porte au contraire la SAISIE HUMAINE du tableau de
passage complet (résultat comptable, report, IS théorique) — les deux
vues sont complémentaires et indépendantes.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
passage éclaire la liquidation, l'humain décide. Fonctions pures
testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.rapprochement_tva`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente. Écritures uniquement sur POST humain.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

SENS_REINTEGRATION: Final = "reintegration"
SENS_DEDUCTION: Final = "deduction"
# Saisie spéciale : le report déficitaire antérieur (une valeur par
# mission, remplacée à chaque re-saisie).
SENS_REPORT_DEFICITAIRE: Final = "report_deficitaire"

SENS_RETRAITEMENT: Final = (SENS_REINTEGRATION, SENS_DEDUCTION)

LIBELLES_SENS: Final[dict[str, str]] = {
    SENS_REINTEGRATION: "Réintégration",
    SENS_DEDUCTION: "Déduction",
}

# Préfixes SYSCOHADA lus dans la balance pour le résultat comptable.
PREFIXE_CHARGES: Final = "6"      # charges (débitrices)
PREFIXE_PRODUITS: Final = "7"     # produits (créditeurs)
PREFIXE_HAO: Final = "8"          # HAO + participation/impôt (signé)

# Taux normal de l'impôt sur les bénéfices (BIC personnes morales,
# CGI ivoirien) — appliqué au résultat fiscal bénéficiaire.
TAUX_IS_NORMAL: Final = Decimal("0.25")

# Minimum de perception INDICATIF de l'impôt minimum forfaitaire au
# régime du réel normal (ordre de grandeur CGI, art. 39) — sert
# uniquement à SIGNALER que l'IMF pourrait s'appliquer, jamais à le
# calculer.
IMF_MINIMUM_PERCEPTION_INDICATIF: Final = Decimal("3000000")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_BENEFICIAIRE: Final = "beneficiaire"
STATUT_DEFICITAIRE: Final = "deficitaire"
STATUT_NUL: Final = "nul"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Passage indisponible — importez la balance (classes 6 et 7)"
    ),
    STATUT_BENEFICIAIRE: "Résultat fiscal bénéficiaire",
    STATUT_DEFICITAIRE: "Résultat fiscal déficitaire",
    STATUT_NUL: "Résultat fiscal nul",
}

MOTIF_IMF_DEFICIT: Final = "resultat_deficitaire"
MOTIF_IMF_IS_FAIBLE: Final = "is_inferieur_minimum_indicatif"

LIBELLES_MOTIF_IMF: Final[dict[str, str]] = {
    MOTIF_IMF_DEFICIT: (
        "Résultat fiscal déficitaire ou nul — l'impôt minimum "
        "forfaitaire pourrait s'appliquer (à vérifier par le "
        "fiscaliste, IMF non calculé ici)"
    ),
    MOTIF_IMF_IS_FAIBLE: (
        "IS théorique inférieur au minimum de perception indicatif — "
        "l'impôt minimum forfaitaire pourrait s'appliquer (à vérifier "
        "par le fiscaliste, IMF non calculé ici)"
    ),
}

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_RESULTAT_FISCAL: Final = (
    "Tableau de passage consultatif du résultat comptable (balance, "
    "classes 6/7, HAO 8x inclus si présents) au résultat fiscal : "
    "réintégrations et déductions saisies par le fiscaliste "
    "(référence CGI facultative), report déficitaire antérieur imputé "
    "dans la limite du bénéfice. L'IS théorique au taux normal de "
    "25 % et le signal d'impôt minimum forfaitaire sont indicatifs — "
    "l'humain liquide, apprécie et décide."
)

# Codes journalisés dans le journal d'audit.
ACTION_SAISIE_RETRAITEMENT: Final = "saisie_retraitement_fiscal"
ACTION_SUPPRESSION_RETRAITEMENT: Final = "suppression_retraitement_fiscal"
ACTION_SAISIE_REPORT: Final = "saisie_report_deficitaire"
ACTION_CONSULTATION: Final = "consultation_resultat_fiscal"
ACTION_REPRISE_IS_DU: Final = "reprise_is_du_depuis_resultat_fiscal"


class ErreurResultatFiscal(Exception):
    """Échec du tableau de passage fiscal."""


class ErreurResultatFiscalIntrouvable(ErreurResultatFiscal):
    """Mission ou ligne hors périmètre du tenant — 404 côté route."""


class ErreurResultatFiscalInvalide(ErreurResultatFiscal):
    """Saisie invalide (sens, libellé, montant) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_sens(sens: object) -> str:
    """PUR — sens de saisie (retraitement ou report déficitaire).

    Invalide → :class:`ErreurResultatFiscalInvalide` (422 côté route).
    """
    texte_sens = str(sens or "").strip()
    if texte_sens not in (*SENS_RETRAITEMENT, SENS_REPORT_DEFICITAIRE):
        attendus = ", ".join((*SENS_RETRAITEMENT, SENS_REPORT_DEFICITAIRE))
        raise ErreurResultatFiscalInvalide(
            f"sens invalide « {texte_sens} » — sens attendus : {attendus}"
        )
    return texte_sens


def valider_libelle(libelle: object) -> str:
    """PUR — libellé de retraitement non vide (max 300 caractères).

    Invalide → :class:`ErreurResultatFiscalInvalide` (422 côté route).
    """
    texte_libelle = str(libelle or "").strip()
    if not texte_libelle:
        raise ErreurResultatFiscalInvalide(
            "libellé requis pour un retraitement (réintégration ou "
            "déduction)"
        )
    if len(texte_libelle) > 300:
        raise ErreurResultatFiscalInvalide(
            "libellé trop long (300 caractères maximum)"
        )
    return texte_libelle


def valider_montant(montant: object, champ: str) -> Decimal:
    """PUR — montant FCFA ≥ 0 arrondi au centime (Decimal).

    ``None``/vide → 0. Illisible ou négatif →
    :class:`ErreurResultatFiscalInvalide` (422 côté route) — le SENS
    porte le signe, jamais le montant.
    """
    if montant is None or str(montant).strip() == "":
        return Decimal("0.00")
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurResultatFiscalInvalide(
            f"montant illisible pour « {champ} » : {montant!r}"
        ) from e
    if valeur < 0:
        raise ErreurResultatFiscalInvalide(
            f"montant négatif interdit pour « {champ} » : {valeur} — "
            "le sens (réintégration/déduction) porte le signe"
        )
    return valeur.quantize(Decimal("0.01"))


def extraire_resultat_comptable(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — résultat comptable depuis les soldes de balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``produits_classe7`` : soldes créditeurs nets des comptes 7x ;
    - ``charges_classe6`` : soldes débiteurs nets des comptes 6x ;
    - ``solde_hao_classe8`` : solde créditeur net SIGNÉ des comptes 8x
      (positif = produits HAO nets ; inclut 87x/89x si présents) ;
    - ``resultat_comptable`` : produits - charges + solde HAO ;
    - ``nb_comptes_resultat`` : nombre de comptes 6x/7x/8x lus ;
    - ``disponible`` : vrai si au moins un compte 6x ou 7x existe.
    """
    produits = Decimal("0")
    charges = Decimal("0")
    hao = Decimal("0")
    nb = 0
    exploitation_presente = False
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte or compte[0] not in "678":
            continue
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        nb += 1
        if compte.startswith(PREFIXE_CHARGES):
            charges += debit - credit
            exploitation_presente = True
        elif compte.startswith(PREFIXE_PRODUITS):
            produits += credit - debit
            exploitation_presente = True
        else:  # classe 8 — HAO, participation, impôt : solde signé
            hao += credit - debit
    return {
        "produits_classe7": produits,
        "charges_classe6": charges,
        "solde_hao_classe8": hao,
        "resultat_comptable": produits - charges + hao,
        "nb_comptes_resultat": nb,
        "disponible": exploitation_presente,
    }


def totaliser_retraitements(
    retraitements: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """PUR — totaux des réintégrations et déductions (Decimal)."""
    totaux = {s: Decimal("0") for s in SENS_RETRAITEMENT}
    for r in retraitements:
        sens = str(r.get("sens") or "")
        if sens in totaux:
            totaux[sens] += Decimal(str(r.get("montant") or 0))
    return totaux


def arrondir_franc(montant: Decimal) -> Decimal:
    """PUR — arrondi au franc CFA (entier, ROUND_HALF_UP)."""
    return montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calculer_passage_fiscal(
    soldes: list[dict[str, Any]],
    retraitements: list[dict[str, Any]],
    report_anterieur: Decimal | None,
    taux_is: Decimal = TAUX_IS_NORMAL,
) -> dict[str, Any]:
    """PUR — tableau de passage résultat comptable → résultat fiscal.

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}`` ; ``retraitements`` : lignes ``{id, sens, libelle,
    montant, reference_cgi}`` ; ``report_anterieur`` : report
    déficitaire antérieur saisi (``None`` si non saisi). Montants
    restitués en ``str`` (Decimal). Clés TOUJOURS présentes ;
    ``disponible`` est vrai seulement si la balance porte au moins un
    compte de résultat (6x ou 7x) — sans elle, le passage ne se
    chiffre pas (les retraitements saisis restent listés).

    Déterministe :

    - résultat fiscal avant report = résultat comptable
      + réintégrations - déductions ;
    - report imputé = min(report antérieur, max(avant report, 0)) —
      plafonné au bénéfice, ne crée jamais de déficit ;
    - résultat fiscal = avant report - report imputé ;
    - IS théorique = taux normal × résultat fiscal bénéficiaire,
      arrondi au franc (0 si déficitaire ou nul) ;
    - IMF : signal consultatif si résultat ≤ 0 ou IS théorique <
      :data:`IMF_MINIMUM_PERCEPTION_INDICATIF` (IMF non calculé).
    """
    compta = extraire_resultat_comptable(soldes)
    totaux = totaliser_retraitements(retraitements)

    lignes = [
        {
            "id": int(r["id"]) if r.get("id") is not None else None,
            "sens": str(r.get("sens") or ""),
            "libelle_sens": LIBELLES_SENS.get(
                str(r.get("sens") or ""), str(r.get("sens") or "")
            ),
            "libelle": str(r.get("libelle") or ""),
            "montant": str(Decimal(str(r.get("montant") or 0))),
            "reference_cgi": (
                str(r["reference_cgi"]) if r.get("reference_cgi") else None
            ),
        }
        for r in sorted(
            retraitements,
            key=lambda r: (
                # Réintégrations d'abord (ordre du tableau de passage),
                # puis par id de saisie.
                0 if str(r.get("sens") or "") == SENS_REINTEGRATION else 1,
                int(r["id"]) if r.get("id") is not None else 0,
            ),
        )
    ]

    disponible = bool(compta["disponible"])
    report_saisi = (
        Decimal(str(report_anterieur))
        if report_anterieur is not None
        else Decimal("0")
    )

    if disponible:
        avant_report = (
            compta["resultat_comptable"]
            + totaux[SENS_REINTEGRATION]
            - totaux[SENS_DEDUCTION]
        )
        # Règle retenue : imputation plafonnée au bénéfice avant
        # report — le report n'aggrave jamais un déficit.
        report_impute = min(report_saisi, max(avant_report, Decimal("0")))
        resultat_fiscal = avant_report - report_impute
        if resultat_fiscal > 0:
            statut = STATUT_BENEFICIAIRE
            is_theorique = arrondir_franc(resultat_fiscal * taux_is)
        elif resultat_fiscal < 0:
            statut = STATUT_DEFICITAIRE
            is_theorique = Decimal("0")
        else:
            statut = STATUT_NUL
            is_theorique = Decimal("0")
        if resultat_fiscal <= 0:
            motif_imf: str | None = MOTIF_IMF_DEFICIT
        elif is_theorique < IMF_MINIMUM_PERCEPTION_INDICATIF:
            motif_imf = MOTIF_IMF_IS_FAIBLE
        else:
            motif_imf = None
    else:
        avant_report = Decimal("0")
        report_impute = Decimal("0")
        resultat_fiscal = Decimal("0")
        is_theorique = Decimal("0")
        statut = STATUT_INDISPONIBLE
        motif_imf = None

    return {
        "disponible": disponible,
        "comptable": {
            "produits_classe7": str(compta["produits_classe7"]),
            "charges_classe6": str(compta["charges_classe6"]),
            "solde_hao_classe8": str(compta["solde_hao_classe8"]),
            "resultat_comptable": str(compta["resultat_comptable"]),
            "nb_comptes_resultat": int(compta["nb_comptes_resultat"]),
        },
        "retraitements": lignes,
        "totaux_retraitements": {
            "reintegrations": str(totaux[SENS_REINTEGRATION]),
            "deductions": str(totaux[SENS_DEDUCTION]),
        },
        "report_deficitaire": {
            "saisi": report_anterieur is not None,
            "anterieur": str(report_saisi),
            "impute": str(report_impute),
            "restant": str(report_saisi - report_impute),
        },
        "resultat_fiscal_avant_report": str(avant_report),
        "resultat_fiscal": str(resultat_fiscal),
        "taux_is_normal": str(TAUX_IS_NORMAL),
        "is_theorique": str(is_theorique),
        "imf": {
            "possible": motif_imf is not None,
            "motif": motif_imf,
            "libelle": (
                LIBELLES_MOTIF_IMF[motif_imf] if motif_imf else None
            ),
            "minimum_perception_indicatif": str(
                IMF_MINIMUM_PERCEPTION_INDICATIF
            ),
        },
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_retraitements": len(lignes),
            "imf_possible": motif_imf is not None,
        },
        "note": NOTE_RESULTAT_FISCAL,
    }


def _serialiser_retraitement(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — ligne DB ``retraitement_fiscal`` → charge JSON."""
    cree = row.get("cree_le")
    return {
        "id": int(row["id"]),
        "sens": str(row.get("sens") or ""),
        "libelle_sens": LIBELLES_SENS.get(
            str(row.get("sens") or ""), str(row.get("sens") or "")
        ),
        "libelle": str(row.get("libelle") or ""),
        "montant": str(Decimal(str(row.get("montant") or 0))),
        "reference_cgi": (
            str(row["reference_cgi"]) if row.get("reference_cgi") else None
        ),
        "cree_le": (
            cree.isoformat() if isinstance(cree, datetime) else None
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
        raise ErreurResultatFiscalIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def saisir_retraitement(
    session: Session,
    tenant_id: int,
    mission_id: int,
    sens: object,
    montant: object,
    acteur: str,
    libelle: object = None,
    reference_cgi: object = None,
) -> dict[str, Any]:
    """Ajoute une ligne de retraitement OU saisit le report — clic humain.

    ``sens`` ``reintegration``/``deduction`` : AJOUTE une ligne
    (libellé requis, référence CGI facultative) — pas d'upsert, les
    libellés sont libres et non uniques ; la correction passe par la
    suppression de la ligne (par id) puis une nouvelle saisie (choix
    documenté : plus simple et sans ambiguïté). ``sens`` =
    ``report_deficitaire`` : REMPLACE le report antérieur de la
    mission (une valeur, le libellé est ignoré).
    Saisie invalide → :class:`ErreurResultatFiscalInvalide` (422) ;
    mission hors tenant → :class:`ErreurResultatFiscalIntrouvable`
    (404). Journalise :data:`ACTION_SAISIE_RETRAITEMENT` ou
    :data:`ACTION_SAISIE_REPORT`.
    """
    from backend.moteur.journal import append_journal

    sens_ok = valider_sens(sens)
    montant_ok = valider_montant(montant, "montant")

    if sens_ok == SENS_REPORT_DEFICITAIRE:
        with contexte_tenant(session, tenant_id):
            _mission_ou_404(session, mission_id)
            row = session.execute(
                text(
                    "INSERT INTO report_deficitaire_mission (tenant_id, "
                    "mission_id, montant) VALUES (:t, :m, :mt) "
                    "ON CONFLICT (mission_id) DO UPDATE SET "
                    "montant = EXCLUDED.montant, mis_a_jour_le = now() "
                    "RETURNING id, montant"
                ),
                {"t": tenant_id, "m": mission_id, "mt": montant_ok},
            ).mappings().one()
            append_journal(
                session,
                tenant_id=tenant_id,
                mission_id=mission_id,
                acteur=acteur,
                action=ACTION_SAISIE_REPORT,
                charge_utile={"report_deficitaire": str(montant_ok)},
            )
        # Pas de commit ici : get_session committe en fin de requête.
        return {
            "mission_id": mission_id,
            "report_deficitaire": str(Decimal(str(row["montant"]))),
            "note": NOTE_RESULTAT_FISCAL,
        }

    libelle_ok = valider_libelle(libelle)
    reference = str(reference_cgi or "").strip() or None
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "INSERT INTO retraitement_fiscal (tenant_id, mission_id, "
                "sens, libelle, montant, reference_cgi) "
                "VALUES (:t, :m, :s, :l, :mt, :r) "
                "RETURNING id, sens, libelle, montant, reference_cgi, "
                "cree_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "s": sens_ok,
                "l": libelle_ok,
                "mt": montant_ok,
                "r": reference,
            },
        ).mappings().one()
        retraitement = _serialiser_retraitement(dict(row))
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_SAISIE_RETRAITEMENT,
            charge_utile={
                "retraitement_id": retraitement["id"],
                "sens": sens_ok,
                "libelle": libelle_ok,
                "montant": str(montant_ok),
                "reference_cgi": reference,
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "retraitement": retraitement,
        "note": NOTE_RESULTAT_FISCAL,
    }


def supprimer_retraitement(
    session: Session,
    tenant_id: int,
    mission_id: int,
    retraitement_id: object,
    acteur: str,
) -> dict[str, Any]:
    """Supprime une ligne de retraitement par id — clic humain.

    Ligne inconnue, d'une autre mission ou hors tenant (RLS) →
    :class:`ErreurResultatFiscalIntrouvable` (404). Id illisible →
    :class:`ErreurResultatFiscalInvalide` (422). Journalise
    :data:`ACTION_SUPPRESSION_RETRAITEMENT`.
    """
    from backend.moteur.journal import append_journal

    try:
        rid = int(str(retraitement_id))
    except (TypeError, ValueError) as e:
        raise ErreurResultatFiscalInvalide(
            f"identifiant de retraitement illisible : {retraitement_id!r}"
        ) from e
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "DELETE FROM retraitement_fiscal "
                "WHERE id = :r AND mission_id = :m "
                "RETURNING id, sens, libelle, montant"
            ),
            {"r": rid, "m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurResultatFiscalIntrouvable(
                f"retraitement {rid} introuvable pour la mission "
                f"{mission_id}"
            )
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_SUPPRESSION_RETRAITEMENT,
            charge_utile={
                "retraitement_id": int(row["id"]),
                "sens": str(row["sens"]),
                "libelle": str(row["libelle"]),
                "montant": str(Decimal(str(row["montant"]))),
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "retraitement_supprime": int(row["id"]),
        "note": NOTE_RESULTAT_FISCAL,
    }


def _retraitements_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, sens, libelle, montant, reference_cgi, cree_le "
            "FROM retraitement_fiscal WHERE mission_id = :m ORDER BY id"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _report_deficitaire_mission(
    session: Session, mission_id: int
) -> Decimal | None:
    montant = session.execute(
        text(
            "SELECT montant FROM report_deficitaire_mission "
            "WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()
    return None if montant is None else Decimal(str(montant))


def _soldes_resultat_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND (compte LIKE '6%' OR compte LIKE '7%' "
            "OR compte LIKE '8%') ORDER BY compte"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_resultat_fiscal_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Tableau de passage de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurResultatFiscalIntrouvable`
    (404 côté route). Se construit toujours : sans balance (aucun
    compte 6x/7x), ``disponible=false`` et
    ``synthese.statut="indisponible"`` — les retraitements saisis
    restent listés et les clés présentes.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        retraitements = [
            _serialiser_retraitement(r)
            for r in _retraitements_mission(session, mission_id)
        ]
        report = _report_deficitaire_mission(session, mission_id)
        soldes = _soldes_resultat_mission(session, mission_id)

    vue = calculer_passage_fiscal(soldes, retraitements, report)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue


def reprendre_is_du_estime(
    session: Session, tenant_id: int, mission_id: int, acteur: str
) -> dict[str, Any]:
    """Reprend l'IS théorique calculé comme IS dû estimé — clic humain.

    BONUS : écrit l'IS théorique du tableau de passage dans
    ``is_du_estime_mission`` en RÉUTILISANT
    :func:`backend.plateforme.acomptes.saisir_acompte` (aucune
    duplication d'insertion — même upsert, même journalisation
    ``saisie_is_du_estime``). Refusé (422) si le passage est
    indisponible (pas de balance) : rien à reprendre. Journalise en
    plus :data:`ACTION_REPRISE_IS_DU` pour tracer l'origine.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.acomptes import (
        NATURE_IS_DU_ESTIME,
        saisir_acompte,
    )

    vue = vue_resultat_fiscal_mission(session, tenant_id, mission_id)
    if not vue["disponible"]:
        raise ErreurResultatFiscalInvalide(
            "passage indisponible (balance sans comptes 6x/7x) — aucun "
            "IS théorique à reprendre comme IS dû estimé"
        )
    is_theorique = vue["is_theorique"]
    saisie = saisir_acompte(
        session,
        tenant_id,
        mission_id,
        NATURE_IS_DU_ESTIME,
        is_theorique,
        acteur=acteur,
    )
    with contexte_tenant(session, tenant_id):
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_REPRISE_IS_DU,
            charge_utile={
                "is_theorique": is_theorique,
                "resultat_fiscal": vue["resultat_fiscal"],
            },
        )
    return {
        "mission_id": mission_id,
        "is_du_estime": saisie["is_du_estime"],
        "source": "resultat_fiscal_theorique",
        "note": NOTE_RESULTAT_FISCAL,
    }
