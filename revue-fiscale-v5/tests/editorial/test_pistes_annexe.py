"""Pistes Annexe 2026 — catalogue + enrichissement (pas de visa)."""
from __future__ import annotations

from backend.editorial.pistes_annexe import (
    SOURCE_PROPOSITION,
    charger_catalogue_pistes,
    enrichir_entrees_file,
    ids_entrees_pistes,
    index_pistes_par_entree,
)


def test_catalogue_huit_pistes_annexe():
    cat = charger_catalogue_pistes()
    assert cat["lot"] == "annexe_2026_pistes_claires"
    pistes = cat["pistes"]
    assert len(pistes) == 8
    ids = ids_entrees_pistes(cat)
    assert "PAT-272-PATENTE#0" in ids
    assert "RAS-92-NONRESIDENT#0" in ids
    assert "OBL-36-ETII#0" in ids
    assert "OBL-49BIS-REGISTRES#1" in ids
    assert len(ids) == 8


def test_chaque_piste_a_extrait_et_statut_humain():
    for p in charger_catalogue_pistes()["pistes"]:
        assert p["rule_id"]
        assert p["entree_id"]
        assert p["extrait_annexe"]
        assert p["suggestion"]
        assert p["statut_editorial"] == "a_valider_humain"
        assert p.get("pages")


def test_enrichir_entrees_file_badge():
    liens = {
        "PAT-272-PATENTE#0": {
            "piste_annexe": True,
            "piste_id": "A1-PAT-272-date",
            "proposition_id": 42,
        }
    }
    entrees = [
        {"id": "PAT-272-PATENTE#0", "identifiant": "PAT-272-PATENTE", "texte": "date"},
        {"id": "BIC-CHG-18G-DONS#0", "identifiant": "BIC-CHG-18G-DONS", "texte": "taux"},
    ]
    out = enrichir_entrees_file(entrees, liens)
    assert out[0]["piste_annexe"] is True
    assert out[0]["proposition_id"] == 42
    assert out[1]["piste_annexe"] is False


def test_index_par_entree_unique():
    idx = index_pistes_par_entree()
    assert len(idx) == 8
    assert SOURCE_PROPOSITION == "annexe_2026_croisement"
