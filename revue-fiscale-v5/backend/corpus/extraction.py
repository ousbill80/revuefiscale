"""Extraction texte depuis PDF / Markdown / TXT pour ingestion corpus."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ErreurExtraction(ValueError):
    """Fichier illisible ou outil manquant."""


EXTENSIONS_TEXTE = {".md", ".markdown", ".txt", ".text"}
EXTENSIONS_PDF = {".pdf"}


def extraire_texte(chemin: Path) -> str:
    """Lit le texte d'une source réglementaire.

    PDF : ``pdftotext`` (poppler). Markdown / TXT : lecture UTF-8.
    N'interprète aucun droit positif.
    """
    path = chemin.expanduser().resolve()
    if not path.is_file():
        raise ErreurExtraction(f"Fichier introuvable : {path}")

    suffixe = path.suffix.lower()
    if suffixe in EXTENSIONS_TEXTE:
        texte = path.read_text(encoding="utf-8")
        if not texte.strip():
            raise ErreurExtraction(f"Fichier vide : {path}")
        return texte

    if suffixe in EXTENSIONS_PDF:
        return _extraire_pdf(path)

    raise ErreurExtraction(
        f"Extension non supportée ({suffixe}). "
        "Déposer un .pdf, .md ou .txt dans corpus_sources/."
    )


def _extraire_pdf(path: Path) -> str:
    binaire = shutil.which("pdftotext")
    if not binaire:
        raise ErreurExtraction(
            "pdftotext introuvable (poppler). "
            "Installer poppler-utils / brew install poppler, "
            "ou fournir un .md / .txt déjà extrait."
        )
    try:
        resultat = subprocess.run(  # noqa: S603 — binaire poppler résolu via which
            [binaire, "-layout", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        raise ErreurExtraction(f"Timeout pdftotext sur {path.name}") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()[:500]
        raise ErreurExtraction(
            f"Échec pdftotext sur {path.name}" + (f" : {detail}" if detail else "")
        ) from e

    texte = resultat.stdout or ""
    if not texte.strip():
        raise ErreurExtraction(
            f"PDF sans texte extractible (scan image ?) : {path.name}. "
            "Fournir une version OCR / Markdown."
        )
    return texte
