"""Alias historique → ``demo_commercial`` (chemin unique : ``make demolot``).

Usage ::

    make seed
    make demolot          # recommandé
    make demo-mission     # alias
"""
from __future__ import annotations

import sys

from backend.scripts.demo_commercial import main

if __name__ == "__main__":
    sys.exit(main())
