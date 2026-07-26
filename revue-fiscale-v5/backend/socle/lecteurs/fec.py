"""Lecteur FEC-like — colonnes minimales, separateur | / tab / csv."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.modeles import EcritureFec

_COLONNES = (
    "journalcode",
    "ecriturenum",
    "ecrituredate",
    "comptenum",
    "comptelib",
    "debit",
    "credit",
)


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


def _date_fec(valeur: str, ligne_no: int) -> date:
    texte = (valeur or "").strip()
    if not texte:
        raise ErreurLectureBalance(f"ligne {ligne_no} : EcritureDate vide")
    if len(texte) == 8 and texte.isdigit():
        try:
            return date(int(texte[:4]), int(texte[4:6]), int(texte[6:8]))
        except ValueError as e:
            raise ErreurLectureBalance(
                f"ligne {ligne_no} : EcritureDate invalide ({valeur!r})"
            ) from e
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            continue
    raise ErreurLectureBalance(f"ligne {ligne_no} : EcritureDate invalide ({valeur!r})")


def _detecter_delimiteur(premiere_ligne: str) -> str:
    if "|" in premiere_ligne:
        return "|"
    if "\t" in premiere_ligne:
        return "\t"
    return ","


def parser_fec(contenu: str | bytes, *, delimiteur: str | None = None) -> list[EcritureFec]:
    """Parse un FEC-like (colonnes minimales JournalCode…Debit/Credit).

    Separateur : pipe, tabulation ou virgule. Entete obligatoire (noms FEC).
    """
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    texte = contenu.strip()
    if not texte:
        raise ErreurLectureBalance("fichier FEC vide")

    premiere = texte.splitlines()[0]
    if delimiteur is None:
        delimiteur = _detecter_delimiteur(premiere)

    lecteur = csv.reader(io.StringIO(texte), delimiter=delimiteur)
    lignes_brutes = list(lecteur)
    if not lignes_brutes:
        raise ErreurLectureBalance("fichier FEC vide")

    entete = [c.strip().lower().replace("_", "") for c in lignes_brutes[0]]
    manquantes = [c for c in _COLONNES if c not in entete]
    if manquantes:
        raise ErreurLectureBalance(
            "entete FEC attendu : JournalCode|EcritureNum|EcritureDate|"
            "CompteNum|CompteLib|Debit|Credit"
        )

    idx = {nom: entete.index(nom) for nom in _COLONNES}
    resultat: list[EcritureFec] = []
    for no, raw in enumerate(lignes_brutes[1:], start=2):
        if not raw or all(not c.strip() for c in raw):
            continue
        besoin = max(idx.values())
        if len(raw) <= besoin:
            raise ErreurLectureBalance(f"ligne {no} : colonnes insuffisantes")
        compte = raw[idx["comptenum"]].strip()
        if not compte:
            raise ErreurLectureBalance(f"ligne {no} : CompteNum vide")
        journal = raw[idx["journalcode"]].strip()
        if not journal:
            raise ErreurLectureBalance(f"ligne {no} : JournalCode vide")
        num = raw[idx["ecriturenum"]].strip()
        if not num:
            raise ErreurLectureBalance(f"ligne {no} : EcritureNum vide")
        resultat.append(
            EcritureFec(
                journal_code=journal,
                ecriture_num=num,
                ecriture_date=_date_fec(raw[idx["ecrituredate"]], no),
                compte_num=compte,
                compte_lib=raw[idx["comptelib"]].strip() or None,
                debit=_dec(raw[idx["debit"]], "Debit", no),
                credit=_dec(raw[idx["credit"]], "Credit", no),
            )
        )

    if not resultat:
        raise ErreurLectureBalance("aucune ecriture FEC")
    return resultat
