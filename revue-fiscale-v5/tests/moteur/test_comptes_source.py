"""Traçabilité des conclusions — comptes à l'origine (piste d'audit)."""
from decimal import Decimal

from backend.moteur.calcul import calculer_regle
from backend.moteur.service import comptes_source_conclusion
from backend.referentiel.depot import RegleChargee
from backend.referentiel.expressions import Contexte
from backend.socle.agregats import comptes_par_agregat


def _regle(condition: str, resultat: str) -> RegleChargee:
    return RegleChargee(
        regle_version_id=1,
        regle_id="TST-COMPTES",
        impot="BIC",
        libelle="test traçabilité",
        comptes_declencheurs=["658"],
        nature="reintegration",
        condition_declenchement=condition,
        expression_resultat=resultat,
        niveau_risque="faible",
        formule_plafonnement=None,
        questions=[],
        a_confirmer=[],
        profils_applicables=[],
    )


def _ctx(soldes: dict[str, Decimal], agregats: dict[str, Decimal] | None = None) -> Contexte:
    return Contexte(
        soldes=soldes,
        agregats=agregats or {},
        reponses={},
        comptes_par_agregat=comptes_par_agregat(soldes),
    )


def test_comptes_utilises_via_reference_solde_et_prefixe():
    soldes = {
        "6581": Decimal("100"),
        "6582": Decimal("50"),
        "701000": Decimal("1000"),
    }
    c = calculer_regle(_regle("solde(658) > 0", "solde(658)"), _ctx(soldes))
    assert c.declenchee is True
    assert c.montant == Decimal("150")
    # Les deux sous-comptes 658x, jamais le 701 non référencé.
    assert c.comptes_utilises == ("6581", "6582")


def test_comptes_utilises_via_agregat():
    soldes = {
        "701000": Decimal("800"),
        "706000": Decimal("200"),
        "6581": Decimal("10"),
    }
    agregats = {"CA": Decimal("1000")}
    c = calculer_regle(
        _regle("agregat(CA) > 0", "agregat(CA) * 2 / 1000"),
        _ctx(soldes, agregats),
    )
    assert c.declenchee is True
    # Composition du CA (701-707) tracée, pas le compte de charge.
    assert c.comptes_utilises == ("701000", "706000")


def test_contexte_appelant_non_mute_entre_regles():
    soldes = {"6581": Decimal("100"), "701000": Decimal("1000")}
    ctx = _ctx(soldes)
    c1 = calculer_regle(_regle("solde(658) > 0", "solde(658)"), ctx)
    c2 = calculer_regle(_regle("solde(701) > 0", "solde(701)"), ctx)
    assert c1.comptes_utilises == ("6581",)
    assert c2.comptes_utilises == ("701000",)
    # Le contexte partagé ne cumule pas les traces d'une règle à l'autre.
    assert ctx.comptes_utilises == set()


def test_comptes_traces_meme_si_resultat_inevaluable():
    soldes = {"6581": Decimal("100")}
    c = calculer_regle(_regle("solde(658) > 0", "reponse(absente)"), _ctx(soldes))
    assert c.inevaluable is True
    assert c.comptes_utilises == ("6581",)


def test_comptes_source_conclusion_payload():
    soldes = {
        "6581": Decimal("100"),
        "701000": Decimal("1000"),  # naturel classe 7 : credit - debit
    }
    infos = {
        "6581": {
            "libelle": "Dons et libéralités",
            "debit": Decimal("100"),
            "credit": Decimal("0"),
        },
        "701000": {
            "libelle": "Ventes de marchandises",
            "debit": Decimal("0"),
            "credit": Decimal("1000"),
        },
    }
    payload = comptes_source_conclusion(("701000", "6581"), soldes, infos)
    assert payload == [
        {
            "compte": "6581",
            "libelle": "Dons et libéralités",
            "solde": "100",
            "sens": "debiteur",
        },
        {
            "compte": "701000",
            "libelle": "Ventes de marchandises",
            "solde": "1000",
            "sens": "crediteur",
        },
    ]


def test_comptes_source_conclusion_ignore_compte_inconnu():
    payload = comptes_source_conclusion(("999",), {}, {})
    assert payload == []


def test_comptes_par_agregat_benefice_et_frais():
    soldes = {
        "131": Decimal("-500"),
        "601": Decimal("10"),
        "622": Decimal("20"),
        "681": Decimal("30"),
        "891": Decimal("40"),
    }
    compo = comptes_par_agregat(soldes)
    assert compo["BENEFICE_COMPTABLE"] == ("131",)
    assert compo["RESULTAT_AVANT_IMPOT"] == ("131", "891")
    # Frais généraux : hors achats (601) et hors dotations (68x).
    assert compo["FRAIS_GENERAUX"] == ("622",)
