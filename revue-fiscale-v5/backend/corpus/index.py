"""Index lexical en memoire — token -> list[(fragment_id, article_id, score_hint)]."""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

_RE_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ0-9]{2,}", re.UNICODE)

# Mots outils FR — exclus du score lexical (evite les faux positifs massifs)
STOPWORDS = frozenset(
    {
        "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux", "et", "ou",
        "en", "dans", "sur", "pour", "par", "avec", "sans", "sous", "chez",
        "ce", "cet", "cette", "ces", "son", "sa", "ses", "leur", "leurs",
        "qui", "que", "quoi", "dont", "est", "sont", "etre", "avoir",
        "fait", "faire", "dit", "dire", "peut", "doit", "selon", "entre",
        "plus", "moins", "tres", "tout", "tous", "toute", "toutes",
        "ne", "pas", "non", "oui", "si", "comme", "ainsi", "alors",
        "quel", "quelle", "quels", "quelles", "comment",
        "il", "elle", "ils", "elles", "on", "nous", "vous",
        "je", "tu", "me", "te", "se", "lui",
        "the", "of", "and", "to", "in", "is", "for",
        "article", "art", "texte", "present", "presents",
    }
)


def tokeniser(texte: str) -> list[str]:
    """Tokens minuscules, accents conserves, stopwords exclus."""
    return [
        t.lower()
        for t in _RE_TOKEN.findall(texte or "")
        if t.lower() not in STOPWORDS and len(t) >= 2
    ]


def construire_index(
    session: Session,
    types: list[str] | None = None,
) -> dict[str, list[tuple[int, int, float]]]:
    """Construit un index lexical depuis fragment_corpus + article_corpus.

    ``types`` : si fourni, restreint aux ``source_document.type`` listés
    (ex. ``["demo"]`` pour le harnais d'évaluation).
    """
    sql = (
        "SELECT f.id AS fragment_id, f.article_id, f.contenu, a.reference, a.titre "
        "FROM fragment_corpus f "
        "JOIN article_corpus a ON a.id = f.article_id "
        "JOIN source_document s ON s.id = a.source_document_id"
    )
    params: dict[str, object] = {}
    if types:
        sql += " WHERE s.type = ANY(:types)"
        params["types"] = list(types)
    rows = session.execute(text(sql), params).mappings().all()

    index: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    for row in rows:
        fid = int(row["fragment_id"])
        aid = int(row["article_id"])
        tokens_ref = tokeniser(str(row["reference"] or ""))
        tokens_titre = tokeniser(str(row["titre"] or ""))
        tokens_corps = tokeniser(str(row["contenu"] or ""))

        scores: dict[str, float] = {}
        for t in tokens_corps:
            scores[t] = max(scores.get(t, 0.0), 1.0)
        for t in tokens_titre:
            scores[t] = max(scores.get(t, 0.0), 2.0)
        for t in tokens_ref:
            scores[t] = max(scores.get(t, 0.0), 5.0)

        for tok, hint in scores.items():
            index[tok].append((fid, aid, hint))

    return dict(index)
