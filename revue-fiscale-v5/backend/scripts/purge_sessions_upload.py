"""Purge des sessions d'upload pièces orphelines (TTL).

Parcourt chaque tenant avec SET LOCAL (jamais SET nu).
Ne touche pas aux pièces déjà rattachées (contribuable_id NOT NULL).

Usage :
  cd revue-fiscale-v5
  .venv/bin/python -m backend.scripts.purge_sessions_upload
  .venv/bin/python -m backend.scripts.purge_sessions_upload --dry-run
  .venv/bin/python -m backend.scripts.purge_sessions_upload --ttl-heures 48
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from sqlalchemy import text

from backend.abonne.pieces_contribuable_service import (
    purger_orphelines,
    ttl_session_heures,
)
from backend.db import Fabrique
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Purge sessions upload pièces sans fiche client (TTL)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Liste sans supprimer",
    )
    parser.add_argument(
        "--ttl-heures",
        type=int,
        default=None,
        help=f"Âge min. (défaut config={ttl_session_heures()})",
    )
    args = parser.parse_args(argv)
    age = (
        timedelta(hours=args.ttl_heures)
        if args.ttl_heures is not None
        else None
    )

    session = Fabrique()
    try:
        tenants = session.execute(
            text("SELECT id, denomination FROM tenant ORDER BY id")
        ).mappings().all()
        total_pieces = 0
        total_sessions = 0
        for t in tenants:
            tid = int(t["id"])
            with contexte_tenant(session, tid):
                res = purger_orphelines(
                    session,
                    plus_vieux_que=age,
                    dry_run=args.dry_run,
                )
            effacer_contexte_tenant(session)
            n_s = int(res.get("sessions_purgées") or len(res.get("sessions") or []))
            n_p = int(res.get("pieces_supprimees") or 0)
            if n_s or (args.dry_run and res.get("sessions")):
                print(
                    f"tenant {tid} ({t['denomination']}) : "
                    f"sessions={n_s} pieces={n_p} "
                    f"ttl={res.get('ttl_heures')}h "
                    f"{'DRY' if args.dry_run else 'OK'}"
                )
            total_pieces += n_p
            total_sessions += n_s
            if not args.dry_run:
                session.commit()
            else:
                session.rollback()
        print(
            f"Total : sessions={total_sessions} pieces={total_pieces} "
            f"({'dry-run' if args.dry_run else 'purgé'})"
        )
        return 0
    except Exception as e:
        session.rollback()
        print(f"FAIL — {e}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
