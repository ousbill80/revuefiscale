"""Cas de test BIC-CHG-18G-DONS — régression d'expressions (sans base).

Les montants illustrent la structure du format pivot, pas le droit en vigueur.
Tout paramètre marqué a_confirmer dans le YAML reste provisional.
"""
from decimal import Decimal
from pathlib import Path

import yaml

from backend.referentiel.expressions import Contexte, evaluer

RACINE = Path(__file__).resolve().parents[2] / "referentiel"


def _charger(identifiant: str) -> dict:
    chemin = RACINE / f"{identifiant}.yaml"
    assert chemin.exists(), f"regle absente : {chemin}"
    data = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data["identifiant"] == identifiant
    return data


class TestBICChg18GDons:
    """Régression d'expression — valeurs a_confirmer dans le YAML."""

    def test_plafond_et_reintegration(self):
        regle = _charger("BIC-CHG-18G-DONS")
        ctx = Contexte(
            soldes={"6582": Decimal("150000000")},
            agregats={"CA": Decimal("4000000000")},
        )
        assert evaluer(regle["condition_declenchement"], ctx) is True
        plafond = evaluer(regle["formule_plafonnement"], ctx)
        assert plafond == Decimal("100000000")
        assert evaluer(regle["resultat"], ctx) == Decimal("50000000")

    def test_bascule_borne_absolue(self):
        regle = _charger("BIC-CHG-18G-DONS")
        ctx = Contexte(
            soldes={"6582": Decimal("250000000")},
            agregats={"CA": Decimal("8000000000")},
        )
        assert evaluer(regle["formule_plafonnement"], ctx) == Decimal("200000000")
        assert evaluer(regle["resultat"], ctx) == Decimal("50000000")


def test_cinquante_sept_regles_metier_a_la_racine():
    """Harnais complet : 57 metier, 0 EMPLACEMENT."""
    metier = sorted(
        p for p in RACINE.glob("*.yaml") if not p.name.startswith("EMPLACEMENT-")
    )
    assert len(metier) == 57, f"attendu 57 metier, trouvé {len(metier)}"
    assert (RACINE / "BIC-CHG-18G-DONS.yaml").is_file()
    assert (RACINE / "TVA-DED-PRORATA.yaml").is_file()
    assert (RACINE / "RA-CNX-01.yaml").is_file()
    emp_dir = RACINE / "emplacements"
    n_emp = len(list(emp_dir.glob("EMPLACEMENT-*.yaml"))) if emp_dir.is_dir() else 0
    assert n_emp == 0, f"attendu 0 EMPLACEMENT, trouvé {n_emp}"
