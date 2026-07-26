"""Harnais des règles YAML sous referentiel/ — sans base.

57 fiches metier (Lots 1–3 + RA). Paramètres souvent a_confirmer.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from backend.referentiel.expressions import Contexte, analyser, evaluer

RACINE = Path(__file__).resolve().parents[2] / "referentiel"

CHAMPS_REQUIS = {
    "identifiant",
    "impot",
    "reference_legale",
    "date_effet",
    "profils_applicables",
    "comptes_declencheurs",
    "nature",
    "condition_declenchement",
    "conditions_fond",
    "formule_plafonnement",
    "questions_generees",
    "resultat",
    "niveau_risque",
    "effets_croises",
}

EXPR_CHAMPS = ("condition_declenchement", "formule_plafonnement", "resultat")


def _fichiers_regles() -> list[Path]:
    """Harnais : 57 fiches metier a la racine."""
    return sorted(
        p for p in RACINE.glob("*.yaml") if not p.name.startswith("EMPLACEMENT-")
    )


def _charger(chemin: Path) -> dict:
    data = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{chemin} : pas un mapping"
    return data


def _vers_decimal(valeur: object) -> Decimal:
    if isinstance(valeur, Decimal):
        return valeur
    if isinstance(valeur, bool):
        raise TypeError(f"booleen inattendu dans cas_test : {valeur!r}")
    if isinstance(valeur, (int, float)):
        return Decimal(str(valeur))
    return Decimal(str(valeur))


def _contexte_depuis_cas(cas: dict) -> Contexte:
    soldes_bruts = cas.get("soldes") or {}
    agregats_bruts = cas.get("agregats") or {}
    reponses_bruts = cas.get("reponses") or {}
    soldes = {str(k): _vers_decimal(v) for k, v in soldes_bruts.items()}
    agregats = {str(k): _vers_decimal(v) for k, v in agregats_bruts.items()}
    reponses: dict[str, object] = {}
    for k, v in reponses_bruts.items():
        if isinstance(v, bool):
            reponses[str(k)] = v
        elif isinstance(v, (int, float, str, Decimal)):
            try:
                reponses[str(k)] = _vers_decimal(v)
            except Exception:
                reponses[str(k)] = v
        else:
            reponses[str(k)] = v
    return Contexte(soldes=soldes, agregats=agregats, reponses=reponses)


def test_compte_regles_egal_57():
    fichiers = _fichiers_regles()
    assert len(fichiers) == 57, f"attendu 57 YAML metier, trouvé {len(fichiers)}"
    emp = list((RACINE / "emplacements").glob("EMPLACEMENT-*.yaml")) if (
        RACINE / "emplacements"
    ).is_dir() else []
    assert len(emp) == 0, f"EMPLACEMENT restants : {len(emp)}"


@pytest.mark.parametrize("chemin", _fichiers_regles(), ids=lambda p: p.stem)
def test_regle_format_et_expressions(chemin: Path):
    regle = _charger(chemin)
    manquants = CHAMPS_REQUIS - set(regle)
    assert not manquants, f"{chemin.name} : champs absents {sorted(manquants)}"

    for champ in EXPR_CHAMPS:
        expr = regle[champ]
        if isinstance(expr, str) and expr.strip().lower() != "sans objet":
            analyser(expr)


@pytest.mark.parametrize("chemin", _fichiers_regles(), ids=lambda p: p.stem)
def test_cas_test_declenchement_et_montant(chemin: Path):
    regle = _charger(chemin)
    cas = regle.get("cas_test")
    assert isinstance(cas, dict), f"{chemin.name} : cas_test obligatoire"
    ctx = _contexte_depuis_cas(cas)
    declenche = evaluer(regle["condition_declenchement"], ctx)
    attendu = cas.get("declenche_attendu")
    assert declenche is bool(attendu) or declenche == attendu, (
        f"{chemin.name} : declenche={declenche!r} attendu={attendu!r}"
    )
    if not declenche:
        return
    montant = evaluer(regle["resultat"], ctx)
    attendu_mt = cas.get("montant_attendu")
    assert attendu_mt is not None, f"{chemin.name} : montant_attendu manquant"
    assert Decimal(str(montant)) == Decimal(str(attendu_mt)), (
        f"{chemin.name} : montant={montant} attendu={attendu_mt}"
    )
