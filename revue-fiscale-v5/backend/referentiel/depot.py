"""Depot referentiel — lecture des regles d une version epinglee."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RegleChargee:
    """Regle_version + metadonnees regle pour le moteur."""

    regle_version_id: int
    regle_id: str
    impot: str
    libelle: str
    comptes_declencheurs: list[str]
    nature: str
    condition_declenchement: str
    expression_resultat: str
    niveau_risque: str
    formule_plafonnement: str | None
    questions: list[Any]
    a_confirmer: list[Any]
    profils_applicables: list[Any]


def lire_regles_version(session: Session, version_id: int) -> list[RegleChargee]:
    """Charge toutes les regles actives d une version_referentiel."""
    rows = session.execute(
        text(
            "SELECT rv.id AS regle_version_id, rv.regle_id, r.impot, r.libelle, "
            "rv.comptes_declencheurs, rv.nature, rv.condition_declenchement, "
            "rv.expression_resultat, rv.niveau_risque, rv.formule_plafonnement, "
            "rv.questions, rv.a_confirmer, rv.profils_applicables "
            "FROM regle_version rv "
            "JOIN regle r ON r.identifiant = rv.regle_id "
            "WHERE rv.version_referentiel_id = :v AND r.actif = TRUE "
            "ORDER BY rv.regle_id"
        ),
        {"v": version_id},
    ).mappings().all()

    resultat: list[RegleChargee] = []
    for row in rows:
        comptes = row["comptes_declencheurs"] or []
        if isinstance(comptes, str):
            comptes = [comptes]
        resultat.append(
            RegleChargee(
                regle_version_id=int(row["regle_version_id"]),
                regle_id=str(row["regle_id"]),
                impot=str(row["impot"]),
                libelle=str(row["libelle"]),
                comptes_declencheurs=[str(c) for c in comptes],
                nature=str(row["nature"]),
                condition_declenchement=str(row["condition_declenchement"]),
                expression_resultat=str(row["expression_resultat"]),
                niveau_risque=str(row["niveau_risque"]),
                formule_plafonnement=row["formule_plafonnement"],
                questions=list(row["questions"] or []),
                a_confirmer=list(row["a_confirmer"] or []),
                profils_applicables=list(row["profils_applicables"] or []),
            )
        )
    return resultat
