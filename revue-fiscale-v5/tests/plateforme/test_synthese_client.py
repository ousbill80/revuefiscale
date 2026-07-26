"""Tests unitaires — coercition du JSON LLM de synthèse client (Data Room)."""
from __future__ import annotations

import pytest

from backend.plateforme.synthese_client import (
    ELEMENTS_MAX,
    GRAVITE_DEFAUT,
    ErreurSyntheseClient,
    _parser_json_llm,
    normaliser_contenu_synthese,
    sources_du_contexte,
)

SOURCES = {"memoire:12", "piece:123", "risque:40", "mission:7", "score_risque"}


def test_contenu_complet_valide():
    brut = {
        "resume": "  Dossier globalement à jour.  ",
        "points_cles": [
            {"texte": "NCC confirmé par la DFE.", "sources": ["piece:123"]}
        ],
        "incoherences": [
            {
                "description": "Adresse siège différente du bail.",
                "sources": ["piece:123", "memoire:12"],
                "gravite": "haute",
            }
        ],
        "recommandations": [
            {"texte": "Planifier une revue du risque TVA.", "sources": ["risque:40"]}
        ],
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["resume"] == "Dossier globalement à jour."
    assert out["points_cles"] == [
        {"texte": "NCC confirmé par la DFE.", "sources": ["piece:123"]}
    ]
    assert out["incoherences"][0]["gravite"] == "haute"
    assert out["incoherences"][0]["sources"] == ["piece:123", "memoire:12"]
    assert out["recommandations"][0]["sources"] == ["risque:40"]


def test_sources_inconnues_retirees():
    brut = {
        "resume": "r",
        "points_cles": [
            {
                "texte": "Point sourcé douteux.",
                "sources": ["piece:999", "memoire:12", "invente:1", ""],
            }
        ],
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["points_cles"][0]["sources"] == ["memoire:12"]


def test_sources_dedoublonnees():
    brut = {
        "points_cles": [
            {"texte": "x", "sources": ["memoire:12", "memoire:12"]}
        ]
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["points_cles"][0]["sources"] == ["memoire:12"]


@pytest.mark.parametrize("gravite", ["critique", "", None, 3, "URGENT"])
def test_gravite_invalide_devient_moyenne(gravite):
    brut = {
        "incoherences": [
            {"description": "Écart constaté.", "sources": [], "gravite": gravite}
        ]
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["incoherences"][0]["gravite"] == GRAVITE_DEFAUT == "moyenne"


def test_gravite_normalisee_casse():
    brut = {
        "incoherences": [
            {"description": "d", "sources": [], "gravite": " Haute "}
        ]
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["incoherences"][0]["gravite"] == "haute"


def test_elements_sans_texte_ignores():
    brut = {
        "points_cles": [
            {"texte": "  ", "sources": ["memoire:12"]},
            "chaîne brute",
            None,
            {"sources": ["memoire:12"]},
            {"texte": "valide"},
        ],
        "incoherences": [{"description": "", "gravite": "haute"}],
        "recommandations": [{"texte": ""}],
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert out["points_cles"] == [{"texte": "valide", "sources": []}]
    assert out["incoherences"] == []
    assert out["recommandations"] == []


def test_structures_invalides_tolerees():
    for brut in (None, [], "texte", 42, {"points_cles": "pas une liste"}):
        out = normaliser_contenu_synthese(brut, SOURCES)
        assert out == {
            "resume": "",
            "points_cles": [],
            "incoherences": [],
            "recommandations": [],
        }


def test_listes_plafonnees():
    brut = {
        "points_cles": [
            {"texte": f"point {i}"} for i in range(ELEMENTS_MAX + 10)
        ]
    }
    out = normaliser_contenu_synthese(brut, SOURCES)
    assert len(out["points_cles"]) == ELEMENTS_MAX


def test_sources_du_contexte():
    contexte = {
        "identite": {"denomination": "ACME"},
        "memoire": [{"source": "memoire:12"}],
        "risques": [{"source": "risque:40"}],
        "pieces": [{"source": "piece:123"}],
        "missions": [{"source": "mission:7"}],
    }
    assert sources_du_contexte(contexte) == SOURCES


def test_sources_du_contexte_vide():
    assert sources_du_contexte({}) == {"score_risque"}


def test_parser_json_tolerant():
    assert _parser_json_llm('{"resume": "ok"}') == {"resume": "ok"}
    assert _parser_json_llm('Voici :\n```json\n{"resume": "ok"}\n```') == {
        "resume": "ok"
    }


def test_parser_json_invalide():
    with pytest.raises(ErreurSyntheseClient):
        _parser_json_llm("aucun json ici")
    with pytest.raises(ErreurSyntheseClient):
        _parser_json_llm('["liste", "pas objet"]')
