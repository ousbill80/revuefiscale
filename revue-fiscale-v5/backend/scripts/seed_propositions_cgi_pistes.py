"""Seed propositions CGI 2026 (7 pistes) — file éditoriale, pas visa."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.db import Fabrique  # noqa: E402
from backend.editorial.pistes_cgi import deposer_propositions_pistes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dépose les ~7 propositions CGI 2026 (a_valider_humain). "
            "N'accepte / ne purge aucun a_confirmer YAML."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Créer même si une proposition ouverte existe déjà pour la piste_id",
    )
    args = parser.parse_args(argv)
    with Fabrique() as session:
        resultat = deposer_propositions_pistes(session, force=args.force)
        session.commit()
    print(json.dumps(resultat, ensure_ascii=False, indent=2, default=str))
    print(
        f"OK — {resultat['n_creees']} créée(s), "
        f"{resultat['n_ignorees']} déjà ouverte(s). "
        "Statut workflow proposition = ouverte ; statut éditorial = a_valider_humain.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
