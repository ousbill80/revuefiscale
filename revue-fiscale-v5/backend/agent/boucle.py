"""Boucle agent — regle-based, deterministe pour CI. Pas d appel LLM par defaut."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.agent.ancrage import verifier_ancrage
from backend.agent.metrage import enregistre_appel
from backend.agent.outils import lire_article, rechercher_corpus
from backend.config import config

MESSAGE_ABSTENTION = (
    "Je ne peux pas répondre sans source dans le corpus"
)

# Reference explicite demandee (DEMO-18-G, 18 G, 39, 999-X, …)
_RE_REF_DEMANDEE = re.compile(
    r"(?:art(?:icle)?\.?\s+)([A-Z]{2,}(?:-[\w]+)+|\d+[\s\-]?[A-Z]?)",
    re.IGNORECASE,
)

SCORE_MIN = 2.0


@dataclass
class ReponseAgent:
    statut: str  # repondu | abstention | rejete
    texte: str
    references: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    fragments: list[dict[str, object]] = field(default_factory=list)
    invention: bool = False


def _abstention(tenant_id: int | None, session: Session, q: str) -> ReponseAgent:
    if tenant_id:
        enregistre_appel(
            session,
            tenant_id=tenant_id,
            modele="regle-based",
            tokens_in=len(q.split()),
            tokens_out=0,
            usage="agent_question_abstention",
        )
    return ReponseAgent(
        statut="abstention",
        texte=MESSAGE_ABSTENTION,
        invention=False,
    )


def _reference_demandee(question: str) -> str | None:
    m = _RE_REF_DEMANDEE.search(question or "")
    if not m:
        return None
    return m.group(1).strip().upper().replace(" ", "-")


def repondre(
    session: Session,
    question: str,
    tenant_id: int | None = None,
    types_corpus: list[str] | None = None,
) -> ReponseAgent:
    """1. Cherche le corpus 2. Cite + ancre 3. Sinon s abstient. Jamais d invention.

    ``types_corpus`` : filtre optionnel (ex. ``["demo"]`` pour le harnais d'eval
    lorsque l'annexe / CGI réel est aussi indexé).
    """
    q = (question or "").strip()
    if not q:
        return ReponseAgent(
            statut="abstention",
            texte=MESSAGE_ABSTENTION,
            invention=False,
        )

    # Refus explicite des demandes d invention
    q_low = q.casefold()
    if any(m in q_low for m in ("invente", "inventer", "fabrique un article", "crée un article")):
        return _abstention(tenant_id, session, q)

    # Chemin LLM optionnel — desactive en tests (pas de cle)
    if config.modele_cle_api:
        # Reserve : branche future. Par defaut CI reste deterministe.
        pass

    hits = rechercher_corpus(session, q, limite=5, types=types_corpus)
    # Filtrer les hits trop faibles (chevauchement fortuit sur un mot commun).
    # Seuil applique au score LEXICAL pur (avant boost cgi/millesime) : le boost
    # reordonne, il ne cree pas de pertinence — sinon un fragment hors sujet
    # passerait le seuil et l agent citerait une reference non couverte.
    hits = [
        h
        for h in hits
        if float(str(h.get("score_lexical", h.get("score")) or 0)) >= SCORE_MIN
    ]

    ref_demandee = _reference_demandee(q)
    if ref_demandee:
        article = lire_article(session, ref_demandee, types=types_corpus)
        # Uniquement si la question cite explicitement DEMO-…
        if article is None and "DEMO" in q.upper() and not ref_demandee.startswith("DEMO"):
            article = lire_article(session, f"DEMO-{ref_demandee}", types=types_corpus)
        if article is None:
            # Reference explicite absente du corpus → abstention (anti-invention)
            return _abstention(tenant_id, session, q)
        # Ne garder que les hits de cette reference
        hits = [
            h
            for h in hits
            if str(h.get("reference", "")).upper()
            in {ref_demandee, str(article["reference"]).upper()}
        ]
        if not hits:
            # Forcer un hit depuis l article lu
            hits = [
                {
                    "fragment_id": 0,
                    "article_id": article["id"],
                    "reference": article["reference"],
                    "extrait": str(article["texte"])[:280],
                    "score": 100.0,
                    "score_lexical": 100.0,
                }
            ]

    if not hits:
        return _abstention(tenant_id, session, q)

    # Enrichir avec texte integral pour citation exacte
    refs_vues: list[str] = []
    citations: list[str] = []
    textes_fragments: list[str] = []
    parties: list[str] = []

    for hit in hits:
        ref = str(hit["reference"])
        if ref in refs_vues:
            continue
        article = lire_article(session, ref, types=types_corpus)
        if article is None:
            # Validation post-recuperation : reference introuvable dans le
            # corpus → on ne la cite JAMAIS (anti-invention).
            continue
        refs_vues.append(ref)
        texte_src = str(article["texte"])
        textes_fragments.append(texte_src)
        # Citation = premiere phrase / alinea utile (sous-chaine reelle)
        citation = _extraire_citation(texte_src)
        if citation:
            citations.append(citation)
        mention_demo = " [DÉMO FICTIF]" if "DÉMO" in texte_src or "FICTIF" in texte_src else ""
        parties.append(
            f"Selon {ref}{mention_demo} : « {citation} »"
            if citation
            else f"Selon {ref}{mention_demo}."
        )

    if not refs_vues:
        # Validation post-reponse : aucune reference verifiable dans le corpus
        # recupere → abstention explicite plutot que citation inventee.
        return _abstention(tenant_id, session, q)

    ancrage = verifier_ancrage(citations, textes_fragments)
    if not ancrage.ok or ancrage.citations_rejetees:
        # Rejet plutot qu invention : on s abstient
        return ReponseAgent(
            statut="abstention",
            texte=MESSAGE_ABSTENTION,
            references=[],
            citations=[],
            fragments=hits,
            invention=False,
        )

    texte = (
        "Réponse fondée exclusivement sur le corpus indexé.\n"
        + "\n".join(parties)
        + "\n\n(Sources démo/fictives le cas échéant — non opposables.)"
    )

    if tenant_id:
        enregistre_appel(
            session,
            tenant_id=tenant_id,
            modele="regle-based",
            tokens_in=len(q.split()),
            tokens_out=len(texte.split()),
            usage="agent_question",
        )

    return ReponseAgent(
        statut="repondu",
        texte=texte,
        references=refs_vues,
        citations=ancrage.citations_valides,
        fragments=hits,
        invention=False,
    )


def _extraire_citation(texte: str, max_len: int = 220) -> str:
    """Extrait une sous-chaine continue du fragment pour citation ancree."""
    brut = (texte or "").strip()
    if not brut:
        return ""
    # Sauter l en-tete (premiere ligne Article …) pour citer le corps
    lignes = brut.split("\n")
    corps = "\n".join(lignes[1:]).strip() if len(lignes) > 1 else brut
    t = " ".join(corps.split()) if corps else " ".join(brut.split())
    if len(t) <= max_len:
        return t
    coupe = t[:max_len]
    esp = coupe.rfind(" ")
    return coupe[:esp] if esp > 40 else coupe
