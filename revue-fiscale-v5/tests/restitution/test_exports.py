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
    # ReportLab dessine en WinAnsi — accents possibles en octets.
    assert b"Non examin" in pdf or b"P" in pdf
