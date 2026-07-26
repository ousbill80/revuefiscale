"""Lecteur etats financiers — postes bilan / compte de resultat (CSV ou JSON)."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal, InvalidOperation

from backend.socle.erreurs import ErreurLectureBalance
from backend.socle.modeles import LigneEtatFinancier


def _dec(valeur: object, champ: str, ligne_no: int) -> Decimal:
    if valeur is None or valeur == "":
        raise ErreurLectureBalance(f"ligne {ligne_no} : {champ} manquant")
    texte = str(valeur).strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(texte)
    except InvalidOperation as e:
        raise ErreurLectureBalance(
            f"ligne {ligne_no} : {champ} non numerique ({valeur!r})"
        ) from e


def _dec_opt(valeur: object, champ: str, ligne_no: int) -> Decimal | None:
    if valeur is None or str(valeur).strip() == "":
        return None
    return _dec(valeur, champ, ligne_no)


def parser_etats_financiers_json(contenu: str | bytes) -> list[LigneEtatFinancier]:
    """Parse un JSON {lignes: [...]} ou une liste de postes."""
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    texte = contenu.strip()
    if not texte:
        raise ErreurLectureBalance("fichier etats financiers vide")
    try:
        data = json.loads(texte)
    except json.JSONDecodeError as e:
        raise ErreurLectureBalance(f"JSON illisible : {e}") from e

    if isinstance(data, dict):
        raw_lignes = data.get("lignes")
        if raw_lignes is None:
            raise ErreurLectureBalance("JSON attendu : {lignes: [...]}")
    elif isinstance(data, list):
        raw_lignes = data
    else:
        raise ErreurLectureBalance("JSON attendu : objet ou liste de postes")

    if not isinstance(raw_lignes, list) or not raw_lignes:
        raise ErreurLectureBalance("aucune ligne de poste")

    resultat: list[LigneEtatFinancier] = []
    for no, item in enumerate(raw_lignes, start=1):
        if not isinstance(item, dict):
            raise ErreurLectureBalance(f"ligne {no} : objet attendu")
        try:
            resultat.append(LigneEtatFinancier.model_validate(item))
        except Exception as e:
            raise ErreurLectureBalance(f"ligne {no} : {e}") from e
    return resultat


def parser_etats_financiers(
    contenu: str | bytes, *, delimiteur: str | None = None
) -> list[LigneEtatFinancier]:
    """Parse CSV/TSV : compte|poste,libelle,montant_n[,montant_n1].

    Detecte JSON si le contenu commence par '{' ou '['.
    """
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    texte = contenu.strip()
    if not texte:
        raise ErreurLectureBalance("fichier etats financiers vide")

    if texte[0] in "{[":
        return parser_etats_financiers_json(texte)

    if delimiteur is None:
        premiere_ligne = texte.splitlines()[0]
        delimiteur = "\t" if "\t" in premiere_ligne else ","

    lecteur = csv.reader(io.StringIO(texte), delimiter=delimiteur)
    lignes_brutes = list(lecteur)
    if not lignes_brutes:
        raise ErreurLectureBalance("fichier etats financiers vide")

    debut = 0
    entete = [c.strip().lower() for c in lignes_brutes[0]]
    i_compte, i_libelle, i_n, i_n1 = 0, 1, 2, None
    if "compte" in entete or "poste" in entete:
        debut = 1
        cle = "compte" if "compte" in entete else "poste"
        try:
            i_compte = entete.index(cle)
            i_libelle = entete.index("libelle") if "libelle" in entete else None
            if "montant_n" in entete:
                i_n = entete.index("montant_n")
            elif "montant" in entete:
                i_n = entete.index("montant")
            else:
                raise ValueError("montant_n")
            i_n1 = entete.index("montant_n1") if "montant_n1" in entete else None
        except ValueError as e:
            raise ErreurLectureBalance(
                "entete attendu : compte|poste,libelle,montant_n[,montant_n1]"
            ) from e
    else:
        i_libelle = 1 if len(lignes_brutes[0]) > 1 else None

    resultat: list[LigneEtatFinancier] = []
    for no, raw in enumerate(lignes_brutes[debut:], start=debut + 1):
        if not raw or all(not c.strip() for c in raw):
            continue
        if len(raw) <= max(i_compte, i_n):
            raise ErreurLectureBalance(f"ligne {no} : colonnes insuffisantes")
        compte = raw[i_compte].strip()
        if not compte:
            raise ErreurLectureBalance(f"ligne {no} : poste/compte vide")
        libelle = None
        if i_libelle is not None and i_libelle < len(raw):
            libelle = raw[i_libelle].strip() or None
        montant_n = _dec(raw[i_n] if i_n < len(raw) else "", "montant_n", no)
        montant_n1 = None
        if i_n1 is not None and i_n1 < len(raw):
            montant_n1 = _dec_opt(raw[i_n1], "montant_n1", no)
        resultat.append(
            LigneEtatFinancier(
                compte=compte,
                libelle=libelle,
                montant_n=montant_n,
                montant_n1=montant_n1,
            )
        )

    if not resultat:
        raise ErreurLectureBalance("aucune ligne de poste")
    return resultat
