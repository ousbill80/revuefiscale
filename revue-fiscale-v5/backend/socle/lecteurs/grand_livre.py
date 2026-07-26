"""Lecteur grand livre — ecritures CSV (compte, date, piece, libelle, debit, credit)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.modeles import EcritureGrandLivre


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


def _date_opt(valeur: str, ligne_no: int) -> date | None:
    texte = (valeur or "").strip()
    if not texte:
        return None
    if len(texte) == 8 and texte.isdigit():
        try:
            return date(int(texte[:4]), int(texte[4:6]), int(texte[6:8]))
        except ValueError as e:
            raise ErreurLectureBalance(f"ligne {ligne_no} : date invalide ({valeur!r})") from e
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            continue
    raise ErreurLectureBalance(f"ligne {ligne_no} : date invalide ({valeur!r})")


def parser_grand_livre(
    contenu: str | bytes, *, delimiteur: str | None = None
) -> list[EcritureGrandLivre]:
    """Parse un grand livre CSV/TSV.

    Colonnes : compte,date,piece,libelle,debit,credit. Entete optionnel.
    """
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    texte = contenu.strip()
    if not texte:
        raise ErreurLectureBalance("fichier grand livre vide")

    if delimiteur is None:
        premiere_ligne = texte.splitlines()[0]
        delimiteur = "\t" if "\t" in premiere_ligne else ","

    lecteur = csv.reader(io.StringIO(texte), delimiter=delimiteur)
    lignes_brutes = list(lecteur)
    if not lignes_brutes:
        raise ErreurLectureBalance("fichier grand livre vide")

    debut = 0
    entete = [c.strip().lower() for c in lignes_brutes[0]]
    if "compte" in entete:
        debut = 1
        try:
            i_compte = entete.index("compte")
            i_date = entete.index("date") if "date" in entete else None
            i_piece = entete.index("piece") if "piece" in entete else None
            i_libelle = entete.index("libelle") if "libelle" in entete else None
            i_debit = entete.index("debit")
            i_credit = entete.index("credit")
        except ValueError as e:
            raise ErreurLectureBalance(
                "entete attendu : compte,date,piece,libelle,debit,credit"
            ) from e
    else:
        i_compte, i_date, i_piece, i_libelle, i_debit, i_credit = 0, 1, 2, 3, 4, 5

    resultat: list[EcritureGrandLivre] = []
    for no, raw in enumerate(lignes_brutes[debut:], start=debut + 1):
        if not raw or all(not c.strip() for c in raw):
            continue
        if len(raw) <= max(i_compte, i_debit, i_credit):
            raise ErreurLectureBalance(f"ligne {no} : colonnes insuffisantes")
        compte = raw[i_compte].strip()
        if not compte:
            raise ErreurLectureBalance(f"ligne {no} : compte vide")
        date_ecriture = None
        if i_date is not None and i_date < len(raw):
            date_ecriture = _date_opt(raw[i_date], no)
        piece = None
        if i_piece is not None and i_piece < len(raw):
            piece = raw[i_piece].strip() or None
        libelle = None
        if i_libelle is not None and i_libelle < len(raw):
            libelle = raw[i_libelle].strip() or None
        debit = _dec(raw[i_debit] if i_debit < len(raw) else "0", "debit", no)
        credit = _dec(raw[i_credit] if i_credit < len(raw) else "0", "credit", no)
        resultat.append(
            EcritureGrandLivre(
                compte=compte,
                date_ecriture=date_ecriture,
                piece=piece,
                libelle=libelle,
                debit=debit,
                credit=credit,
            )
        )

    if not resultat:
        raise ErreurLectureBalance("aucune ecriture")
    return resultat
