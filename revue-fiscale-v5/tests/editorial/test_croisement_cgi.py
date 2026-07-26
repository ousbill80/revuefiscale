"""Tests croisement CGI — matching strict, pas d'invention."""
from __future__ import annotations

from backend.editorial.croisement_cgi import (
    CONTRASTES_CONNUS,
    chercher_marqueur_dans_texte,
    extraire_marqueurs,
    extraire_references_article,
    generer_markdown,
)


def test_extraire_refs_36bis_et_18g():
    refs = extraire_references_article(
        "OBL-36BIS-CBCR", "CGI 2026, art. 36 bis — CbCR"
    )
    assert any("36" in r and "bis" in r for r in refs)
    refs18 = extraire_references_article("BIC-CHG-18G-DONS", "CGI 2026, art. 18 G")
    assert "18" in refs18


def test_seuil_50000_ne_match_pas_50000000():
    mark = extraire_marqueurs("seuils 50 000")[0]
    assert mark.valeur == 50_000
    ok_false, _ = chercher_marqueur_dans_texte(
        "chiffre d'affaires au moins égal à 50 000 000 de francs", mark
    )
    assert ok_false is False
    ok_true, extr = chercher_marqueur_dans_texte(
        "lorsqu'elles dépassent 50 000 francs par an", mark
    )
    assert ok_true is True
    assert "50 000" in extr


def test_taux_25_ne_match_pas_dans_125():
    mark = extraire_marqueurs("taux 5 %")[0]
    ok, _ = chercher_marqueur_dans_texte("plus de 25 % du chiffre", mark)
    assert ok is False
    ok2, _ = chercher_marqueur_dans_texte("plafonnée à 5 % du chiffre", mark)
    assert ok2 is True


def test_contraste_18a3_connu():
    assert "BIC-CHG-18A3-FRAISSIEGE#2" in CONTRASTES_CONNUS


def test_markdown_contient_classes():
    rapport = {
        "genere_le": "2026-07-26T00:00:00Z",
        "source_document_id": 211,
        "n_articles": 1,
        "n_mentions": 0,
        "comptes": {"claire": 0, "contraste": 0, "faible": 0, "bloque": 0},
        "par_classe": {"claire": [], "contraste": [], "faible": [], "bloque": []},
    }
    md = generer_markdown(rapport)
    assert "Claire" in md
    assert "Contraste" in md
    assert "Faible" in md
    assert "Bloqué" in md
