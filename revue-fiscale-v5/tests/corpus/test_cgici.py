"""Tests extraction / index cgici.com (hors réseau pour l'unité)."""
from __future__ import annotations

from pathlib import Path

from backend.corpus.cgici import (
    assembler_texte,
    extraire_texte_page,
    filtrer_pages,
    parser_index_articles,
    pages_depuis_index,
    telecharger_corpus_cgici,
)
from backend.corpus.ingestion import _decouper_articles

# Fragment minimal inspiré du markup réel V2026 (Art. 18 + historique à exclure)
HTML_FIXTURE = """\
<!DOCTYPE HTML><html><body>
<span id="#A0018"></span>
<H6 CLASS="NoArticle">
Art. 18 &nbsp;&nbsp;&nbsp;&nbsp;<a href="#" class="ui-button">2025...</a>
</H6>
<P CLASS="ParaText">
Le bénéfice net est établi sous déduction de toutes charges.</P>
<H2 CLASS="Section">G)</H2>
<P CLASS="Liste2-Enumeree">
Les dons et libéralités sont admis dans la limite fixée par le présent Code.</P>
<div class="historique" ID="h2518">
<div class="histText">
<H6 CLASS="NoArticle">Art. 18</H6>
<P>VERSION HISTORIQUE À EXCLURE xyzzy-hist-2025</P>
</div>
</div>
<span id="#A0018b"></span>
<H6 CLASS="NoArticle">Art. 18 bis</H6>
<P CLASS="ParaText">Ne donnent pas droit à déduction, les paiements en espèces.</P>
</body></html>
"""

ARTICLE_LINK_FIXTURE = """\
function setArticleLink() {
Article.insert({art:1,aType:"",html:"page-1.html"});
Article.insert({art:18,aType:"",html:"page-3.html"});
Article.insert({art:18,aType:"bis",html:"page-3.html"});
Article.insert({art:5200,aType:"",html:"page-331.html"});
}
"""


def test_parser_index_articles():
    idx = parser_index_articles(ARTICLE_LINK_FIXTURE)
    assert len(idx) == 4
    assert idx[1].reference == "18"
    assert idx[2].reference == "18 bis"
    assert pages_depuis_index(idx) == [1, 3, 331]


def test_extraire_exclut_historique():
    texte = extraire_texte_page(HTML_FIXTURE)
    assert "bénéfice net" in texte
    assert "xyzzy-hist-2025" not in texte
    assert "Art. 18" in texte
    assert "Art. 18 bis" in texte


def test_decoupage_apres_extraction():
    texte = assembler_texte({3: extraire_texte_page(HTML_FIXTURE)})
    arts = _decouper_articles(texte)
    refs = [r for r, _, _ in arts]
    assert "18" in refs
    assert "18 bis" in refs
    corps_18 = next(c for r, _, c in arts if r == "18")
    assert "dons et libéralités" in corps_18 or "dons et liberalites" in corps_18.lower()


def test_reecriture_lpf_evite_collision():
    from backend.corpus.cgici import reecrire_refs_lpf

    brut = "Art. 18\nTexte LPF contrôle.\n\nArt. 18 bis\nSuite."
    out = reecrire_refs_lpf(brut)
    assert "Art. 5018" in out
    assert "Art. 5018 bis" in out
    assert "Art. 18\n" not in out
    arts = _decouper_articles(out)
    refs = [r for r, _, _ in arts]
    assert "5018" in refs
    assert "5018 bis" in refs


def test_assembler_prefixe_lpf():
    cgi = "Art. 18\nCharges CGI dons.\n"
    lpf = "Art. 18\nContrôle LPF.\n"
    texte = assembler_texte({3: cgi, 266: lpf}, pages_lpf={266})
    arts = _decouper_articles(texte)
    by_ref = {r: c for r, _, c in arts}
    assert "18" in by_ref
    assert "5018" in by_ref
    assert "Charges CGI" in by_ref["18"]
    assert "Contrôle LPF" in by_ref["5018"]


def test_fixture_fichier_si_present():
    """Smoke optionnel : HTML réel mis en cache par l'ingestion."""
    cache = (
        Path(__file__).resolve().parents[2]
        / "corpus_sources"
        / "cgici_2026"
        / "pages"
        / "page-3.html"
    )
    if not cache.is_file():
        return
    texte = extraire_texte_page(cache.read_bytes())
    assert "Art. 18" in texte
    arts = _decouper_articles(texte)
    assert any(r == "18" for r, _, _ in arts)


def test_filtrer_pages_from_to_offset_limit():
    pages = [1, 3, 10, 50, 100, 331]
    assert filtrer_pages(pages, from_page=10, to_page=100) == [10, 50, 100]
    assert filtrer_pages(pages, offset=2, limit=2) == [10, 50]
    assert filtrer_pages(pages, from_page=3, offset=1, limit=2) == [10, 50]


def test_seulement_manquantes_ne_retelecharge_pas(tmp_path, monkeypatch):
    """Worker parallèle : fichiers cache existants → 0 appel HTTP page."""
    repert = tmp_path / "pages"
    repert.mkdir()
    (repert / "ArticleLink.js").write_text(ARTICLE_LINK_FIXTURE, encoding="utf-8")
    html = b"<html><body><h6 class='NoArticle'>Art. 1</h6><p>x</p></body></html>"
    (repert / "page-1.html").write_bytes(html)

    appels: list[str] = []

    def _fake_telecharger(url: str, **_kwargs):
        appels.append(url)
        raise AssertionError(f"HTTP inattendu : {url}")

    monkeypatch.setattr("backend.corpus.cgici.telecharger", _fake_telecharger)
    resultat = telecharger_corpus_cgici(
        pages=[1],
        repertoire_brut=repert,
        pause_s=0,
        seulement_manquantes=True,
        telecharger_index=False,
    )
    assert appels == []
    assert 1 in resultat.pages
    assert resultat.journal[0].erreur == "cache" or resultat.journal[-1].erreur == "cache"
