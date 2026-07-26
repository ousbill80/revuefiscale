"""Recherche hybride lexicale sur le corpus editorial."""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.corpus.index import construire_index, tokeniser

_RE_REF = re.compile(
    r"(?:art(?:icle)?\.?\s*)?([A-Z]{2,}(?:-[\w]+)+|\d+[\s\-]?[A-Z]?)",
    re.IGNORECASE,
)

# Boost déterministe : CGI du millésime courant avant annexe / démo / autres.
# Ne crée aucun montant — réordonne uniquement des fragments déjà en base.
BOOST_TYPE_CGI = 8.0
BOOST_MILLESIME_CIBLE = 4.0
MILLESIME_PRIORITAIRE_DEFAUT = 2026


def _extraire_reference_candidate(requete: str) -> str | None:
    """Detecte une reference d article eventuelle dans la requete."""
    m = _RE_REF.search(requete or "")
    if not m:
        return None
    return m.group(1).strip().upper().replace(" ", "-")


def _references_compatibles(cand: str, ref: str) -> bool:
    """Correspondance stricte — évite que « 18 » booste via sous-chaîne de DEMO-18-G."""
    c = (cand or "").upper()
    r = (ref or "").upper()
    if not c or not r:
        return False
    if c == r:
        return True
    if r.startswith(c + "-") or c.startswith(r + "-"):
        return True
    return bool(c == f"DEMO-{r}" or r == f"DEMO-{c}")


def _charger_fragments(
    session: Session,
    types: list[str] | None = None,
    millesime: int | None = None,
) -> dict[int, dict[str, object]]:
    sql = (
        "SELECT f.id AS fragment_id, f.article_id, f.contenu, a.reference, "
        "s.type AS doc_type, s.millesime AS doc_millesime "
        "FROM fragment_corpus f "
        "JOIN article_corpus a ON a.id = f.article_id "
        "JOIN source_document s ON s.id = a.source_document_id"
    )
    params: dict[str, object] = {}
    clauses: list[str] = []
    if types:
        clauses.append("s.type = ANY(:types)")
        params["types"] = list(types)
    if millesime is not None:
        clauses.append("s.millesime = :millesime")
        params["millesime"] = int(millesime)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = session.execute(text(sql), params).mappings().all()
    return {int(r["fragment_id"]): dict(r) for r in rows}


def _boost_priorite(
    row: dict[str, object],
    *,
    millesime_prioritaire: int | None,
) -> float:
    """Bonus score pour type=cgi et millésime cible (si demandé)."""
    if millesime_prioritaire is None:
        return 0.0
    bonus = 0.0
    doc_type = str(row.get("doc_type") or "").lower()
    if doc_type == "cgi":
        bonus += BOOST_TYPE_CGI
    mill = row.get("doc_millesime")
    if mill is not None and int(mill) == int(millesime_prioritaire):
        bonus += BOOST_MILLESIME_CIBLE
    return bonus


def recherche_hybride(
    session: Session,
    requete: str,
    limite: int = 10,
    types: list[str] | None = None,
    millesime: int | None = None,
    millesime_prioritaire: int | None = MILLESIME_PRIORITAIRE_DEFAUT,
) -> list[dict[str, object]]:
    """Classement par chevauchement lexical + filtre optionnel par reference.

    ``types`` restreint aux ``source_document.type`` (ex. ``["demo"]`` pour l'eval).

    ``millesime`` : filtre strict sur ``source_document.millesime`` (ex. 2026 CGI).

    ``millesime_prioritaire`` : boost CGI + millésime (défaut 2026). Passer
    ``None`` pour désactiver (tests / comparaison à égalité).

    Retourne [{fragment_id, article_id, reference, extrait, score,
    score_lexical, type, millesime}, ...] — ``score_lexical`` est le score de
    pertinence AVANT boost de priorite (seul valable pour un seuil minimal).
    """
    if not (requete or "").strip():
        return []

    index = construire_index(session, types=types)
    tokens = tokeniser(requete)
    meta = _charger_fragments(session, types=types, millesime=millesime)
    # Index lexical peut contenir d'autres types : ne scorer que les fragments chargés
    scores: dict[int, float] = defaultdict(float)

    for tok in tokens:
        for fid, _aid, hint in index.get(tok, []):
            if fid not in meta:
                continue
            scores[fid] += hint

    ref_cand = _extraire_reference_candidate(requete)
    if ref_cand:
        for fid, row in meta.items():
            ref = str(row["reference"] or "").upper()
            if _references_compatibles(ref_cand, ref):
                scores[fid] += 20.0

    # Score lexical pur (chevauchement + reference) AVANT boost de priorite.
    # Le boost reordonne seulement — il ne doit jamais faire passer un fragment
    # non pertinent au-dessus d'un seuil de pertinence (anti-invention).
    scores_lexicaux = dict(scores)

    for fid in list(scores.keys()):
        row = meta.get(fid)
        if row is not None:
            scores[fid] += _boost_priorite(
                row, millesime_prioritaire=millesime_prioritaire
            )

    if not scores:
        return []

    classes = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    resultat: list[dict[str, object]] = []
    for fid, score in classes[:limite]:
        if fid not in meta:
            continue
        row = meta[fid]
        contenu = str(row.get("contenu") or "")
        extrait = contenu[:280] + ("…" if len(contenu) > 280 else "")
        mill = row.get("doc_millesime")
        resultat.append(
            {
                "fragment_id": fid,
                "article_id": int(str(row["article_id"])),
                "reference": str(row["reference"]),
                "extrait": extrait,
                "score": float(score),
                "score_lexical": float(scores_lexicaux.get(fid, 0.0)),
                "type": str(row.get("doc_type") or ""),
                "millesime": int(mill) if mill is not None else None,
            }
        )
    return resultat
