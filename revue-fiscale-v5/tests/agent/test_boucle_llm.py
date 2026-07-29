"""Redaction LLM optionnelle de l agent — enrichissement best-effort, jamais bloquant."""
from __future__ import annotations

import json

import pytest

from backend.agent import boucle
from backend.corpus.ingestion import seed_corpus_demo
from backend.socle import llm_providers

pytestmark = pytest.mark.db


def _configurer_provider_factice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        boucle.llm_providers, "providers_configures", lambda: True
    )


def test_llm_absent_par_defaut(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans fournisseur configure (cas CI) : comportement 100% deterministe."""
    monkeypatch.setattr(
        boucle.llm_providers, "providers_configures", lambda: False
    )
    seed_corpus_demo(session)
    appelle = {"n": 0}

    def _jamais_appele(*_a: object, **_k: object) -> None:
        appelle["n"] += 1
        raise AssertionError("appeler_chat ne doit pas etre appele sans provider")

    monkeypatch.setattr(boucle.llm_providers, "appeler_chat", _jamais_appele)

    rep = boucle.repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert appelle["n"] == 0


def test_llm_redaction_valide_est_utilisee(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configurer_provider_factice(monkeypatch)

    seed_corpus_demo(session)

    def _appeler_chat_factice(messages, **_kwargs):
        fragment = messages[1]["content"]
        # La citation doit etre une sous-chaine reelle d un fragment fourni.
        assert "DEMO-18-G" in fragment
        return (
            json.dumps(
                {
                    "reponse": "Les dons ouvrent droit a une reduction sous conditions.",
                    "citations": [],
                }
            ),
            "provider-test",
            (),
        )

    monkeypatch.setattr(boucle.llm_providers, "appeler_chat", _appeler_chat_factice)

    rep = boucle.repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert "Les dons ouvrent droit a une reduction" in rep.texte
    # Les champs structures restent ceux du chemin regle-based, pas du LLM.
    assert "DEMO-18-G" in rep.references


def test_llm_reference_inventee_est_rejetee(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une reference hors corpus dans la prose LLM -> repli sur le texte deterministe."""
    _configurer_provider_factice(monkeypatch)
    seed_corpus_demo(session)

    def _appeler_chat_invente(messages, **_kwargs):
        return (
            json.dumps(
                {
                    "reponse": "Voir aussi l'article 999-Z qui precise ce point.",
                    "citations": [],
                }
            ),
            "provider-test",
            (),
        )

    monkeypatch.setattr(boucle.llm_providers, "appeler_chat", _appeler_chat_invente)

    rep = boucle.repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert "999-Z" not in rep.texte
    assert "Réponse fondée exclusivement sur le corpus indexé." in rep.texte


def test_llm_citation_non_ancree_est_rejetee(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configurer_provider_factice(monkeypatch)
    seed_corpus_demo(session)

    def _appeler_chat_citation_fausse(messages, **_kwargs):
        return (
            json.dumps(
                {
                    "reponse": "Reponse plausible.",
                    "citations": ["cette phrase n'existe dans aucun fragment fourni"],
                }
            ),
            "provider-test",
            (),
        )

    monkeypatch.setattr(
        boucle.llm_providers, "appeler_chat", _appeler_chat_citation_fausse
    )

    rep = boucle.repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert "Reponse plausible." not in rep.texte
    assert "Réponse fondée exclusivement sur le corpus indexé." in rep.texte


def test_llm_erreur_provider_replie_sans_lever(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configurer_provider_factice(monkeypatch)
    seed_corpus_demo(session)

    def _appeler_chat_echec(messages, **_kwargs):
        raise llm_providers.ErreurLlm("panne simulee", kind="timeout")

    monkeypatch.setattr(boucle.llm_providers, "appeler_chat", _appeler_chat_echec)

    rep = boucle.repondre(session, "Que dit l'article DEMO-18-G sur les dons ?")
    assert rep.statut == "repondu"
    assert "Réponse fondée exclusivement sur le corpus indexé." in rep.texte
