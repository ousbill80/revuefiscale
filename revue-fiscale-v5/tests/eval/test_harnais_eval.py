"""Harnais d evaluation — taux d invention = 0 sur le jeu de reference."""
from __future__ import annotations

import pytest

from backend.agent.evaluation import charger_jeu, evaluer_agent, evaluer_jeu
from backend.corpus.ingestion import seed_corpus_demo

pytestmark = pytest.mark.db


def test_jeu_au_moins_20_cas():
    cas = charger_jeu()
    assert len(cas) >= 20


def test_invention_rate_zero(session):
    seed_corpus_demo(session)
    moyenne, details = evaluer_jeu(session)
    assert moyenne.invention == 0.0, (
        "invention non nulle : "
        + ", ".join(
            str(d.detail.get("id"))
            for d in details
            if d.invention > 0
        )
    )


def test_pieges_sabstiennent(session):
    seed_corpus_demo(session)
    cas = [c for c in charger_jeu() if c.get("est_piege")]
    assert len(cas) >= 5
    for c in cas:
        m = evaluer_agent(c, session=session)
        assert m.invention == 0.0, c.get("id")
        assert m.abstention == 1.0, f"piege {c.get('id')} n a pas sabstenu"
