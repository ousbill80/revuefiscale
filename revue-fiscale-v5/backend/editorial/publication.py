"""Publication de versions du referentiel — domaine editorial (sans tenant_id)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.referentiel.expressions import ErreurSyntaxe, analyser

CHAMPS_REQUIS = {
    "identifiant",
    "impot",
    "reference_legale",
    "date_effet",
    "profils_applicables",
    "comptes_declencheurs",
    "nature",
    "condition_declenchement",
    "conditions_fond",
    "formule_plafonnement",
    "questions_generees",
    "resultat",
    "niveau_risque",
    "effets_croises",
}


class ErreurEditorial(Exception):
    """Echec de creation / publication / chargement editorial."""


def creer_version_brouillon(
    session: Session,
    libelle: str,
    *,
    note: str | None = None,
) -> int:
    """Cree une version non publiee (publiee_le IS NULL)."""
    libelle = libelle.strip()
    if not libelle:
        raise ErreurEditorial("libelle obligatoire")
    existe = session.execute(
        text("SELECT id FROM version_referentiel WHERE libelle = :l"),
        {"l": libelle},
    ).scalar_one_or_none()
    if existe is not None:
        raise ErreurEditorial(f"version deja existante : {libelle}")

    version_id = session.execute(
        text(
            "INSERT INTO version_referentiel (libelle, note) "
            "VALUES (:l, :n) RETURNING id"
        ),
        {"l": libelle, "n": note},
    ).scalar_one()
    session.flush()
    return int(version_id)


def publier_version(session: Session, libelle: str, par: str) -> int:
    """Publie une version brouillon. Refuse si deja publiee."""
    row = session.execute(
        text(
            "SELECT id, publiee_le FROM version_referentiel WHERE libelle = :l"
        ),
        {"l": libelle},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurEditorial(f"version introuvable : {libelle}")
    if row["publiee_le"] is not None:
        raise ErreurEditorial(f"version deja publiee : {libelle}")

    maintenant = datetime.now(UTC)
    session.execute(
        text(
            "UPDATE version_referentiel "
            "SET publiee_le = :d, publiee_par = :p WHERE id = :id"
        ),
        {"d": maintenant, "p": par, "id": row["id"]},
    )
    session.flush()
    return int(row["id"])


def _parser_date(valeur: object) -> date:
    if isinstance(valeur, date) and not isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, datetime):
        return valeur.date()
    return date.fromisoformat(str(valeur)[:10])


def _valider_expressions(regle: dict[str, Any]) -> None:
    for champ in ("condition_declenchement", "formule_plafonnement", "resultat"):
        expr = regle.get(champ)
        if isinstance(expr, str) and expr.strip() and expr.strip().lower() != "sans objet":
            try:
                analyser(expr)
            except ErreurSyntaxe as e:
                raise ErreurEditorial(f"{champ} : {e}") from e


def charger_regle_yaml(
    session: Session,
    version_id: int,
    chemin_ou_dict: str | Path | dict[str, Any],
) -> int:
    """Charge une regle YAML dans regle + regle_version pour version_id.

    Valide les expressions via analyser() avant insertion.
    Retourne l id de regle_version cree.
    """
    if isinstance(chemin_ou_dict, dict):
        regle = chemin_ou_dict
    else:
        path = Path(chemin_ou_dict)
        if not path.exists():
            raise ErreurEditorial(f"fichier introuvable : {path}")
        charge = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(charge, dict):
            raise ErreurEditorial("le fichier YAML ne contient pas une regle")
        regle = charge

    manquants = CHAMPS_REQUIS - set(regle)
    if manquants:
        raise ErreurEditorial(f"champs absents : {sorted(manquants)}")

    _valider_expressions(regle)

    version = session.execute(
        text("SELECT id FROM version_referentiel WHERE id = :id"),
        {"id": version_id},
    ).scalar_one_or_none()
    if version is None:
        raise ErreurEditorial(f"version_referentiel {version_id} introuvable")

    identifiant = str(regle["identifiant"])
    categorie = None
    parties = identifiant.split("-")
    if len(parties) >= 2:
        categorie = parties[1]

    session.execute(
        text(
            "INSERT INTO regle (identifiant, impot, categorie, libelle, actif) "
            "VALUES (:id, :imp, :cat, :lib, TRUE) "
            "ON CONFLICT (identifiant) DO UPDATE SET "
            "impot = EXCLUDED.impot, categorie = EXCLUDED.categorie, "
            "libelle = EXCLUDED.libelle, actif = TRUE"
        ),
        {
            "id": identifiant,
            "imp": str(regle["impot"]),
            "cat": categorie,
            "lib": identifiant,
        },
    )

    profils = regle["profils_applicables"]
    if isinstance(profils, str):
        profils_json = [profils]
    elif isinstance(profils, list):
        profils_json = profils
    else:
        profils_json = [str(profils)]

    comptes = regle["comptes_declencheurs"]
    if not isinstance(comptes, list):
        comptes = [str(comptes)]

    questions = regle.get("questions_generees") or []
    a_confirmer = regle.get("a_confirmer") or []
    date_effet = _parser_date(regle["date_effet"])
    millesime = date_effet.year

    formule = regle.get("formule_plafonnement")
    formule_brut = str(formule).strip().lower() if formule is not None else ""
    formule_txt = None if formule is None or formule_brut == "sans objet" else str(formule)
    conditions_fond = regle.get("conditions_fond")
    fond_txt = None if conditions_fond is None else str(conditions_fond)

    rv_id = session.execute(
        text(
            "INSERT INTO regle_version ("
            "regle_id, version_referentiel_id, reference_article, reference_source, "
            "millesime, date_effet, date_fin, profils_applicables, comptes_declencheurs, "
            "nature, condition_declenchement, conditions_fond, formule_plafonnement, "
            "questions, expression_resultat, niveau_risque, a_confirmer"
            ") VALUES ("
            ":regle_id, :vr, :ref_art, :ref_src, :mill, :deffet, NULL, "
            "CAST(:profils AS jsonb), :comptes, :nature, :cond, :fond, :formule, "
            "CAST(:questions AS jsonb), :resultat, :risque, CAST(:ac AS jsonb)"
            ") RETURNING id"
        ),
        {
            "regle_id": identifiant,
            "vr": version_id,
            "ref_art": str(regle["reference_legale"]),
            "ref_src": str(regle.get("reference_source") or regle["reference_legale"]),
            "mill": millesime,
            "deffet": date_effet,
            "profils": json.dumps(profils_json, ensure_ascii=False),
            "comptes": [str(c) for c in comptes],
            "nature": str(regle["nature"]),
            "cond": str(regle["condition_declenchement"]),
            "fond": fond_txt,
            "formule": formule_txt,
            "questions": json.dumps(questions, ensure_ascii=False),
            "resultat": str(regle["resultat"]),
            "risque": str(regle["niveau_risque"]),
            "ac": json.dumps(a_confirmer, ensure_ascii=False),
        },
    ).scalar_one()

    # Effets croises optionnels
    for effet in regle.get("effets_croises") or []:
        if not isinstance(effet, dict):
            continue
        session.execute(
            text(
                "INSERT INTO effet_croise (source_id, cible_regle, type, commentaire) "
                "VALUES (:s, :c, :t, :com) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "s": rv_id,
                "c": str(effet["cible"]),
                "t": str(effet["type"]),
                "com": effet.get("commentaire"),
            },
        )

    session.flush()
    return int(rv_id)
