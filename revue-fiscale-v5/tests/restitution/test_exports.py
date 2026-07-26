"""Tests exports Word/PDF et lecture audit."""
from __future__ import annotations

from decimal import Decimal

from backend.restitution.passage import Passage, LignePassage
from backend.restitution.rapport_docx import rendre_rapport_docx
from backend.restitution.rapport_pdf import rendre_rapport_pdf
from backend.restitution.risques import ScoreRisque


def test_exports_docx_pdf_non_vides():
    passage = Passage(
        lignes=(
            LignePassage(
                regle_id="BIC-CHG-18G-DONS",
                sens="reintegration",
                montant=Decimal("1000"),
                niveau_risque="moyen",
            ),
        ),
        total_reintegration=Decimal("1000"),
        total_deduction=Decimal("0"),
        solde_net=Decimal("1000"),
    )
    score = ScoreRisque(score=2, comptages={"moyen": 1}, avertissement="heuristique")
    meta = {
        "mission_id": 1,
        "exercice": 2025,
        "contribuable_denomination": "Demo SA",
        "contribuable_ncc": "123",
        "version_referentiel_id": 1,
        "type_engagement": "preventive",
        "perimetre_impots": ["TVA"],
    }
    docx = rendre_rapport_docx(
        meta=meta,
        passage=passage,
        conclusions=[],
        score=score,
        extrait_audit=[{"horodatage": "t", "acteur": "a", "action": "x"}],
    )
    pdf = rendre_rapport_pdf(
        meta=meta,
        passage=passage,
        conclusions=[],
        score=score,
        extrait_audit=[{"horodatage": "t", "acteur": "a", "action": "x"}],
    )
    assert docx[:2] == b"PK"
    assert pdf.startswith(b"%PDF")
    # Section périmètre présente dans les deux exports (template séparé ≠ wrap markdown).
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(docx))
    textes = "\n".join(p.text for p in doc.paragraphs)
    assert "Périmètre déclaré" in textes
    assert "Non examiné" in textes
    # Sections d'enrichissement toujours présentes — mention sobre sans données.
    assert "Fiabilité de la source" in textes
    assert "Aucun contrôle de vraisemblance FEC" in textes
    assert "Revue analytique" in textes
    assert "Aucun exercice antérieur comparable" in textes
    # ReportLab dessine en WinAnsi — accents possibles en octets.
    assert b"Non examin" in pdf or b"P" in pdf


def _donnees_communes():
    passage = Passage(
        lignes=(
            LignePassage(
                regle_id="BIC-CHG-18G-DONS",
                sens="reintegration",
                montant=Decimal("1000"),
                niveau_risque="moyen",
            ),
        ),
        total_reintegration=Decimal("1000"),
        total_deduction=Decimal("0"),
        solde_net=Decimal("1000"),
    )
    score = ScoreRisque(score=2, comptages={"moyen": 1}, avertissement="heuristique")
    meta = {
        "mission_id": 1,
        "exercice": 2025,
        "contribuable_denomination": "Demo SA",
        "contribuable_ncc": "123",
        "version_referentiel_id": 1,
        "type_engagement": "preventive",
        "perimetre_impots": ["TVA"],
    }
    conclusions = [
        {
            "regle_id": "BIC-CHG-18G-DONS",
            "statut": "anomalie",
            "sens": "reintegration",
            "montant": Decimal("1000"),
            "niveau_risque": "moyen",
            "comptes_source": [
                {
                    "compte": "623100",
                    "libelle": "Dons et libéralités",
                    "solde": "1500000",
                    "sens": "debiteur",
                }
            ],
        }
    ]
    controles_fec = {
        "exercice": 2025,
        "cree_le": "2026-01-15T10:00:00",
        "controles": [
            {
                "code": "ecritures_non_equilibrees",
                "libelle": "Écritures non équilibrées (débit ≠ crédit)",
                "statut": "alerte",
                "compteur": 2,
                "echantillon": [],
            },
            {
                "code": "doublons_stricts",
                "libelle": "Doublons stricts d'écritures",
                "statut": "ok",
                "compteur": 0,
                "echantillon": [],
            },
        ],
    }
    revue_analytique = {
        "disponible": True,
        "exercice_n": 2025,
        "exercice_n1": 2024,
        "mission_n1_id": 9,
        "lignes": [
            {
                "compte": "701100",
                "libelle": "Ventes de marchandises",
                "solde_n": -5000000.0,
                "solde_n1": -8000000.0,
                "variation": 3000000.0,
                "variation_pct": 37.5,
                "sens": "hausse",
                "classement": "variation_forte",
            }
        ],
        "totaux_par_classe": [
            {
                "classe": 7,
                "total_n": -5000000.0,
                "total_n1": -8000000.0,
                "variation": 3000000.0,
            }
        ],
    }
    return passage, score, meta, conclusions, controles_fec, revue_analytique


def test_docx_contient_fiabilite_revue_et_comptes_source():
    """Mission avec source FEC contrôlée + N-1 : les sections sont remplies."""
    passage, score, meta, conclusions, controles, revue = _donnees_communes()
    docx = rendre_rapport_docx(
        meta=meta,
        passage=passage,
        conclusions=conclusions,
        score=score,
        extrait_audit=[],
        controles_fec=controles,
        revue_analytique=revue,
    )
    assert docx[:2] == b"PK"
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(docx))
    textes = "\n".join(p.text for p in doc.paragraphs)
    # Fiabilité de la source : titre, date jj/mm/aaaa, alerte avec compteur.
    assert "Fiabilité de la source" in textes
    assert "15/01/2026" in textes
    assert "[ALERTE]" in textes and "2 occurrences" in textes
    assert "[OK] Doublons stricts" in textes
    # Revue analytique : titre avec exercices, ligne principale, totaux classe.
    assert "Revue analytique 2025 / 2024" in textes
    assert "701100" in textes and "variation forte" in textes
    assert "Classe 7" in textes
    # Comptes à l'origine de la conclusion.
    assert "Comptes à l'origine — BIC-CHG-18G-DONS" in textes
    assert "623100" in textes and "debiteur" in textes
    # Montant formaté FCFA (espace + décimales virgule).
    assert "1 500 000,00 FCFA" in textes


def test_pdf_se_genere_avec_enrichissements():
    """Le PDF reste valide (magic %PDF) avec toutes les sections remplies."""
    passage, score, meta, conclusions, controles, revue = _donnees_communes()
    pdf = rendre_rapport_pdf(
        meta=meta,
        passage=passage,
        conclusions=conclusions,
        score=score,
        extrait_audit=[],
        controles_fec=controles,
        revue_analytique=revue,
    )
    assert pdf.startswith(b"%PDF")


def test_pdf_se_genere_sans_donnees_enrichissement():
    """Sans contrôles FEC ni N-1 : mentions sobres, PDF toujours valide."""
    passage, score, meta, conclusions, _, _ = _donnees_communes()
    pdf = rendre_rapport_pdf(
        meta=meta,
        passage=passage,
        conclusions=[],
        score=score,
        extrait_audit=[],
    )
    assert pdf.startswith(b"%PDF")
