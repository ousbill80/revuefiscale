"""Smoke DB : corpus cgici ingéré → recherche hybride trouve un article connu."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from backend.corpus.cgici import assembler_texte, extraire_texte_page
from backend.corpus.ingestion import _decouper_articles, ingerer_document
from backend.corpus.recherche import recherche_hybride

pytestmark = pytest.mark.db

_RACINE = Path(__file__).resolve().parents[2]
_CACHE_P3 = _RACINE / "corpus_sources" / "cgici_2026" / "pages" / "page-3.html"
_TEXTE = _RACINE / "corpus_sources" / "CGI-CI-2026-cgici.txt"


@pytest.fixture
def texte_cgi_minimal() -> str:
    if _CACHE_P3.is_file():
        return assembler_texte({3: extraire_texte_page(_CACHE_P3.read_bytes())})
    if _TEXTE.is_file():
        brut = _TEXTE.read_text(encoding="utf-8")
        # Garde un extrait autour d'Art. 18 pour smoke rapide
        idx = brut.find("Art. 18")
        if idx >= 0:
            return brut[max(0, idx - 200) : idx + 8000]
    pytest.skip("Cache cgici absent — lancer make ingerer-cgici DRY_RUN=1")


def test_ingestion_cgici_minimale_et_recherche(session, texte_cgi_minimal: str):
    arts = _decouper_articles(texte_cgi_minimal)
    assert len(arts) >= 2
    assert any(r == "18" for r, _, _ in arts)

    r = ingerer_document(
        session,
        titre="[TEST] CGI cgici smoke",
        type="cgi",
        millesime=2026,
        texte_brut=texte_cgi_minimal,
        fichier_uri="https://cgici.com/V2026/page-3.html",
    )
    assert r.articles >= 2
    assert r.fragments >= 2

    hits = recherche_hybride(
        session,
        "bénéfice net déduction charges article 18",
        limite=8,
        types=["cgi"],
    )
    assert hits, "recherche hybride devrait trouver Art. 18"
    refs = [h["reference"] for h in hits]
    assert "18" in refs or any(str(ref).startswith("18") for ref in refs)

    n = session.execute(
        text(
            "SELECT count(*) FROM source_document "
            "WHERE titre = :t AND type = 'cgi'"
        ),
        {"t": "[TEST] CGI cgici smoke"},
    ).scalar_one()
    assert n >= 1
