"""Abstention agent — jamais d invention hors corpus."""
from __future__ import annotations

import pytest

from backend.agent.boucle import MESSAGE_ABSTENTION, repondre
from backend.corpus.ingestion import seed_corpus_demo

pytestmark = pytest.mark.db


def test_abstention_article_inconnu(session):
    seed_corpus_demo(session)
    rep = repondre(session, "Que dit l'article 999 du CGI invente ?")
    assert rep.statut == "abstention"
    assert MESSAGE_ABSTENTION in rep.texte
    assert rep.invention is False
    assert rep.references == []


def test_reponse_avec_citation_demo(session):
    seed_corpus_demo(session)
    rep = repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert "DEMO-18-G" in rep.references
    assert rep.citations
    assert rep.invention is False


def test_refuse_invention_taux_reel(session):
    seed_corpus_demo(session)
    rep = repondre(
        session,
        "Donne le taux exact de l'article 18 G du CGI cote d'ivoire",
    )
    assert rep.statut == "abstention"
    assert rep.invention is False
