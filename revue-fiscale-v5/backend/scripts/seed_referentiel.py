"""Chargement du referentiel depuis referentiel/*.yaml vers la base.

Valide chaque regle (format pivot + expressions) puis insert via
backend.editorial.publication. Regenerer Lot1 + Lots 2/3/RA avant chargement.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.editorial.publication import (
    ErreurEditorial,
    charger_regle_yaml,
    creer_version_brouillon,
    publier_version,
)
from backend.referentiel.expressions import ErreurSyntaxe, analyser

CHAMPS_REQUIS = {
    "identifiant",
    "impot",
    "reference_legale",
    "date_effet",
    "profils_applicables",
    "comptes_declencheurs",
    "nature",
    "condition_declenchement",
    "conditions_fond",
    "formule_plafonnement",
    "questions_generees",
    "resultat",
    "niveau_risque",
    "effets_croises",
}

RACINE = Path(__file__).resolve().parents[2] / "referentiel"
VERSION_LIBELLE = "v2026.7-complet"
VERSION_EMPLACEMENTS_BROUILLON = "v-emplacements-brouillon"


def _est_emplacement(regle: dict[str, object], chemin: Path) -> bool:
    identifiant = str(regle.get("identifiant", ""))
    return identifiant.startswith("EMPLACEMENT-") or "emplacements" in chemin.parts


def valider(regle: dict[str, object], *, emplacement: bool = False) -> list[str]:
    anomalies: list[str] = []
    manquants = CHAMPS_REQUIS - set(regle)
    if manquants:
        anomalies.append(f"champs absents : {sorted(manquants)}")

    for champ in ("condition_declenchement", "formule_plafonnement", "resultat"):
        expr = regle.get(champ)
        if isinstance(expr, str) and expr.strip() and expr.strip().lower() != "sans objet":
            try:
                analyser(expr)
            except ErreurSyntaxe as e:
                anomalies.append(f"{champ} : {e}")

    identifiant = str(regle.get("identifiant", ""))
    if identifiant and not emplacement and identifiant.count("-") < 2:
        anomalies.append(
            f"identifiant {identifiant!r} ne suit pas IMPOT-CATEGORIE-ARTICLE-LIBELLE"
        )
    return anomalies


def _obtenir_version(
    session: Session,
    libelle: str,
    *,
    note: str,
    autoriser_recharge_publiee: bool = False,
) -> int:
    row = session.execute(
        text(
            "SELECT id, publiee_le FROM version_referentiel WHERE libelle = :l"
        ),
        {"l": libelle},
    ).mappings().one_or_none()
    if row is None:
        return creer_version_brouillon(session, libelle, note=note)
    if row["publiee_le"] is not None and not autoriser_recharge_publiee:
        raise ErreurEditorial(
            f"{libelle} deja publiee — creer un nouveau millesime pour recharger"
        )
    session.execute(
        text(
            "DELETE FROM effet_croise WHERE source_id IN "
            "(SELECT id FROM regle_version WHERE version_referentiel_id = :v)"
        ),
        {"v": row["id"]},
    )
    session.execute(
        text("DELETE FROM regle_version WHERE version_referentiel_id = :v"),
        {"v": row["id"]},
    )
    session.flush()
    return int(row["id"])


def _lister_yaml() -> list[Path]:
    """Seed : 57 fiches metier a la racine."""
    return sorted(
        p for p in RACINE.glob("*.yaml") if not p.name.startswith("EMPLACEMENT-")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--avec-emplacements-brouillon",
        action="store_true",
        help="Ignore (compat) — EMPLACEMENT retires du harnais.",
    )
    args = parser.parse_args(argv)
    _ = args  # compat CLI

    if not RACINE.exists():
        print(f"Dossier {RACINE} absent.")
        return 0

    from backend.scripts.generer_regles_lot1_bic import generer as generer_lot1
    from backend.scripts.generer_regles_lots_234 import generer as generer_234

    try:
        generer_lot1()
        generer_234()
    except SystemExit as e:
        print(f"ECHEC generation referentiel : {e}")
        return 1

    fichiers = _lister_yaml()
    if not fichiers:
        print(f"Aucun fichier .yaml sous {RACINE}.")
        return 0

    metier: list[tuple[Path, dict[str, object]]] = []
    refusees = 0
    a_confirmer = 0

    for f in fichiers:
        try:
            regle = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            print(f"  REFUSEE  {f.relative_to(RACINE)} — YAML invalide : {e}")
            refusees += 1
            continue
        if not isinstance(regle, dict):
            print(f"  REFUSEE  {f.relative_to(RACINE)} — pas une regle")
            refusees += 1
            continue

        est_emp = _est_emplacement(regle, f)
        anomalies = valider(regle, emplacement=est_emp)
        if anomalies:
            print(f"  REFUSEE  {f.relative_to(RACINE)}")
            for a in anomalies:
                print(f"           {a}")
            refusees += 1
            continue

        n = len(regle.get("a_confirmer") or [])
        a_confirmer += n
        marque = f"  ({n} a confirmer)" if n else ""
        print(f"  ok       {regle['identifiant']}{marque}")
        metier.append((f, regle))

    if refusees:
        print(f"\n{refusees} refusee(s) — aucune insertion.")
        return 1

    engine = create_engine(config.database_url, future=True)
    with Session(engine) as session:
        try:
            version_id = _obtenir_version(
                session,
                VERSION_LIBELLE,
                note="57 fiches metier Lots 1-3 + RA (a_confirmer)",
            )
            for _f, regle in metier:
                charger_regle_yaml(session, version_id, regle)
            publier_version(session, VERSION_LIBELLE, par="seed_referentiel")
            session.commit()
        except ErreurEditorial as e:
            session.rollback()
            print(f"\nECHEC editorial : {e}")
            return 1
        except Exception as e:
            session.rollback()
            print(f"\nECHEC : {type(e).__name__}: {e}")
            return 1

    print()
    print(
        f"{len(metier)} regle(s) metier chargee(s) dans {VERSION_LIBELLE} (publiee), "
        f"{a_confirmer} mention(s) a confirmer"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
