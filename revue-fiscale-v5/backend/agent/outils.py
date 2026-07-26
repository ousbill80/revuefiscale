"""Outils de l agent — corpus, lecture, simulation moteur, propositions."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.corpus.recherche import recherche_hybride
from backend.moteur.calcul import ConclusionCalculee, calculer_regle
from backend.plateforme.contexte import contexte_tenant
from backend.referentiel.depot import lire_regles_version
from backend.referentiel.expressions import Contexte
from backend.socle.agregats import calculer_agregats, solde_naturel


class ErreurOutil(Exception):
    """Echec d un outil agent."""


def rechercher_corpus(
    session: Session,
    query: str,
    limite: int = 10,
    types: list[str] | None = None,
    millesime_prioritaire: int | None = 2026,
) -> list[dict[str, object]]:
    """Delegue a corpus.recherche — ne resume pas, ne calcule aucun montant.

    Priorise type=cgi millésime 2026 par défaut (réordonnancement lexical).
    """
    return recherche_hybride(
        session,
        query,
        limite=limite,
        types=types,
        millesime_prioritaire=millesime_prioritaire,
    )


def lire_article(
    session: Session,
    reference: str,
    types: list[str] | None = None,
    millesime_prioritaire: int | None = 2026,
) -> dict[str, object] | None:
    """Retourne le texte integral d un article du corpus, ou None.

    Si plusieurs sources portent la même référence, préfère ``type=cgi`` puis
    le millésime prioritaire (défaut 2026). Pas d'invention de contenu.
    """
    sql = (
        "SELECT a.id, a.reference, a.titre, a.texte, a.date_effet, a.date_fin, "
        "s.type AS doc_type, s.millesime AS doc_millesime "
        "FROM article_corpus a "
        "JOIN source_document s ON s.id = a.source_document_id "
        "WHERE upper(a.reference) = upper(:ref)"
    )
    params: dict[str, object] = {"ref": reference}
    if types:
        sql += " AND s.type = ANY(:types)"
        params["types"] = list(types)
    # Priorité : cgi > autres ; millésime cible > autres ; id croissant
    sql += (
        " ORDER BY "
        "CASE WHEN lower(s.type) = 'cgi' THEN 0 ELSE 1 END, "
        "CASE WHEN s.millesime = :mill THEN 0 ELSE 1 END, "
        "a.id"
    )
    params["mill"] = millesime_prioritaire if millesime_prioritaire is not None else -1
    sql += " LIMIT 1"
    row = session.execute(text(sql), params).mappings().one_or_none()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "reference": str(row["reference"]),
        "titre": row["titre"],
        "texte": str(row["texte"]),
        "date_effet": row["date_effet"],
        "date_fin": row["date_fin"],
        "type": str(row["doc_type"] or ""),
        "millesime": int(row["doc_millesime"]) if row["doc_millesime"] is not None else None,
    }


def simuler_regle(
    session: Session,
    tenant_id: int,
    mission_id: int,
    regle_id: str,
    reponses: dict[str, Any] | None = None,
) -> ConclusionCalculee:
    """Appelle exclusivement le moteur deterministe — jamais de calcul LLM."""
    reponses = reponses or {}
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, version_referentiel_id FROM mission WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurOutil(f"mission {mission_id} introuvable")
        version_id = mission["version_referentiel_id"]
        if version_id is None:
            raise ErreurOutil(f"mission {mission_id} sans epinglage")

        soldes_rows = session.execute(
            text(
                "SELECT compte, debit, credit FROM solde_compte WHERE mission_id = :m"
            ),
            {"m": mission_id},
        ).mappings().all()
        if not soldes_rows:
            raise ErreurOutil(f"aucun solde pour la mission {mission_id}")

        soldes = {
            str(r["compte"]): solde_naturel(
                str(r["compte"]), Decimal(r["debit"]), Decimal(r["credit"])
            )
            for r in soldes_rows
        }
        agregats = calculer_agregats(soldes)
        ctx = Contexte(soldes=soldes, agregats=agregats, reponses=reponses)

        regles = lire_regles_version(session, int(version_id))
        cible = next((r for r in regles if r.regle_id == regle_id), None)
        if cible is None:
            raise ErreurOutil(f"regle {regle_id} absente de la version epinglee")

        return calculer_regle(cible, ctx)


def proposer_regle(session: Session, proposition: dict[str, Any]) -> int:
    """Depose une proposition dans la file editoriale — n ecrit pas le referentiel."""
    charge = proposition.get("charge_utile", proposition)
    sources = proposition.get("sources", [])
    source = proposition.get("source", "copilote")
    pid = session.execute(
        text(
            "INSERT INTO proposition_editoriale (source, charge_utile, sources) "
            "VALUES (:src, CAST(:cu AS jsonb), CAST(:sources AS jsonb)) "
            "RETURNING id"
        ),
        {
            "src": source,
            "cu": json.dumps(charge, ensure_ascii=False, default=str),
            "sources": json.dumps(sources, ensure_ascii=False, default=str),
        },
    ).scalar_one()
    session.flush()
    return int(pid)
