"""Contrôles de vraisemblance FEC — fonction pure, jamais bloquante."""
from datetime import date
from decimal import Decimal

from backend.socle.controles_fec import controles_vraisemblance_fec
from backend.socle.modeles import EcritureFec

EXERCICE = 2024


def _e(
    num: str,
    compte: str,
    debit: str = "0",
    credit: str = "0",
    *,
    journal: str = "VT",
    jour: date | None = None,
) -> EcritureFec:
    return EcritureFec(
        journal_code=journal,
        ecriture_num=num,
        ecriture_date=jour or date(EXERCICE, 3, 15),
        compte_num=compte,
        compte_lib=None,
        debit=Decimal(debit),
        credit=Decimal(credit),
    )


def _par_code(controles: list[dict]) -> dict[str, dict]:
    return {c["code"]: c for c in controles}


def _fec_sain() -> list[EcritureFec]:
    return [
        _e("1", "411100", debit="100"),
        _e("1", "701100", credit="100"),
        _e("2", "411100", debit="50"),
        _e("2", "701100", credit="50"),
    ]


def test_structure_et_tout_ok():
    controles = controles_vraisemblance_fec(_fec_sain(), EXERCICE)
    codes = [c["code"] for c in controles]
    assert codes == [
        "ecritures_non_equilibrees",
        "dates_hors_exercice",
        "doublons_stricts",
        "comptes_hors_plan",
        "trous_sequence",
    ]
    for c in controles:
        assert c["statut"] == "ok"
        assert c["compteur"] == 0
        assert c["echantillon"] == []
        assert c["libelle"]


def test_ecriture_non_equilibree():
    lignes = _fec_sain() + [
        _e("3", "411100", debit="80"),
        _e("3", "701100", credit="70"),
    ]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "ecritures_non_equilibrees"
    ]
    assert c["statut"] == "alerte"
    assert c["compteur"] == 1
    assert len(c["echantillon"]) == 1
    assert "VT/3" in c["echantillon"][0]["valeur"]


def test_date_hors_exercice():
    lignes = _fec_sain() + [
        _e("3", "411100", debit="10", jour=date(2023, 12, 31)),
        _e("3", "701100", credit="10", jour=date(2023, 12, 31)),
    ]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "dates_hors_exercice"
    ]
    assert c["statut"] == "alerte"
    assert c["compteur"] == 2
    assert c["echantillon"][0]["valeur"] == "2023-12-31"


def test_doublon_strict():
    lignes = _fec_sain() + [_e("1", "411100", debit="100")]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "doublons_stricts"
    ]
    assert c["statut"] == "alerte"
    assert c["compteur"] == 1
    assert c["echantillon"][0]["ligne"] == 5
    assert "411100" in c["echantillon"][0]["valeur"]


def test_compte_classe_9_et_non_numerique():
    lignes = _fec_sain() + [
        _e("3", "911000", debit="20"),
        _e("3", "ANA-01", credit="20"),
    ]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "comptes_hors_plan"
    ]
    assert c["statut"] == "alerte"
    assert c["compteur"] == 2
    valeurs = {occ["valeur"] for occ in c["echantillon"]}
    assert valeurs == {"911000", "ANA-01"}


def test_trou_de_sequence_par_journal():
    lignes = _fec_sain() + [
        _e("5", "411100", debit="30"),
        _e("5", "701100", credit="30"),
        # journal distinct : séquence indépendante, pas de faux positif.
        _e("1", "512100", debit="30", journal="BQ"),
        _e("1", "411100", credit="30", journal="BQ"),
    ]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "trous_sequence"
    ]
    assert c["statut"] == "alerte"
    assert c["compteur"] == 1
    assert "journal VT : saut de 2 à 5" in c["echantillon"][0]["valeur"]


def test_echantillon_plafonne_a_5():
    lignes = _fec_sain() + [
        _e(str(10 + i), "411100", debit="1", jour=date(2022, 1, 2))
        for i in range(8)
    ]
    c = _par_code(controles_vraisemblance_fec(lignes, EXERCICE))[
        "dates_hors_exercice"
    ]
    assert c["compteur"] == 8
    assert len(c["echantillon"]) == 5
