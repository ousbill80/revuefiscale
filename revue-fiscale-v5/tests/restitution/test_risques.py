"""Tests unitaires — score de risque heuristique (non reglementaire)."""
from backend.restitution.risques import AVERTISSEMENT, POIDS_NIVEAU, scorer_risques


def test_poids_documentes():
    assert POIDS_NIVEAU == {"faible": 1, "moyen": 2, "eleve": 3}


def test_score_cumule():
    conclusions = [
        {"niveau_risque": "faible"},
        {"niveau_risque": "moyen"},
        {"niveau_risque": "eleve"},
        {"niveau_risque": "eleve"},
    ]
    s = scorer_risques(conclusions)
    assert s.score == 1 + 2 + 3 + 3
    assert s.comptages == {"faible": 1, "moyen": 1, "eleve": 2}
    assert AVERTISSEMENT in s.avertissement
    assert "non reglementaire" in s.avertissement.lower()


def test_niveaux_inconnus_ignores():
    s = scorer_risques(
        [
            {"niveau_risque": "critique"},
            {"niveau_risque": ""},
            {"niveau_risque": "Faible"},  # case-insensitive
        ]
    )
    assert s.score == 1
    assert s.comptages == {"faible": 1}


def test_score_vide():
    s = scorer_risques([])
    assert s.score == 0
    assert s.comptages == {}
