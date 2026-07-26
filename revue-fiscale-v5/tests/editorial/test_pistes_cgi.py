"""Pistes CGI 2026 — catalogue + enrichissement (pas de visa)."""
from __future__ import annotations

from backend.editorial.pistes_cgi import (
    SOURCE_PROPOSITION,
    charger_catalogue_pistes,
    enrichir_entrees_file,
    ids_entrees_pistes,
    index_pistes_par_entree,
)


def test_catalogue_pistes_cgi_min_sept():
    cat = charger_catalogue_pistes()
    assert cat["lot"] == "cgi_2026_pistes_claires"
    pistes = cat["pistes"]
    assert len(pistes) >= 7
    ids = ids_entrees_pistes(cat)
    assert "BIC-CHG-18G-DONS#0" in ids
    assert "BIC-CHG-18G-DONS#1" in ids
    assert "BIC-CHG-18A4-ADMIN#1" in ids
    assert "BIC-CHG-18A6-SOUSCAP#3" in ids
    assert "OBL-108-HONORAIRES#1" in ids
    assert "OBL-36BIS-CBCR#2" in ids
    assert "BIC-CHG-18A3-FRAISSIEGE#2" in ids


def test_chaque_piste_a_extrait_et_statut_humain():
    for p in charger_catalogue_pistes()["pistes"]:
        assert p["rule_id"]
        assert p["entree_id"]
        assert p["extrait_cgi"]
        assert p["suggestion"]
        assert p["statut_editorial"] == "a_valider_humain"
        assert p.get("article_corpus")


def test_enrichir_entrees_file_badge_cgi():
    liens = {
        "BIC-CHG-18G-DONS#0": {
            "piste_cgi": True,
            "piste_id": "C1-18G-DONS-taux",
            "proposition_id": 99,
        }
    }
    entrees = [
        {
            "id": "BIC-CHG-18G-DONS#0",
            "identifiant": "BIC-CHG-18G-DONS",
            "texte": "taux",
            "piste_annexe": False,
        },
        {
            "id": "PAT-272-PATENTE#0",
            "identifiant": "PAT-272-PATENTE",
            "texte": "date",
            "piste_annexe": True,
        },
    ]
    out = enrichir_entrees_file(entrees, liens)
    assert out[0]["piste_cgi"] is True
    assert out[0]["proposition_id"] == 99
    assert out[0]["piste_sourcee"] is True
    assert out[1]["piste_cgi"] is False
    assert out[1]["piste_sourcee"] is True  # déjà Annexe


def test_index_par_entree_couvre_catalogue():
    cat = charger_catalogue_pistes()
    idx = index_pistes_par_entree(cat)
    assert len(idx) == len(cat["pistes"])
    assert SOURCE_PROPOSITION == "cgi_2026_croisement"
