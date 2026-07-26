"""Mapping plan de comptes → SYSCOHADA.

Par defaut : identite. Remap optionnel via YAML {source: cible}.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from backend.socle.erreurs import ErreurMapping
from backend.socle.modeles import LigneBalance


def charger_remap(chemin: str | Path | None) -> dict[str, str]:
    """Charge un YAML de remap. None ou absent → mapping identite (dict vide)."""
    if chemin is None:
        return {}
    path = Path(chemin)
    if not path.exists():
        raise ErreurMapping(f"fichier de mapping introuvable : {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ErreurMapping("le mapping YAML doit etre un objet {source: cible}")
    return {str(k): str(v) for k, v in data.items()}


def appliquer_mapping(
    lignes: list[LigneBalance],
    remap: dict[str, str] | None = None,
) -> list[LigneBalance]:
    """Applique le remap (identite si remap vide ou None)."""
    table = remap or {}
    sortie: list[LigneBalance] = []
    for ligne in lignes:
        compte = table.get(ligne.compte, ligne.compte)
        sortie.append(
            LigneBalance(
                compte=compte,
                libelle=ligne.libelle,
                debit=ligne.debit,
                credit=ligne.credit,
            )
        )
    return sortie
