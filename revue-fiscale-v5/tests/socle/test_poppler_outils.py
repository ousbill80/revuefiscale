"""Poppler / messages PDF scan — sans dépendance à une DB."""
from backend.socle import poppler_outils


def test_etat_poppler_structure():
    etat = poppler_outils.etat_poppler()
    assert "pdftotext" in etat
    assert "pdftoppm" in etat
    assert "ok" in etat
    assert etat["ok"] is (etat["pdftotext"] and etat["pdftoppm"])
    if not etat["ok"]:
        assert etat["conseil"]


def test_messages_poppler_non_vides():
    # Messages destinés à l'utilisateur final : pas de jargon technique
    # (poppler/pdftotext/pdftoppm), mais toujours une piste de repli.
    for msg in (
        poppler_outils.MESSAGE_PDFTOTEXT_ABSENT,
        poppler_outils.MESSAGE_PDFTOPPM_ABSENT,
        poppler_outils.MESSAGE_VISION_SANS_IMAGE,
    ):
        assert msg.strip()
        assert "manuellement" in msg.casefold()
    assert "pdf" in poppler_outils.MESSAGE_PDFTOTEXT_ABSENT.casefold()
    assert "pdf" in poppler_outils.MESSAGE_PDFTOPPM_ABSENT.casefold()
