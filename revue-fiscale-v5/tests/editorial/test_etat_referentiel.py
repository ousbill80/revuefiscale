"""État référentiel — scan honnête, sans invention fiscale."""
from __future__ import annotations

from pathlib import Path

from backend.editorial.etat_referentiel import construire_etat, ecrire_doc, rendre_markdown

RACINE = Path(__file__).resolve().parents[2]
REFERENTIEL = RACINE / "referentiel"


def test_etat_compte_57_fiches_et_a_confirmer():
    etat = construire_etat(REFERENTIEL)
    t = etat["totaux"]
    assert t["fiches_yaml"] == 57
    assert t["fiches_marque_emplacement"] == 0
    assert t["fiches_avec_a_confirmer"] == 57
    assert t["fiches_sans_a_confirmer"] == 0
    assert t["mentions_a_confirmer"] >= 57
    assert etat["verite_operationnelle"]["aucune_fiche_certifiee"] is True


def test_corpus_sans_cgi_est_en_attente_pas_runtime():
    """CGI absent = statut éditorial ; le SaaS n'est pas arrêté."""
    etat = construire_etat(REFERENTIEL)
    assert etat["corpus"]["cgi_extractible"] is False
    assert etat["corpus"]["bloque_runtime"] is False
    assert etat["verite_operationnelle"]["bloque_runtime"] is False
    assert etat["corpus"]["statut_editorial"] == "en_attente_corpus"
    msg = etat["corpus"]["message_editorial"] or etat["corpus"]["blocage"]
    assert msg
    assert "CGI" in msg
    assert "stop runtime" in msg.lower() or "n'est pas arrêté" in msg.lower()
    # Annexe éventuelle (corpus_sources/) ≠ CGI : ne suffit pas pour purge 18 G
    if etat["corpus"].get("annexe_extractible"):
        assert "annexe" in msg.lower() or "18 G" in msg


def test_classer_pdf_distingue_cgi_et_annexe():
    from backend.editorial.etat_referentiel import _classer_pdf

    assert _classer_pdf("CGI-CI-2026.pdf", "corpus_sources/CGI-CI-2026.pdf") == "candidat_cgi"
    assert (
        _classer_pdf(
            "Annexe-1-Annexe-Fiscale-2026.pdf",
            "corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf",
        )
        == "candidat_annexe"
    )
    assert _classer_pdf("rapport-170.pdf", "fixtures/demo_exports/rapport-170.pdf") == (
        "export_demo"
    )


def test_ecrire_doc_markdown(tmp_path: Path):
    doc = tmp_path / "14-etat-referentiel.md"
    etat = ecrire_doc(REFERENTIEL, chemin_doc=doc)
    assert doc.is_file()
    texte = doc.read_text(encoding="utf-8")
    assert "État du référentiel" in texte
    assert "a_confirmer" in texte
    assert str(etat["totaux"]["fiches_yaml"]) in texte
    assert "Aucun taux" in rendre_markdown(etat)
