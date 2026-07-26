"""Détection FEC/CSV/XLSX + limites distinctes pièces vs preuves — tests purs."""
from __future__ import annotations

from backend.abonne.formats_piece import (
    decoder_texte,
    detecter_format_tabulaire,
    est_en_tete_fec,
)

EN_TETE_FEC_PIPE = (
    "JournalCode|JournalLib|EcritureNum|EcritureDate|CompteNum|CompteLib|"
    "CompAuxNum|CompAuxLib|PieceRef|PieceDate|EcritureLib|Debit|Credit|"
    "EcritureLet|DateLet|ValidDate|Montantdevise|Idevise"
)
EN_TETE_FEC_TAB = EN_TETE_FEC_PIPE.replace("|", "\t")


def test_en_tete_fec_pipe_et_tab():
    assert est_en_tete_fec(EN_TETE_FEC_PIPE) is True
    assert est_en_tete_fec(EN_TETE_FEC_TAB) is True


def test_en_tete_fec_insensible_casse():
    assert est_en_tete_fec(EN_TETE_FEC_PIPE.lower()) is True


def test_en_tete_non_fec():
    assert est_en_tete_fec("nom;prenom;email;telephone;ville") is False
    assert est_en_tete_fec("JournalCode|Debit") is False
    assert est_en_tete_fec("") is False


def test_detection_fec_extension_txt():
    brut = (EN_TETE_FEC_PIPE + "\nVE|Ventes|1|20240101|701|Ventes||||"
            "F1|20240101|Vente|0|1000||||").encode("utf-8")
    assert detecter_format_tabulaire("ecritures.txt", brut) == "fec"
    assert detecter_format_tabulaire("ecritures.fec", brut) == "fec"


def test_detection_fec_prioritaire_sur_csv():
    brut = EN_TETE_FEC_TAB.encode("utf-8")
    assert detecter_format_tabulaire("export.csv", brut) == "fec"


def test_csv_texte_simple_accepte():
    brut = "nom;montant\nA;10\nB;20\n".encode("latin-1")
    assert detecter_format_tabulaire("balance.csv", brut) == "csv"


def test_txt_non_fec_refuse():
    assert detecter_format_tabulaire("notes.txt", b"simple texte libre") is None


def test_csv_octets_nuls_refuse():
    assert detecter_format_tabulaire("d.csv", b"nom;mont\x00ant\n") is None
    assert decoder_texte(b"a\x00b") is None


def test_xlsx_magic_zip_exige():
    zip_magic = b"PK\x03\x04" + b"\x00" * 32
    assert detecter_format_tabulaire("classeur.xlsx", zip_magic) == "xlsx"
    assert detecter_format_tabulaire("classeur.xlsx", b"pas un zip") is None


def test_zip_generique_refuse():
    zip_magic = b"PK\x03\x04" + b"\x00" * 32
    assert detecter_format_tabulaire("archive.zip", zip_magic) is None


def test_extension_inconnue_refusee():
    assert detecter_format_tabulaire("script.exe", b"MZ\x90\x00") is None


def test_limites_pieces_et_preuves_distinctes():
    from backend.abonne.routes import (
        MESSAGE_FICHIER_TROP_VOLUMINEUX,
        MESSAGE_PREUVE_TROP_VOLUMINEUSE,
        TAILLE_MAX_PIECE_OCTETS,
        TAILLE_MAX_PREUVE_OCTETS,
    )

    assert TAILLE_MAX_PIECE_OCTETS == 200 * 1024 * 1024
    assert TAILLE_MAX_PREUVE_OCTETS == 25 * 1024 * 1024
    assert "200 Mo" in MESSAGE_FICHIER_TROP_VOLUMINEUX
    assert "25 Mo" in MESSAGE_PREUVE_TROP_VOLUMINEUSE


def test_preuve_refuse_au_dela_de_25_mo():
    import pytest

    from backend.plateforme.preuve_resolution import (
        ErreurPreuveResolution,
        _verifier_fichier,
    )

    brut = b"%PDF" + b"0" * (25 * 1024 * 1024 + 1)
    with pytest.raises(ErreurPreuveResolution, match="25 Mo"):
        _verifier_fichier("preuve.pdf", "application/pdf", brut)


def test_classification_tabulaire_deterministe():
    from backend.abonne.classification_piece import classer_piece

    brut = EN_TETE_FEC_PIPE.encode("utf-8")
    out = classer_piece("fec_2024.txt", brut, autoriser_vision=True)
    assert out["type_piece"] == "autre"
    assert out["type_source"] == "format_fec"
    assert out["type_detecte_auto"] is True

    out_csv = classer_piece(
        "clients.csv", b"nom;ville\nA;Abidjan\n", autoriser_vision=True
    )
    assert out_csv["type_source"] == "format_csv"

    out_xlsx = classer_piece(
        "balance.xlsx", b"PK\x03\x04" + b"\x00" * 16, autoriser_vision=True
    )
    assert out_xlsx["type_source"] == "format_xlsx"
