"""Lecteurs de fichiers sources — balance comptable."""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.modeles import LigneBalance


def _dec(valeur: str, champ: str, ligne_no: int) -> Decimal:
    texte = (valeur or "0").strip().replace(" ", "").replace(",", ".")
    if texte == "":
        texte = "0"
    try:
        return Decimal(texte)
    except InvalidOperation as e:
        raise ErreurLectureBalance(
            f"ligne {ligne_no} : {champ} non numerique ({valeur!r})"
        ) from e


def parser_balance(contenu: str | bytes, *, delimiteur: str | None = None) -> list[LigneBalance]:
    """Parse une balance CSV/TSV : compte,libelle,debit,credit.

    Detecte tab vs virgule si delimiteur non fourni. Entete optionnel.
    """
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    texte = contenu.strip()
    if not texte:
        raise ErreurLectureBalance("fichier vide")

    if delimiteur is None:
        premiere_ligne = texte.splitlines()[0]
        delimiteur = "\t" if "\t" in premiere_ligne else ","

    lecteur = csv.reader(io.StringIO(texte), delimiter=delimiteur)
    lignes_brutes = list(lecteur)
    if not lignes_brutes:
        raise ErreurLectureBalance("fichier vide")

    debut = 0
    entete = [c.strip().lower() for c in lignes_brutes[0]]
    if "compte" in entete:
        debut = 1
        try:
            i_compte = entete.index("compte")
            i_libelle = entete.index("libelle") if "libelle" in entete else None
            i_debit = entete.index("debit")
            i_credit = entete.index("credit")
        except ValueError as e:
            raise ErreurLectureBalance(
                "entete attendu : compte,libelle,debit,credit"
            ) from e
    else:
        i_compte, i_libelle, i_debit, i_credit = 0, 1, 2, 3

    resultat: list[LigneBalance] = []
    for no, raw in enumerate(lignes_brutes[debut:], start=debut + 1):
        if not raw or all(not c.strip() for c in raw):
            continue
        if len(raw) <= max(i_compte, i_debit, i_credit):
            raise ErreurLectureBalance(f"ligne {no} : colonnes insuffisantes")
        compte = raw[i_compte].strip()
        if not compte:
            raise ErreurLectureBalance(f"ligne {no} : compte vide")
        libelle = None
        if i_libelle is not None and i_libelle < len(raw):
            libelle = raw[i_libelle].strip() or None
        debit = _dec(raw[i_debit] if i_debit < len(raw) else "0", "debit", no)
        credit = _dec(raw[i_credit] if i_credit < len(raw) else "0", "credit", no)
        resultat.append(
            LigneBalance(compte=compte, libelle=libelle, debit=debit, credit=credit)
        )

    if not resultat:
        raise ErreurLectureBalance("aucune ligne de compte")
    return resultat
