"""Détection des formats tabulaires de pièces (FEC, CSV, XLSX) — pur, testable."""
from __future__ import annotations

from pathlib import Path

FORMATS_TABULAIRES = frozenset({"fec", "csv", "xlsx"})

_MAGIC_ZIP = b"PK\x03\x04"

_COLONNES_FEC = frozenset(
    {
        "journalcode",
        "journallib",
        "ecriturenum",
        "ecrituredate",
        "comptenum",
        "comptelib",
        "compauxnum",
        "compauxlib",
        "pieceref",
        "piecedate",
        "ecriturelib",
        "debit",
        "credit",
        "ecriturelet",
        "datelet",
        "validdate",
        "montantdevise",
        "idevise",
    }
)


def decoder_texte(brut: bytes) -> str | None:
    """Texte utf-8 / latin-1 — None si octets nuls ou indécodable."""
    if b"\x00" in brut:
        return None
    try:
        return brut.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return brut.decode("latin-1")
        except UnicodeDecodeError:
            return None


def est_en_tete_fec(ligne: str) -> bool:
    """Vrai si la ligne ressemble à un en-tête FEC (colonnes normalisées)."""
    for sep in ("|", "\t", ";"):
        champs = [c.strip().lower() for c in ligne.split(sep)]
        if len(champs) < 5:
            continue
        if sum(1 for c in champs if c in _COLONNES_FEC) >= 4:
            return True
    return False


def detecter_format_tabulaire(nom_fichier: str, brut: bytes) -> str | None:
    """'fec' | 'csv' | 'xlsx' selon extension + contenu — None si refusé.

    - .xlsx : magic ZIP obligatoire (les .zip génériques restent refusés).
    - .csv : texte décodable sans octet nul ; en-tête FEC → 'fec'.
    - .txt / .fec : acceptés uniquement si en-tête FEC détecté.
    """
    ext = Path(nom_fichier or "").suffix.lower()
    if ext == ".xlsx":
        return "xlsx" if brut.startswith(_MAGIC_ZIP) else None
    if ext not in {".csv", ".txt", ".fec"}:
        return None
    texte = decoder_texte(brut[:65536])
    if texte is None:
        return None
    premiere = texte.lstrip("\ufeff\r\n").splitlines()[0] if texte.strip() else ""
    if est_en_tete_fec(premiere):
        return "fec"
    if ext == ".csv":
        return "csv"
    return None
