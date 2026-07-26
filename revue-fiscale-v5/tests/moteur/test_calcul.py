"""Calcul de regle — expressions synthetiques (pas de taux legal affirme)."""
from decimal import Decimal

from backend.moteur.calcul import calculer_regle
from backend.referentiel.depot import RegleChargee
from backend.referentiel.expressions import Contexte


def _regle(
    *,
    condition: str,
    resultat: str,
    comptes: list[str] | None = None,
) -> RegleChargee:
    return RegleChargee(
        regle_version_id=1,
        regle_id="TST-SYN-CALCUL",
        impot="BIC",
        libelle="test",
        comptes_declencheurs=comptes or ["6582"],
        nature="permanente",
        condition_declenchement=condition,
        expression_resultat=resultat,
        niveau_risque="faible",
        formule_plafonnement=None,
        questions=[],
        a_confirmer=[],
        profils_applicables=[],
    )


def test_declenche_et_calcule():
    """Style BIC-CHG-18G-DONS avec bornes synthetiques (non legales)."""
    ctx = Contexte(
        soldes={"6582": Decimal("150000")},
        agregats={"CA": Decimal("4000000")},
        reponses={},
    )
    # Plafond synthetique de test : 10 % du CA borne a 50 000 — PAS un taux CGI.
    regle = _regle(
        condition="solde(6582) > 0",
        resultat="solde(6582) - min(0.1 * agregat(CA) ; 50000)",
    )
    c = calculer_regle(regle, ctx)
    assert c.declenchee is True
    assert c.montant == Decimal("100000")  # 150000 - 50000
    assert c.sens == "reintegration"


def test_non_declenchee():
    ctx = Contexte(soldes={"6582": Decimal("0")}, agregats={}, reponses={})
    regle = _regle(condition="solde(6582) > 0", resultat="solde(6582)")
    c = calculer_regle(regle, ctx)
    assert c.declenchee is False
    assert c.montant is None
