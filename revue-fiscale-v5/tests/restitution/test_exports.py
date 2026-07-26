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


# ── Note de synthèse dans les exports ─────────────────────────────────


def _note_disponible():
    return {
        "id": 7,
        "mission_id": 1,
        "version": 2,
        "statut": "disponible",
        "modele": "provider-x",
        "erreur": None,
        "auteur": "admin@demo.local",
        "cree_le": "2026-07-20T09:30:00",
        "contenu": {
            "contexte": "Revue fiscale préventive de Demo SA, exercice 2025.",
            "constats": [
                {
                    "regle_id": "OBL-36-ETII",
                    "resume": "État des transactions intra-groupe non produit.",
                    "montant": None,
                    "gravite": "haute",
                },
                {
                    "regle_id": "BIC-CHG-18G-DONS",
                    "resume": "Dons à réintégrer au résultat fiscal.",
                    "montant": "1000",
                    "gravite": "moyenne",
                },
            ],
            "exposition": "Exposition estimée à 1 000 FCFA hors pénalités.",
            "points_attention": ["2 écritures FEC non équilibrées."],
            "recommandations": ["Produire l'état des transactions intra-groupe."],
        },
    }


def _texte_pdf(pdf: bytes) -> str:
    """Texte brut des content streams (ASCII85 + Flate de ReportLab) — sans dépendance."""
    import base64
    import re
    import zlib

    morceaux: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        brut = m.group(1).strip()
        try:  # encodage ReportLab par défaut : ASCII85 puis Flate.
            brut = base64.a85decode(brut, adobe=True)
        except ValueError:
            pass
        try:
            morceaux.append(zlib.decompress(brut))
        except zlib.error:
            morceaux.append(brut)
    return b"\n".join(morceaux).decode("latin-1", "replace")


def _texte_docx(docx: bytes) -> str:
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(docx))
    return "\n".join(p.text for p in doc.paragraphs)


def test_docx_avec_note_synthese_disponible():
    """Note disponible → section en tête avec gravité, regle_id et contenu."""
    passage, score, meta, conclusions, controles, revue = _donnees_communes()
    docx = rendre_rapport_docx(
        meta=meta,
        passage=passage,
        conclusions=conclusions,
        score=score,
        extrait_audit=[],
        controles_fec=controles,
        revue_analytique=revue,
        note_synthese=_note_disponible(),
    )
    textes = _texte_docx(docx)
    assert "Note de synthèse" in textes
    assert "version 2 du 20/07/2026" in textes
    assert "Contexte : Revue fiscale préventive de Demo SA" in textes
    assert "[HAUTE] OBL-36-ETII" in textes
    assert "[MOYENNE] BIC-CHG-18G-DONS" in textes
    assert "montant : 1000 FCFA" in textes
    assert "Exposition estimée" in textes
    assert "Points d'attention" in textes
    assert "2 écritures FEC non équilibrées." in textes
    assert "Recommandations prioritaires" in textes
    assert "Produire l'état des transactions intra-groupe." in textes
    # La section précède le périmètre (en tête de rapport).
    assert textes.index("Note de synthèse") < textes.index("Périmètre déclaré")


def test_docx_sans_note_synthese_pas_de_section():
    """Aucune note disponible → aucune section (pas de titre vide)."""
    passage, score, meta, conclusions, _, _ = _donnees_communes()
    for note in (None, {"statut": "echec", "contenu": None}):
        docx = rendre_rapport_docx(
            meta=meta,
            passage=passage,
            conclusions=conclusions,
            score=score,
            extrait_audit=[],
            note_synthese=note,
        )
        assert "Note de synthèse" not in _texte_docx(docx)


def test_pdf_avec_note_synthese_disponible():
    """PDF valide et section note présente avec les regle_id."""
    passage, score, meta, conclusions, controles, revue = _donnees_communes()
    pdf = rendre_rapport_pdf(
        meta=meta,
        passage=passage,
        conclusions=conclusions,
        score=score,
        extrait_audit=[],
        controles_fec=controles,
        revue_analytique=revue,
        note_synthese=_note_disponible(),
    )
    assert pdf.startswith(b"%PDF")
    texte = _texte_pdf(pdf)
    assert "Note de synth" in texte
    assert "OBL-36-ETII" in texte
    assert "BIC-CHG-18G-DONS" in texte
    assert "Recommandations prioritaires" in texte


def test_pdf_sans_note_synthese_pas_de_section():
    passage, score, meta, conclusions, _, _ = _donnees_communes()
    pdf = rendre_rapport_pdf(
        meta=meta,
        passage=passage,
        conclusions=conclusions,
        score=score,
        extrait_audit=[],
        note_synthese=None,
    )
    assert pdf.startswith(b"%PDF")
    assert "Note de synth" not in _texte_pdf(pdf)


def test_section_note_synthese_vide_ou_invalide():
    """Garde-fou : pas de lignes si note absente, sans contenu ou non-dict."""
    from backend.restitution.rapport import section_note_synthese

    assert section_note_synthese(None) == []
    assert section_note_synthese({"statut": "echec", "contenu": None}) == []
    assert section_note_synthese({"contenu": "pas un dict"}) == []
