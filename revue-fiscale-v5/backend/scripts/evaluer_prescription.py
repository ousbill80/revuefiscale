"""Ops — évaluation auto-prescrit (R5). No-op tant que visa Lot 5 manquant.

Usage :
  cd revue-fiscale-v5
  .venv/bin/python -m backend.scripts.evaluer_prescription
  .venv/bin/python -m backend.scripts.evaluer_prescription --dry-run
  .venv/bin/python -m backend.scripts.evaluer_prescription --tenant-id 1
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.db import Fabrique
from backend.plateforme.prescription import evaluer_prescription


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "R5 auto-prescrit registre risques. "
            "Désarmé sans paramètres référentiel (visa Lot 5)."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compte sans UPDATE (même no-op si désarmé)",
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        help="Limiter à un tenant (défaut : tous)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie JSON sur stdout",
    )
    args = parser.parse_args(argv)

    session = Fabrique()
    try:
        res = evaluer_prescription(
            session,
            tenant_id=args.tenant_id,
            dry_run=args.dry_run,
        )
        if not args.dry_run and res.get("passes_prescrit"):
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(
            f"arme={res['arme']} motif={res['motif']} "
            f"tenants={res['tenants']} examines={res['examines']} "
            f"passes_prescrit={res['passes_prescrit']} "
            f"{'DRY' if args.dry_run else 'OK'}"
        )
        for d in res.get("details") or []:
            print(f"  - {d}")
        if not res["arme"]:
            print(
                "Auto-prescrit non armé — "
                "voir docs/15-bloqueurs-humains.md (Lot 5) "
                "et docs/25-registre-risques-actions.md (R5)."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
