"""Classification type_piece — heuristiques nom / texte (sans clés API)."""
from __future__ import annotations

from backend.abonne.classification_piece import (
    classer_par_nom,
    classer_par_texte,
    classer_piece,
)


def test_classer_nom_dfe_zenapi():
    typ, conf = classer_par_nom("DFE ZenAPI SAS-2023 (4).pdf")
    assert typ == "dfe"
    assert conf >= 0.6


def test_classer_nom_rccm():
    typ, _ = classer_par_nom("extrait_RCCM_CI-ABJ.pdf")
    assert typ == "rccm"


def test_classer_texte_dfe():
    texte = (
        "DECLARATION FISCALE D'EXISTENCE\n"
        "PERSONNES MORALES\n"
        "N° de compte contribuable : 2300228 C\n"
        "Régime d'imposition RNI\n"
    )
    typ, conf = classer_par_texte(texte)
    assert typ == "dfe"
    assert conf >= 0.65


def test_classer_piece_prefer_contenu_sur_mauvais_nom(monkeypatch):
    """Nom trompeur + texte DFE clair → dfe."""
    monkeypatch.setattr(
        "backend.abonne.classification_piece._classer_par_vision",
        lambda *a, **k: (None, 0.0, None),
    )
    res = classer_piece(
        "rccm-scan.txt",
        (
            b"DECLARATION FISCALE D'EXISTENCE\n"
            b"Identification du contribuable\n"
            b"N de compte contribuable 1234567A\n"
            b"Direction Generale des Impots\n"
        ),
        autoriser_vision=False,
    )
    assert res["type_piece"] == "dfe"
    assert res["type_detecte_auto"] is True
    assert res["type_source"] == "texte"


def test_classer_piece_nom_dfe_malgre_label_manuel_absent(monkeypatch):
    """Fichier nommé DFE… même si on aurait pu le typé RCCM à la main."""
    monkeypatch.setattr(
        "backend.abonne.classification_piece._extraire_texte_rapide",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "backend.abonne.classification_piece._classer_par_vision",
        lambda *a, **k: (None, 0.0, None),
    )
    res = classer_piece(
        "DFE ZenAPI SAS-2023 (4).pdf",
        b"%PDF-1.4",
        autoriser_vision=False,
    )
    assert res["type_piece"] == "dfe"


def test_classer_piece_nom_seul_sans_texte(monkeypatch):
    monkeypatch.setattr(
        "backend.abonne.classification_piece._extraire_texte_rapide",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "backend.abonne.classification_piece._classer_par_vision",
        lambda *a, **k: (None, 0.0, None),
    )
    res = classer_piece(
        "DFE.pdf",
        b"%PDF-1.4 scan",
        autoriser_vision=False,
    )
    assert res["type_piece"] == "dfe"
    assert res["type_source"] == "nom_fichier"


def test_classer_piece_skip_vision_si_nom_dfe_fiable(monkeypatch):
    """PDF scan nommé DFE : heuristique nom suffit — pas d'appel vision."""
    appels = {"n": 0}

    def _vision(*_a, **_k):
        appels["n"] += 1
        return ("autre", 0.9, "ne doit pas être appelé")

    monkeypatch.setattr(
        "backend.abonne.classification_piece._extraire_texte_rapide",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "backend.abonne.classification_piece._classer_par_vision",
        _vision,
    )
    res = classer_piece(
        "DFE ZenAPI SAS-2023 (4).pdf",
        b"%PDF-1.4 scan sans texte",
        autoriser_vision=True,
    )
    assert res["type_piece"] == "dfe"
    assert res["type_source"] == "nom_fichier"
    assert appels["n"] == 0
    assert res["type_confiance"] >= 0.7


def test_classer_piece_vision_si_nom_ambigu(monkeypatch):
    """Nom sans indice + scan → vision autorisée."""
    appels = {"n": 0}

    def _vision(*_a, **_k):
        appels["n"] += 1
        return ("dfe", 0.88, "lu titre DFE")

    monkeypatch.setattr(
        "backend.abonne.classification_piece._extraire_texte_rapide",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        "backend.abonne.classification_piece._classer_par_vision",
        _vision,
    )
    res = classer_piece(
        "scan_document.pdf",
        b"%PDF-1.4",
        autoriser_vision=True,
    )
    assert appels["n"] == 1
    assert res["type_piece"] == "dfe"
    assert res["type_source"] == "vision"
