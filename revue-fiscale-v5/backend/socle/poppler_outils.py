"""Disponibilité Poppler (pdftotext / pdftoppm) — messages clairs, pas d'OCR local."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


MESSAGE_PDFTOTEXT_ABSENT = (
    "Extraction du texte PDF indisponible sur ce serveur. "
    "Joignez un fichier texte, ou saisissez manuellement."
)

MESSAGE_PDFTOPPM_ABSENT = (
    "Analyse des PDF scannés indisponible sur ce serveur. "
    "Joignez une image ou un fichier texte, ou saisissez manuellement."
)

MESSAGE_VISION_SANS_IMAGE = (
    "Le document scanné n'a pas pu être préparé pour l'analyse visuelle. "
    "Joignez une image plus nette ou saisissez manuellement."
)


def pdftotext_disponible() -> bool:
    return shutil.which("pdftotext") is not None


def pdftoppm_disponible() -> bool:
    return shutil.which("pdftoppm") is not None


def etat_poppler() -> dict[str, Any]:
    """État ops (health / diagnostics) — sans secrets."""
    txt = pdftotext_disponible()
    ppm = pdftoppm_disponible()
    return {
        "pdftotext": txt,
        "pdftoppm": ppm,
        "ok": txt and ppm,
        "conseil": None
        if (txt and ppm)
        else (
            "Installer poppler-utils (Linux) ou brew install poppler (macOS) "
            "pour PDF texte + scan vision."
        ),
    }


def chemin_pdftotext() -> str | None:
    return shutil.which("pdftotext")


def chemin_pdftoppm() -> str | None:
    return shutil.which("pdftoppm")


def pdf_vers_images_vision(
    contenu: bytes,
    *,
    max_pages: int | None = None,
    dpi: int | None = None,
    jpeg_quality: int | None = None,
    plafond_pages: int = 12,
) -> tuple[list[tuple[str, bytes]], str | None]:
    """Rasterise les premières pages PDF en JPEG compressé pour vision.

    Retourne ``(images, avertissement_optionnel)``. JPEG plutôt que PNG pour
    réduire le payload base64 (latence upload + tokens vision).
    """
    from backend.config import config as cfg

    pages_max = int(
        max_pages
        if max_pages is not None
        else (cfg.llm_vision_pdf_max_pages or 3)
    )
    resolution = int(dpi if dpi is not None else (cfg.llm_vision_pdf_dpi or 140))
    qualite = int(
        jpeg_quality
        if jpeg_quality is not None
        else (cfg.llm_vision_jpeg_quality or 82)
    )
    pages_max = max(1, min(pages_max, plafond_pages))
    resolution = max(72, min(resolution, 300))
    qualite = max(40, min(qualite, 95))

    binaire = chemin_pdftoppm()
    if not binaire:
        return [], MESSAGE_PDFTOPPM_ABSENT

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        racine = Path(tmp)
        pdf = racine / "doc.pdf"
        pdf.write_bytes(contenu)
        prefixe = racine / "page"
        try:
            subprocess.run(  # noqa: S603
                [
                    binaire,
                    "-jpeg",
                    "-jpegopt",
                    f"quality={qualite}",
                    "-f",
                    "1",
                    "-l",
                    str(pages_max),
                    "-r",
                    str(resolution),
                    str(pdf),
                    str(prefixe),
                ],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("pdftoppm_echec raison=%s", e)
            return [], (
                "Conversion du PDF scanné impossible pour le moment. "
                "Joignez une image ou un fichier texte, ou saisissez manuellement."
            )
        images: list[tuple[str, bytes]] = []
        octets_total = 0
        for chemin in sorted(racine.glob("page*.jpg")) + sorted(
            racine.glob("page*.jpeg")
        ):
            brut_img = chemin.read_bytes()
            # Garde-fou taille requête vision (~2 Mo / page JPEG)
            if len(brut_img) <= 2_000_000:
                images.append(("image/jpeg", brut_img))
                octets_total += len(brut_img)
        duree_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "pdf_rasterisation pages=%s dpi=%s jpeg_q=%s octets=%s duree_ms=%s",
            len(images),
            resolution,
            qualite,
            octets_total,
            duree_ms,
        )
        if not images:
            return [], (
                "Le PDF scanné n'a produit aucune page lisible. "
                "Joignez une image plus nette ou saisissez manuellement."
            )
        return images, None
