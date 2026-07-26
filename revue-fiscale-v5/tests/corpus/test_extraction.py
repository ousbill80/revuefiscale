"""Extraction PDF/texte et découpage références CGI (ex. 18 G)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.corpus.extraction import ErreurExtraction, extraire_texte
from backend.corpus.ingestion import _decouper_articles


def test_extraire_texte_md(tmp_path: Path):
    f = tmp_path / "extrait.md"
    f.write_text("Article 18 G — dons (texte de test non opposable).\n", encoding="utf-8")
    assert "18 G" in extraire_texte(f)


def test_extraire_texte_extension_refusee(tmp_path: Path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"fake")
    with pytest.raises(ErreurExtraction, match="Extension"):
        extraire_texte(f)


def test_decoupage_reference_18_g():
    texte = (
        "Article 18 G — Les dons et liberalites.\n\n"
        "Corps de l'article pour test technique.\n\n"
        "Article DEMO-42-A — autre.\n"
    )
    arts = _decouper_articles(texte)
    refs = [r for r, _, _ in arts]
    assert "18 G" in refs
    assert "DEMO-42-A" in refs


def test_extraire_annexe_pdf_si_presente():
    """Annexe liée dans corpus_sources — extractible, sans affirmer de seuil 18 G."""
    racine = Path(__file__).resolve().parents[2]
    pdf = racine / "corpus_sources" / "Annexe-1-Annexe-Fiscale-2026.pdf"
    if not pdf.exists():
        pytest.skip("Annexe non liée dans corpus_sources")
    texte = extraire_texte(pdf)
    assert "ANNEXE" in texte.upper() or "annexe" in texte.lower()
    assert "2026" in texte
    # Garde-fou anti-purge fictive : pas de « 18 G » dans l'annexe
    assert "18 G" not in texte and "18G" not in texte.replace(" ", "")
