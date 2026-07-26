"""Statut brouillon conclusion — déterministe, sans seuil CGI inventé."""
from decimal import Decimal

from backend.moteur.calcul import (
    ConclusionCalculee,
    calculer_regle,
    statut_brouillon_conclusion,
)
from backend.referentiel.depot import RegleChargee
from backend.referentiel.expressions import Contexte


def _c(
    *,
    declenchee: bool,
    montant: Decimal | None,
    inevaluable: bool = False,
) -> ConclusionCalculee:
    return ConclusionCalculee(
        regle_version_id=1,
        regle_id="TST",
        declenchee=declenchee,
        montant=montant,
        sens="reintegration" if montant is not None else None,
        niveau_risque="faible",
        inevaluable=inevaluable,
    )


def test_statut_anomalie_sans_seuil():
    assert statut_brouillon_conclusion(_c(declenchee=True, montant=Decimal("100")), None) == (
        "anomalie"
    )


def test_statut_sous_seuil_si_montant_strictement_inferieur():
    seuil = Decimal("1000")
    assert (
        statut_brouillon_conclusion(_c(declenchee=True, montant=Decimal("999")), seuil)
        == "sous_seuil"
    )
    assert (
        statut_brouillon_conclusion(_c(declenchee=True, montant=Decimal("1000")), seuil)
        == "anomalie"
    )
    assert (
        statut_brouillon_conclusion(_c(declenchee=True, montant=Decimal("-500")), seuil)
        == "sous_seuil"
    )


def test_statut_non_verifiable_si_inevaluable():
    assert (
        statut_brouillon_conclusion(
            _c(declenchee=False, montant=None, inevaluable=True), Decimal("1")
        )
        == "non_verifiable"
    )


def test_pas_de_statut_si_non_declenchee():
    assert statut_brouillon_conclusion(_c(declenchee=False, montant=None), None) is None


def test_condition_inevaluable_marque_flag():
    regle = RegleChargee(
        regle_version_id=1,
        regle_id="TST-INEV",
        impot="BIC",
        libelle="test",
        comptes_declencheurs=["701"],
        nature="sans_objet",
        condition_declenchement="reponse(absent)",
        expression_resultat="0",
        niveau_risque="faible",
        formule_plafonnement=None,
        questions=[],
        a_confirmer=[],
        profils_applicables=[],
    )
    c = calculer_regle(regle, Contexte(soldes={}, agregats={}, reponses={}))
    assert c.inevaluable is True
    assert c.declenchee is False
    assert statut_brouillon_conclusion(c, None) == "non_verifiable"
