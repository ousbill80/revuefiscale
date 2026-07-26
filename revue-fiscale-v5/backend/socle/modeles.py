"""Modeles Pydantic du socle de donnees."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TypePiece = Literal[
    "balance", "etats_financiers", "grand_livre", "fec", "autre"
]
RolePiece = Literal["source_active", "annexe"]


class LigneBalance(BaseModel):
    compte: str = Field(min_length=1, max_length=32)
    libelle: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


class BalanceJson(BaseModel):
    """Corps JSON balance. Champs meta (avertissement) ignorés par le moteur."""

    lignes: list[LigneBalance]
    avertissement: str | None = None


class LigneEtatFinancier(BaseModel):
    """Poste de bilan ou de compte de resultat."""

    compte: str = Field(min_length=1, max_length=32)
    libelle: str | None = None
    montant_n: Decimal
    montant_n1: Decimal | None = None

    @model_validator(mode="before")
    @classmethod
    def _alias_poste(cls, data: object) -> object:
        if isinstance(data, dict) and "compte" not in data and "poste" in data:
            data = {**data, "compte": data["poste"]}
        return data


class EtatsFinanciersJson(BaseModel):
    lignes: list[LigneEtatFinancier]


class EcritureGrandLivre(BaseModel):
    compte: str = Field(min_length=1, max_length=32)
    date_ecriture: date | None = None
    piece: str | None = None
    libelle: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


class EcritureFec(BaseModel):
    """Ligne FEC-like (colonnes minimales)."""

    journal_code: str = Field(min_length=1, max_length=32)
    ecriture_num: str = Field(min_length=1, max_length=64)
    ecriture_date: date
    compte_num: str = Field(min_length=1, max_length=32)
    compte_lib: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")

    @field_validator("ecriture_date", mode="before")
    @classmethod
    def _parse_date_fec(cls, valeur: object) -> object:
        if isinstance(valeur, date):
            return valeur
        texte = str(valeur or "").strip()
        if len(texte) == 8 and texte.isdigit():
            return date(int(texte[:4]), int(texte[4:6]), int(texte[6:8]))
        return valeur


class RapportFiab(BaseModel):
    mission_id: int
    statut: str  # ok | refuse
    anomalies: list[str]
    rapport_id: int | None = None
    nb_comptes: int = 0


class PieceOut(BaseModel):
    id: int
    mission_id: int
    type_piece: TypePiece
    role: RolePiece
    nom_fichier: str
    chemin_stockage: str
    taille_octets: int | None = None
    content_type: str | None = None
    cree_le: datetime | None = None


class DesigneSourceActiveOut(BaseModel):
    piece: PieceOut | None = None
    rapport: RapportFiab
    source_precedente_degradee: bool = False
