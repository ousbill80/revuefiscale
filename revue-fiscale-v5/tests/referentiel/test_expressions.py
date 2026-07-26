"""L evaluateur d expressions : determinisme, liste blanche, erreurs nommees."""
from decimal import Decimal

import pytest

from backend.referentiel.expressions import Contexte, ErreurEvaluation, ErreurSyntaxe, evaluer


@pytest.fixture
def ctx() -> Contexte:
    return Contexte(
        soldes={"6582": Decimal("150000000"), "661": Decimal("80000000")},
        agregats={"CA": Decimal("4000000000"), "RESULTAT_AVANT_IMPOT": Decimal("300000000")},
        reponses={"q1": True, "q2": False, "q3": Decimal("500000")},
    )


class TestArithmetique:
    def test_operations(self, ctx):
        assert evaluer("2 + 3 * 4", ctx) == Decimal("14")
        assert evaluer("(2 + 3) * 4", ctx) == Decimal("20")
        assert evaluer("-5 + 3", ctx) == Decimal("-2")

    def test_decimal_pas_float(self, ctx):
        # 0.1 + 0.2 doit valoir exactement 0.3 — un float donnerait 0.30000000000000004
        assert evaluer("0.1 + 0.2", ctx) == Decimal("0.3")

    def test_virgule_decimale(self, ctx):
        assert evaluer("2,5 * 2", ctx) == Decimal("5.0")


class TestReferences:
    def test_solde(self, ctx):
        assert evaluer("solde(6582)", ctx) == Decimal("150000000")

    def test_solde_agrege_les_sous_comptes(self, ctx):
        ctx.soldes["6583"] = Decimal("10000000")
        assert evaluer("solde(658)", ctx) == Decimal("160000000")

    def test_agregat_insensible_a_la_casse(self, ctx):
        assert evaluer("agregat(ca)", ctx) == Decimal("4000000000")

    def test_reponse(self, ctx):
        assert evaluer("reponse(q1)", ctx) is True


class TestPlafonnementReel:
    """La regle BIC-CHG-18G-DONS de docs/02-format-pivot.md."""

    PLAFOND = "min(0.025 * agregat(CA) ; 200000000)"

    def test_plafond_proportionnel(self, ctx):
        assert evaluer(self.PLAFOND, ctx) == Decimal("100000000")

    def test_bascule_sur_la_borne_absolue(self, ctx):
        ctx.agregats["CA"] = Decimal("8000000000")
        assert evaluer(self.PLAFOND, ctx) == Decimal("200000000")

    def test_reintegration(self, ctx):
        montant = evaluer(f"solde(6582) - ({self.PLAFOND})", ctx)
        assert montant == Decimal("50000000")

    def test_declenchement(self, ctx):
        assert evaluer("solde(6582) > 0", ctx) is True


class TestLogique:
    def test_et_ou_non(self, ctx):
        assert evaluer("reponse(q1) et non reponse(q2)", ctx) is True
        assert evaluer("reponse(q2) ou reponse(q1)", ctx) is True

    def test_comparaisons(self, ctx):
        assert evaluer("agregat(CA) >= 4000000000", ctx) is True
        assert evaluer("solde(661) <> 0", ctx) is True


class TestListeBlanche:
    """Ce qui doit etre refuse — la surface d attaque."""

    @pytest.mark.parametrize(
        "source",
        [
            "__import__('os').system('rm -rf /')",
            "eval('1+1')",
            "open('/etc/passwd')",
            "solde.__class__",
            "[1, 2, 3]",
            "lambda x: x",
            "exec('print(1)')",
            "os.path",
            "CA",  # identifiant nu : il faut agregat(CA)
        ],
    )
    def test_refuse(self, source, ctx):
        with pytest.raises(ErreurSyntaxe):
            evaluer(source, ctx)

    def test_nombre_d_arguments_verifie(self, ctx):
        with pytest.raises(ErreurSyntaxe):
            evaluer("min(1)", ctx)

    def test_expression_vide(self, ctx):
        with pytest.raises(ErreurSyntaxe):
            evaluer("   ", ctx)


class TestErreursNommees:
    """Jamais de valeur par defaut silencieuse sur un calcul fiscal."""

    def test_compte_absent(self, ctx):
        with pytest.raises(ErreurEvaluation, match="compte 7999 absent"):
            evaluer("solde(7999)", ctx)

    def test_agregat_non_defini(self, ctx):
        with pytest.raises(ErreurEvaluation, match="agregat FRAIS_GENERAUX non defini"):
            evaluer("agregat(FRAIS_GENERAUX)", ctx)

    def test_reponse_non_saisie(self, ctx):
        with pytest.raises(ErreurEvaluation, match="reponse q9 non saisie"):
            evaluer("reponse(q9)", ctx)

    def test_division_par_zero(self, ctx):
        with pytest.raises(ErreurEvaluation, match="division par zero"):
            evaluer("1 / 0", ctx)


class TestDeterminisme:
    def test_meme_entree_meme_sortie(self, ctx):
        source = "min(0.025 * agregat(CA) ; 200000000)"
        resultats = {evaluer(source, ctx) for _ in range(100)}
        assert len(resultats) == 1
