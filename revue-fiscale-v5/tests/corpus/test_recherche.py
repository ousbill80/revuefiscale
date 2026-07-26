"""Tests recherche et ingestion corpus."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.corpus.ingestion import TEXTE_DEMO, ingerer_document, seed_corpus_demo
from backend.corpus.recherche import recherche_hybride

pytestmark = pytest.mark.db


def test_ingerer_et_rechercher_demo(session):
    r = ingerer_document(
        session,
        titre="[TEST] Corpus unitaire",
        type="demo",
        millesime=2026,
        texte_brut=TEXTE_DEMO,
    )
    assert r.articles >= 3
    assert r.fragments >= 3

    hits = recherche_hybride(session, "dons liberalites DEMO-18-G", limite=5)
    assert hits
    refs = [h["reference"] for h in hits]
    assert "DEMO-18-G" in refs
    assert hits[0]["score"] > 0
    assert "extrait" in hits[0]


def test_seed_idempotent(session):
    a = seed_corpus_demo(session)
    b = seed_corpus_demo(session)
    assert a is not None or b is None
    # Second appel ne duplique pas
    n = session.execute(
        text(
            "SELECT count(*) FROM source_document "
            "WHERE titre = :t AND type = 'demo'"
        ),
        {"t": "[DÉMO FICTIF] Corpus de reference technique"},
    ).scalar_one()
    assert n == 1


def test_recherche_article_inconnu_faible(session):
    seed_corpus_demo(session)
    hits = recherche_hybride(session, "xyzzy plugh article 77777 inexistant", limite=5)
    # Peut etre vide ou score faible — pas de reference inventee
    for h in hits:
        assert "77777" not in str(h["reference"])


def test_priorite_cgi_millesime_2026(session):
    """À score lexical comparable, type=cgi millésime 2026 passe devant annexe."""
    texte = (
        "Art. PRIORITE-X — La déduction des dons et liberalites est plafonnée.\n\n"
        "Art. PRIORITE-Y — Autre article sans lien lexical fort."
    )
    ingerer_document(
        session,
        titre="[TEST] Annexe priorite",
        type="annexe",
        millesime=2026,
        texte_brut=texte,
    )
    ingerer_document(
        session,
        titre="[TEST] CGI priorite",
        type="cgi",
        millesime=2026,
        texte_brut=texte,
    )
    hits = recherche_hybride(
        session,
        "dons liberalites PRIORITE-X",
        limite=5,
        millesime_prioritaire=2026,
    )
    assert hits
    cgi_hits = [h for h in hits if h.get("type") == "cgi" and "PRIORITE-X" in str(h["reference"])]
    annexe_hits = [
        h for h in hits if h.get("type") == "annexe" and "PRIORITE-X" in str(h["reference"])
    ]
    assert cgi_hits and annexe_hits
    assert float(cgi_hits[0]["score"]) > float(annexe_hits[0]["score"])
    # Premier hit de la référence PRIORITE-X doit être CGI
    premier_priorite = next(h for h in hits if "PRIORITE-X" in str(h["reference"]))
    assert premier_priorite["type"] == "cgi"
    assert premier_priorite["millesime"] == 2026


def test_recherche_filtre_strict_millesime(session):
    """``millesime=`` exclut les autres millésimes (filtre, pas seulement boost)."""
    texte = "Art. MIL-FILTRE — Texte technique de recherche millesime."
    ingerer_document(
        session,
        titre="[TEST] CGI 2025 filtre",
        type="cgi",
        millesime=2025,
        texte_brut=texte,
    )
    ingerer_document(
        session,
        titre="[TEST] CGI 2026 filtre",
        type="cgi",
        millesime=2026,
        texte_brut=texte,
    )
    hits_2026 = recherche_hybride(
        session,
        "MIL-FILTRE",
        limite=10,
        types=["cgi"],
        millesime=2026,
    )
    assert hits_2026
    assert all(h.get("millesime") == 2026 for h in hits_2026)
    assert all(h.get("type") == "cgi" for h in hits_2026)