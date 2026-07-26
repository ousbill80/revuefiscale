"""Tests unitaires — preuve de résolution de risque (verdict IA consultatif)."""
from __future__ import annotations

import pytest

from backend.plateforme.preuve_resolution import (
    MESSAGE_ANALYSE_INDISPONIBLE,
    MESSAGE_MOTIF_FORCAGE_REQUIS,
    ErreurPreuveResolution,
    valider_verdict_ia,
    verifier_motif_forcage,
)


def test_verdict_probante_valide():
    out = valider_verdict_ia(
        {
            "verdict": "probante",
            "justification": "  Quittance DGI datée et signée.  ",
            "elements_retrouves": ["quittance n°123", "montant réglé"],
        }
    )
    assert out["verdict"] == "probante"
    assert out["justification"] == "Quittance DGI datée et signée."
    assert out["elements_retrouves"] == ["quittance n°123", "montant réglé"]


@pytest.mark.parametrize(
    "verdict",
    ["", None, "PROBANT", "valide", 42, "indisponible", "ok"],
)
def test_verdict_invalide_devient_indisponible(verdict):
    out = valider_verdict_ia({"verdict": verdict, "justification": "x"})
    assert out["verdict"] == "indisponible"


def test_verdict_normalise_casse_et_espaces():
    out = valider_verdict_ia({"verdict": "  Insuffisante ", "justification": "j"})
    assert out["verdict"] == "insuffisante"


def test_justification_coercee_str():
    out = valider_verdict_ia({"verdict": "sans_rapport", "justification": 123})
    assert out["justification"] == "123"


def test_justification_vide_message_neutre():
    out = valider_verdict_ia({"verdict": "probante"})
    assert out["justification"] == "Verdict rendu sans justification détaillée."
    out2 = valider_verdict_ia({})
    assert out2["verdict"] == "indisponible"
    assert out2["justification"] == MESSAGE_ANALYSE_INDISPONIBLE


def test_justification_tronquee():
    out = valider_verdict_ia(
        {"verdict": "probante", "justification": "x" * 5000}
    )
    assert len(out["justification"]) == 2000


@pytest.mark.parametrize("brut", [None, "texte", [], 7])
def test_json_non_dict_tolere(brut):
    out = valider_verdict_ia(brut)
    assert out["verdict"] == "indisponible"
    assert out["elements_retrouves"] == []


def test_elements_retrouves_nettoyes():
    out = valider_verdict_ia(
        {
            "verdict": "probante",
            "justification": "j",
            "elements_retrouves": ["  a  ", "", None, 5],
        }
    )
    assert out["elements_retrouves"] == ["a", "5"]


def test_elements_retrouves_non_liste_ignores():
    out = valider_verdict_ia(
        {"verdict": "probante", "justification": "j", "elements_retrouves": "x"}
    )
    assert out["elements_retrouves"] == []


def test_decision_acceptee_si_probante():
    assert verifier_motif_forcage("probante", None) == ("acceptee", None)
    assert verifier_motif_forcage("probante", "  motif ignoré ") == (
        "acceptee",
        None,
    )


@pytest.mark.parametrize(
    "verdict", ["insuffisante", "sans_rapport", "indisponible"]
)
def test_motif_forcage_obligatoire_si_non_probante(verdict):
    with pytest.raises(ErreurPreuveResolution) as exc:
        verifier_motif_forcage(verdict, None)
    assert str(exc.value) == MESSAGE_MOTIF_FORCAGE_REQUIS
    with pytest.raises(ErreurPreuveResolution):
        verifier_motif_forcage(verdict, "   ")


def test_forcage_avec_motif():
    assert verifier_motif_forcage("insuffisante", "  Régularisé hors DGI ") == (
        "forcee",
        "Régularisé hors DGI",
    )


def test_resolution_refusee_sans_analyse():
    with pytest.raises(ErreurPreuveResolution) as exc:
        verifier_motif_forcage(None, "motif")
    assert "Analysez la preuve" in str(exc.value)


def test_message_blocage_resolution_sans_preuve():
    from backend.plateforme.preuve_resolution import MESSAGE_PREUVE_REQUISE

    assert "Résolu" in MESSAGE_PREUVE_REQUISE
    assert "preuve" in MESSAGE_PREUVE_REQUISE
