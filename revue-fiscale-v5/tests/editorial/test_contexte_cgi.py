"""Contexte CGI + recherche filtrée — outillage revue, pas de visa."""
from __future__ import annotations

import pytest

from backend.corpus.ingestion import ingerer_document
from backend.corpus.recherche import recherche_hybride
from backend.editorial.contexte_cgi import (
    MESSAGE_AUCUN_FRAGMENT,
    construire_contexte_cgi,
    requete_depuis_references,
)
from backend.editorial.croisement_cgi import (
    ecrire_catalogue_croisement,
    enrichir_entrees_croisement,
    index_classes_croisement,
)

pytestmark = pytest.mark.db


def test_requete_depuis_references():
    assert "art. 18" in requete_depuis_references(["18"])
    assert requete_depuis_references([]) == ""


def test_recherche_filtre_type_cgi_millesime(session):
    texte = (
        "Art. FILTRE-CGI-99 — Plafond de démonstration technique uniquement.\n\n"
        "Art. AUTRE-1 — Sans lien."
    )
    ingerer_document(
        session,
        titre="[TEST] Annexe filtre ctx",
        type="annexe",
        millesime=2026,
        texte_brut=texte,
    )
    ingerer_document(
        session,
        titre="[TEST] CGI filtre ctx",
        type="cgi",
        millesime=2026,
        texte_brut=texte,
    )
    hits = recherche_hybride(
        session,
        "art. FILTRE-CGI-99 plafond",
        limite=10,
        types=["cgi"],
        millesime=2026,
    )
    assert hits
    assert all(h.get("type") == "cgi" for h in hits)
    assert all(h.get("millesime") == 2026 for h in hits)
    assert any("FILTRE-CGI-99" in str(h.get("reference")) for h in hits)


def test_contexte_cgi_extrait_ou_bloque(session):
    texte = (
        "Art. 18 — La valeur des dons et liberalites consentis est deductible "
        "dans la double limite de 2,5 % du chiffre d'affaires.\n\n"
        "Art. 999 — Article sans rapport."
    )
    ingerer_document(
        session,
        titre="[TEST] CGI contexte dons",
        type="cgi",
        millesime=2026,
        texte_brut=texte,
    )
    ctx = construire_contexte_cgi(
        session,
        rule_id="BIC-CHG-18G-DONS",
        reference_legale="CGI 2026, art. 18 G",
        article_corpus="18",
        millesime=2026,
        limite=3,
    )
    assert ctx["type"] == "cgi"
    assert ctx["millesime"] == 2026
    if ctx["n_fragments"] == 0:
        assert ctx["bloque"] is True
        assert ctx["message"] == MESSAGE_AUCUN_FRAGMENT
    else:
        assert ctx["bloque"] is False
        assert len(ctx["fragments"]) <= 3
        assert all("extrait" in f for f in ctx["fragments"])


def test_contexte_cgi_aucun_fragment(session):
    ctx = construire_contexte_cgi(
        session,
        requete="xyzzy-article-inexistant-777777",
        millesime=2026,
        limite=3,
    )
    assert ctx["bloque"] is True
    assert ctx["message"] == MESSAGE_AUCUN_FRAGMENT
    assert ctx["fragments"] == []


def test_catalogue_faibles_pas_promotion(tmp_path):
    rapport = {
        "genere_le": "2026-07-26T00:00:00Z",
        "source_document_id": 211,
        "n_articles": 1,
        "n_mentions": 2,
        "comptes": {"claire": 0, "contraste": 0, "faible": 1, "bloque": 1},
        "par_classe": {
            "claire": [],
            "contraste": [],
            "faible": [
                {
                    "entree_id": "BIC-AMORT-18B-GENERAL#0",
                    "rule_id": "BIC-AMORT-18B-GENERAL",
                    "raison": "article_present_date_non_prouvee",
                    "article_reference": "18",
                    "extrait": "…",
                }
            ],
            "bloque": [
                {
                    "entree_id": "BIC-AMORT-18B-GENERAL#1",
                    "rule_id": "BIC-AMORT-18B-GENERAL",
                    "raison": "hors_perimetre",
                }
            ],
        },
    }
    path = ecrire_catalogue_croisement(rapport, chemin=tmp_path / "croisement.json")
    assert path.is_file()
    idx = index_classes_croisement(
        {
            "par_classe": rapport["par_classe"],
        }
    )
    assert idx["BIC-AMORT-18B-GENERAL#0"]["classe_croisement"] == "faible"
    assert idx["BIC-AMORT-18B-GENERAL#1"]["classe_croisement"] == "bloque"
    entrees = enrichir_entrees_croisement(
        [{"id": "BIC-AMORT-18B-GENERAL#0"}, {"id": "X#0"}],
        idx,
    )
    assert entrees[0]["classe_croisement"] == "faible"
    assert "classe_croisement" not in entrees[1]


def test_index_faux_amis_potentiels_catalogue():
    idx = index_classes_croisement(
        {
            "par_classe": {
                "claire": [
                    {
                        "entree_id": "BIC-CHG-18A4-ADMIN#1",
                        "faux_amis": ["39", "53"],
                        "raison": "marqueur ; faux_amis_potentiels=['39', '53']",
                    }
                ],
                "faible": [],
                "bloque": [],
                "contraste": [],
            }
        }
    )
    meta = idx["BIC-CHG-18A4-ADMIN#1"]
    assert meta["faux_amis"] == ["39", "53"]
    assert meta["faux_amis_potentiels"] == ["39", "53"]
    # Faibles restent faibles — pas de promotion implicite via index
    assert meta["classe_croisement"] == "claire"
