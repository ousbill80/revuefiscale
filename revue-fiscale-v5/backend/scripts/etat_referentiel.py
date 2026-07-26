"""CLI — état réel du référentiel (docs/14-etat-referentiel.md).

Usage :
  python -m backend.scripts.etat_referentiel
  python -m backend.scripts.etat_referentiel --dry-run
  python -m backend.scripts.etat_referentiel --json-stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.editorial.etat_referentiel import (  # noqa: E402
    construire_etat,
    ecrire_doc,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan referentiel/*.yaml — compte EMPLACEMENT / a_confirmer / validées. "
            "N'invente aucun droit positif."
        )
    )
    parser.add_argument("--racine", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calcule sans écrire docs/14-etat-referentiel.md",
    )
    parser.add_argument("--json-stdout", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        etat = construire_etat(args.racine)
    else:
        etat = ecrire_doc(args.racine)

    if args.json_stdout:
        print(json.dumps(etat, ensure_ascii=False, indent=2))
    else:
        t = etat["totaux"]
        print(
            f"Fiches YAML : {t['fiches_yaml']} | "
            f"EMPLACEMENT : {t['fiches_marque_emplacement']} | "
            f"a_confirmer : {t['mentions_a_confirmer']} mentions "
            f"({t['fiches_avec_a_confirmer']} fiches) | "
            f"validées fiscaliste : {t['fiches_validees_fiscaliste']}"
        )
        corpus = etat["corpus"]
        statut = corpus.get("statut_editorial") or "?"
        print(
            f"Corpus : statut_editorial={statut} | "
            f"bloque_runtime={corpus.get('bloque_runtime', False)}"
        )
        msg = corpus.get("message_editorial") or corpus.get("blocage")
        if msg:
            print(f"  → {msg[:140]}…")
        if etat.get("chemin_doc"):
            print(f"Écrit : {etat['chemin_doc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
