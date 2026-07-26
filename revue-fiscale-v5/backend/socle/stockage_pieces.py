"""Stockage local des pièces de mission (dev / mono-nœud)."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

# Racine locale — hors dépôt Git recommandé (voir .gitignore).
_RACINE = Path(
    os.environ.get(
        "PIECES_DIR",
        str(Path(__file__).resolve().parents[2] / "var" / "pieces"),
    )
)

_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")


def racine_pieces() -> Path:
    return _RACINE


def _nom_sur(nom: str) -> str:
    base = Path(nom).name.strip() or "fichier"
    nettoye = _SAFE.sub("_", base)[:180]
    return nettoye or "fichier"


def ecrire_piece(
    tenant_id: int,
    mission_id: int,
    nom_fichier: str,
    contenu: bytes,
) -> str:
    """Écrit le fichier et retourne le chemin relatif (stocké en base)."""
    dossier = _RACINE / str(tenant_id) / str(mission_id)
    dossier.mkdir(parents=True, exist_ok=True)
    rel = f"{tenant_id}/{mission_id}/{uuid.uuid4().hex}_{_nom_sur(nom_fichier)}"
    cible = _RACINE / rel
    cible.write_bytes(contenu)
    return rel.replace("\\", "/")


def ecrire_piece_contribuable(
    tenant_id: int,
    ancre: str,
    nom_fichier: str,
    contenu: bytes,
) -> str:
    """Écrit une pièce d'identité contribuable sous var/pieces/{tenant}/c/{ancre}/.

    ``ancre`` = ``session_<uuid>`` (avant création) ou ``id_<contribuable_id>``.
    """
    ancre_safe = _SAFE.sub("_", (ancre or "orphan").strip())[:80] or "orphan"
    dossier = _RACINE / str(tenant_id) / "c" / ancre_safe
    dossier.mkdir(parents=True, exist_ok=True)
    rel = (
        f"{tenant_id}/c/{ancre_safe}/"
        f"{uuid.uuid4().hex}_{_nom_sur(nom_fichier)}"
    )
    cible = _RACINE / rel
    cible.write_bytes(contenu)
    return rel.replace("\\", "/")


def chemin_absolu(relatif: str) -> Path:
    rel = relatif.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise ValueError("chemin de pièce invalide")
    return _RACINE / rel


def lire_piece(relatif: str) -> bytes:
    return chemin_absolu(relatif).read_bytes()


def supprimer_fichier(relatif: str) -> None:
    try:
        chemin_absolu(relatif).unlink(missing_ok=True)
    except OSError:
        pass
