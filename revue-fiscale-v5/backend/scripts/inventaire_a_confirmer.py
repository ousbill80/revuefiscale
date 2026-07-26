"""CLI — inventaire des ``a_confirmer`` du référentiel (lecture seule).

Usage :
  python -m backend.scripts.inventaire_a_confirmer
  python -m backend.scripts.inventaire_a_confirmer --json-stdout
  python -m backend.scripts.inventaire_a_confirmer --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Garantit l'import ``backend.*`` depuis la racine du dépôt.
_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.editorial.inventaire_a_confirmer import (  # noqa: E402
    construire_inventaire,
    ecrire_artefacts,
    rendre_csv,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventorie les mentions a_confirmer des YAML referentiel/*.yaml. "
            "N'invente aucun taux/article ; n'écrit aucune purge."
        )
    )
    parser.add_argument(
        "--racine",
        type=Path,
        default=None,
        help="Répertoire referentiel/ (défaut : <projet>/referentiel)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calcule l'inventaire sans écrire MD/JSON/CSV",
    )
    parser.add_argument(
        "--json-stdout",
        action="store_true",
        help="Affiche l'inventaire JSON complet sur stdout",
    )
    parser.add_argument(
        "--csv-stdout",
        action="store_true",
        help="Affiche l'inventaire CSV (checklist fiscaliste) sur stdout",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        inventaire = construire_inventaire(args.racine)
        inventaire["chemins_ecrits"] = {}
    else:
        inventaire = ecrire_artefacts(args.racine)

    if args.csv_stdout:
        print(rendre_csv(inventaire), end="")
    elif args.json_stdout:
        print(json.dumps(inventaire, ensure_ascii=False, indent=2))
    else:
        print(
            f"Mentions a_confirmer : {inventaire['total_mentions']} "
            f"sur {inventaire['total_regles_concernees']} règles"
        )
        for cat, n in inventaire["comptes_par_categorie"].items():
            print(f"  {cat}: {n}")
        print("Priorité éditoriale :")
        for p, n in inventaire["comptes_par_priorite"].items():
            print(f"  {p}: {n}")
        print(f"Empreinte : {inventaire['empreinte']}")
        for libelle, chemin in inventaire.get("chemins_ecrits", {}).items():
            print(f"Écrit ({libelle}) : {chemin}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
