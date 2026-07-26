"""Mentions légales facture + paliers À CONFIRMER — pas d'invention."""
from __future__ import annotations

from backend.billing.factures import rendre_facture_pdf
from backend.config import Config
from backend.plateforme.paliers import TARIFS_A_CONFIRMER, TARIFS_AVERTISSEMENT


def test_mentions_legales_defaut_a_confirmer():
    cfg = Config.model_construct(
        facture_raison_sociale="",
        facture_siege="",
        facture_siedge="",
        facture_rccm="",
        facture_idu="",
        facture_compte_bancaire="",
        facture_regime_tva="",
        facture_taux_tva="",
    )
    m = cfg.mentions_legales_facture()
    assert "À CONFIRMER" in m["raison_sociale"]
    assert m["siege"] == "À CONFIRMER"
    assert m["rccm"] == "À CONFIRMER"
    assert m["regime_tva"] == "A_CONFIRMER"
    assert "CI-ABJ" not in m["rccm"]


def test_alias_facture_siedge_prioritaire():
    cfg = Config.model_construct(
        facture_siege="Siège A",
        facture_siedge="Siège B (alias)",
        facture_raison_sociale="2AàZ SAS — À CONFIRMER",
        facture_rccm="À CONFIRMER",
        facture_idu="À CONFIRMER",
        facture_compte_bancaire="À CONFIRMER",
        facture_regime_tva="A_CONFIRMER",
        facture_taux_tva="À CONFIRMER",
    )
    assert cfg.mentions_legales_facture()["siege"] == "Siège B (alias)"


def test_pdf_facture_genere_sans_erreur():
    """PDF commercial minimal — contenu compressé ; on vérifie génération + taille."""
    pdf = rendre_facture_pdf(
        {
            "numero": "FA-TEST-1",
            "denomination": "Cabinet Demo",
            "tenant_id": 1,
            "periode": "2026-01-01",
            "palier": "standard",
            "statut": "brouillon",
            "montant": "350000",
            "devise": "XOF",
            "note": "A CONFIRMER — tarif provisoire",
        }
    )
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 400


def test_tarifs_explicitement_a_confirmer():
    assert TARIFS_A_CONFIRMER is True
    assert "CONFIRMER" in TARIFS_AVERTISSEMENT.upper()
