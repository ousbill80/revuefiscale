"""Tests verification d ancrage."""
from backend.agent.ancrage import verifier_ancrage


def test_ancrage_ok():
    frag = "Les dons et liberalites mentionnes au present article fictif."
    r = verifier_ancrage(
        ["dons et liberalites mentionnes"],
        [frag],
    )
    assert r.ok
    assert not r.citations_rejetees


def test_ancrage_rejette_invention():
    frag = "Texte demo non opposable."
    r = verifier_ancrage(
        ["Selon l'article 39 du CGI les charges sont deductibles"],
        [frag],
    )
    assert not r.ok
    assert r.citations_rejetees


def test_ancrage_espace_normalise():
    frag = "plafond   demontre   pour   essais"
    r = verifier_ancrage(["plafond demontre pour essais"], [frag])
    assert r.ok
