"""Revue analytique N / N-1 — réflexe fondamental du réviseur.

Compare les soldes de l'exercice contrôlé (N) à ceux de l'exercice
précédent (N-1) du même contribuable pour repérer les variations
anormales : CA qui chute, charges qui explosent, comptes qui
apparaissent ou disparaissent. Chaque variation significative appelle
une explication.

La fonction de comparaison est pure (aucun accès DB) — testable seule.
Lecture seule : aucune écriture, aucune migration.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# Seuils cumulatifs d'une « variation forte » : il faut dépasser LES DEUX.
SEUIL_VARIATION_PCT: Final = Decimal("20")            # 20 %
SEUIL_VARIATION_FCFA: Final = Decimal("1000000")      # 1 000 000 FCFA

CLASSEMENT_APPARITION: Final = "apparition"
CLASSEMENT_DISPARITION: Final = "disparition"
CLASSEMENT_VARIATION_FORTE: Final = "variation_forte"
CLASSEMENT_STABLE: Final = "stable"


class ErreurRevueAnalytique(Exception):
    """Mission introuvable ou revue impossible."""


# ── Fonction pure (sans DB) ────────────────────────────────────────


def _agreger_par_compte(
    soldes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Agrège débit/crédit par compte → solde net (débit - crédit)."""
    par_compte: dict[str, dict[str, Any]] = {}
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte:
            continue
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        entree = par_compte.setdefault(
            compte, {"libelle": None, "solde": Decimal("0")}
        )
        entree["solde"] += debit - credit
        if not entree["libelle"] and ligne.get("libelle"):
            entree["libelle"] = str(ligne["libelle"])
    return par_compte


def _classer(
    present_n: bool,
    present_n1: bool,
    variation: Decimal,
    variation_pct: Decimal | None,
) -> str:
    if present_n and not present_n1:
        return CLASSEMENT_APPARITION
    if present_n1 and not present_n:
        return CLASSEMENT_DISPARITION
    if (
        variation_pct is not None
        and abs(variation_pct) > SEUIL_VARIATION_PCT
        and abs(variation) > SEUIL_VARIATION_FCFA
    ):
        return CLASSEMENT_VARIATION_FORTE
    return CLASSEMENT_STABLE


def comparer_soldes(
    soldes_n: list[dict[str, Any]],
    soldes_n1: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare deux jeux de soldes {compte, libelle, debit, credit}.

    Pure — aucun accès DB. Retourne :
      - lignes : triées par variation absolue décroissante, chacune avec
        compte, libelle, solde_n, solde_n1, variation, variation_pct,
        sens (hausse/baisse/stable) et classement (apparition,
        disparition, variation_forte, stable) ;
      - totaux_par_classe : totaux N / N-1 / variation par classe de
        compte SYSCOHADA (1 à 7).
    """
    n = _agreger_par_compte(soldes_n)
    n1 = _agreger_par_compte(soldes_n1)

    lignes: list[dict[str, Any]] = []
    for compte in sorted(set(n) | set(n1)):
        present_n = compte in n
        present_n1 = compte in n1
        solde_n = n[compte]["solde"] if present_n else Decimal("0")
        solde_n1 = n1[compte]["solde"] if present_n1 else Decimal("0")
        variation = solde_n - solde_n1
        variation_pct = (
            (variation / abs(solde_n1)) * 100 if solde_n1 != 0 else None
        )
        if variation > 0:
            sens = "hausse"
        elif variation < 0:
            sens = "baisse"
        else:
            sens = "stable"
        libelle = (
            (n.get(compte) or {}).get("libelle")
            or (n1.get(compte) or {}).get("libelle")
        )
        lignes.append(
            {
                "compte": compte,
                "libelle": libelle,
                "solde_n": float(solde_n),
                "solde_n1": float(solde_n1),
                "variation": float(variation),
                "variation_pct": (
                    round(float(variation_pct), 2)
                    if variation_pct is not None
                    else None
                ),
                "sens": sens,
                "classement": _classer(
                    present_n, present_n1, variation, variation_pct
                ),
            }
        )

    lignes.sort(key=lambda x: abs(x["variation"]), reverse=True)

    totaux: dict[str, dict[str, Decimal]] = {}
    for ligne in lignes:
        classe = ligne["compte"][:1]
        if classe not in {"1", "2", "3", "4", "5", "6", "7"}:
            continue
        t = totaux.setdefault(
            classe,
            {"total_n": Decimal("0"), "total_n1": Decimal("0")},
        )
        t["total_n"] += Decimal(str(ligne["solde_n"]))
        t["total_n1"] += Decimal(str(ligne["solde_n1"]))
    totaux_par_classe = [
        {
            "classe": int(classe),
            "total_n": float(t["total_n"]),
            "total_n1": float(t["total_n1"]),
            "variation": float(t["total_n"] - t["total_n1"]),
        }
        for classe, t in sorted(totaux.items())
    ]

    return {"lignes": lignes, "totaux_par_classe": totaux_par_classe}


# ── Accès DB (contexte tenant obligatoire) ─────────────────────────


def _soldes_mission(session: Session, mission_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m ORDER BY compte"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def trouver_mission_n1(
    session: Session, contribuable_id: int, exercice: int
) -> dict[str, Any] | None:
    """Mission du même contribuable sur exercice-1 — la plus récente.

    Contexte tenant déjà posé (RLS).
    """
    row = session.execute(
        text(
            "SELECT id, exercice FROM mission "
            "WHERE contribuable_id = :c AND exercice = :e "
            "ORDER BY cree_le DESC, id DESC LIMIT 1"
        ),
        {"c": contribuable_id, "e": exercice - 1},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def revue_analytique_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Revue analytique N / N-1 de la mission (lecture seule, RLS).

    disponible=false si pas de mission N-1 ou pas de soldes comparables.
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, contribuable_id, exercice FROM mission "
                "WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurRevueAnalytique(
                f"mission {mission_id} introuvable pour ce tenant"
            )

        exercice_n = int(mission["exercice"])
        indisponible = {
            "disponible": False,
            "exercice_n": exercice_n,
            "exercice_n1": exercice_n - 1,
            "mission_n1_id": None,
            "lignes": [],
            "totaux_par_classe": [],
        }

        mission_n1 = trouver_mission_n1(
            session, int(mission["contribuable_id"]), exercice_n
        )
        if mission_n1 is None:
            return indisponible

        soldes_n = _soldes_mission(session, mission_id)
        soldes_n1 = _soldes_mission(session, int(mission_n1["id"]))
        if not soldes_n or not soldes_n1:
            return indisponible

    comparaison = comparer_soldes(soldes_n, soldes_n1)
    return {
        "disponible": True,
        "exercice_n": exercice_n,
        "exercice_n1": exercice_n - 1,
        "mission_n1_id": int(mission_n1["id"]),
        "lignes": comparaison["lignes"],
        "totaux_par_classe": comparaison["totaux_par_classe"],
    }
