"""Tests unitaires — score de risque client (calcul déterministe)."""
from __future__ import annotations

from datetime import date

from backend.plateforme.risques import calculer_score_risque

AUJOURD_HUI = date(2026, 7, 26)


def _risque(**kw) -> dict:
    base = {
        "statut": "ouvert",
        "probabilite": "possible",
        "montant_estime": None,
        "penalites_estimees": None,
        "derniere_revue": AUJOURD_HUI.isoformat(),
        "cree_le": AUJOURD_HUI.isoformat(),
        "exercice_origine": AUJOURD_HUI.year,
        "nb_actions": 1,
    }
    base.update(kw)
    return base


def test_vide_score_zero_niveau_aucun():
    r = calculer_score_risque({"risques": [], "aujourd_hui": AUJOURD_HUI})
    assert r["score"] == 0
    assert r["niveau"] == "aucun"
    assert r["libelle_niveau"] == "Aucun risque ouvert"
    assert r["alertes"] == []
    assert r["exposition_totale"] == "0"


def test_risques_clos_ignores():
    r = calculer_score_risque(
        {
            "risques": [
                _risque(statut="resolu", montant_estime="9000000"),
                _risque(statut="accepte", probabilite="probable"),
                _risque(statut="prescrit"),
            ],
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert r["score"] == 0
    assert r["niveau"] == "aucun"


def test_cas_mixte():
    r = calculer_score_risque(
        {
            "risques": [
                # probable (12) + revue récente, avec action
                _risque(probabilite="probable", montant_estime="600000"),
                # possible (7), dormant (jamais revu, créé il y a > 90 j)
                _risque(
                    probabilite="possible",
                    derniere_revue=None,
                    cree_le="2026-01-01",
                    penalites_estimees="500000",
                ),
                # faible (3), en_traitement
                _risque(probabilite="faible", statut="en_traitement"),
            ],
            "actions_en_retard": 1,
            "actions_refusees": 1,
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    # exposition 12+7+3=22 ; enjeu 1,1 M → 10 ; retards 8 ; dormant 5 ; refus 4
    assert r["score"] == 22 + 10 + 8 + 5 + 4
    assert r["niveau"] == "eleve"
    pts = {f["code"]: f["points"] for f in r["facteurs"]}
    assert pts == {
        "exposition": 22,
        "enjeu_financier": 10,
        "actions_retard": 8,
        "dormants": 5,
        "actions_refusees": 4,
    }
    assert r["exposition_totale"] == "1100000"
    assert any("en retard" in a for a in r["alertes"])
    assert any("90 jours" in a for a in r["alertes"])
    assert any("refusée" in a for a in r["alertes"])


def test_plafonds_facteurs():
    r = calculer_score_risque(
        {
            "risques": [
                _risque(derniere_revue="2020-01-01", probabilite="faible")
                for _ in range(6)
            ],
            "actions_en_retard": 10,  # 80 → plafonné 24
            "actions_refusees": 9,  # 36 → plafonné 12
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    pts = {f["code"]: f["points"] for f in r["facteurs"]}
    assert pts["actions_retard"] == 24
    assert pts["actions_refusees"] == 12
    assert pts["dormants"] == 20  # 6 × 5 = 30 → plafonné 20


def test_score_plafonne_100_et_critique():
    r = calculer_score_risque(
        {
            "risques": [
                _risque(
                    probabilite="probable",
                    montant_estime="50000000",
                    derniere_revue="2020-01-01",
                    nb_actions=0,
                )
                for _ in range(10)
            ],
            "actions_en_retard": 5,
            "actions_refusees": 5,
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert r["score"] == 100
    assert r["niveau"] == "critique"
    assert any("probable(s) sans action" in a for a in r["alertes"])


def test_paliers_enjeu():
    def score_enjeu(montant: str) -> int:
        r = calculer_score_risque(
            {
                "risques": [_risque(montant_estime=montant)],
                "aujourd_hui": AUJOURD_HUI,
            }
        )
        return {f["code"]: f["points"] for f in r["facteurs"]}[
            "enjeu_financier"
        ]

    assert score_enjeu("999999") == 5
    assert score_enjeu("1000000") == 10
    assert score_enjeu("4999999") == 10
    assert score_enjeu("5000000") == 15
    assert score_enjeu("20000000") == 20


def test_alerte_prescription():
    r = calculer_score_risque(
        {
            "risques": [
                _risque(exercice_origine=AUJOURD_HUI.year - 3),
                _risque(exercice_origine=AUJOURD_HUI.year - 5),
                _risque(exercice_origine=AUJOURD_HUI.year - 1),
            ],
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert any(
        "2 risque(s) d'exercices ≤ N-3" in a and "L171" in a
        for a in r["alertes"]
    )


def test_niveaux_seuils():
    # 1 risque faible bien suivi → 3 pts → faible
    r = calculer_score_risque(
        {
            "risques": [_risque(probabilite="faible")],
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert (r["score"], r["niveau"]) == (3, "faible")
    assert r["plage"] == "0–19"
    # 2 probables + 1 possible = 31 → modéré
    r = calculer_score_risque(
        {
            "risques": [
                _risque(probabilite="probable"),
                _risque(probabilite="probable"),
                _risque(probabilite="possible"),
            ],
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert (r["score"], r["niveau"]) == (31, "modere")
    assert r["plage"] == "20–39"


def test_plages_niveaux_documentees():
    vide = calculer_score_risque({"risques": [], "aujourd_hui": AUJOURD_HUI})
    assert vide["plage"] is None
    critique = calculer_score_risque(
        {
            "risques": [
                _risque(
                    probabilite="probable",
                    montant_estime="50000000",
                    derniere_revue="2020-01-01",
                )
                for _ in range(10)
            ],
            "actions_en_retard": 5,
            "actions_refusees": 5,
            "aujourd_hui": AUJOURD_HUI,
        }
    )
    assert critique["plage"] == "70–100"
