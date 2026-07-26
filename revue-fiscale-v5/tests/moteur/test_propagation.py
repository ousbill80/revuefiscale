"""Detection de cycles dans le graphe d effets croises."""
import pytest

from backend.moteur.propagation import ErreurCycle, detect_cycles


def test_sans_cycle():
    detect_cycles({"A": ["B"], "B": ["C"], "C": []})


def test_cycle_simple():
    with pytest.raises(ErreurCycle) as exc:
        detect_cycles({"A": ["B"], "B": ["A"]})
    assert "A" in exc.value.chemin
    assert "B" in exc.value.chemin


def test_cycle_long():
    with pytest.raises(ErreurCycle):
        detect_cycles({"A": ["B"], "B": ["C"], "C": ["A"]})


def test_graphe_vide():
    detect_cycles({})


def test_auto_boucle():
    with pytest.raises(ErreurCycle):
        detect_cycles({"A": ["A"]})
