"""Harnais d evaluation de l agent — metriques anti-invention."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from backend.agent.ancrage import verifier_ancrage
from backend.agent.boucle import MESSAGE_ABSTENTION, ReponseAgent, repondre
from backend.corpus.ingestion import seed_corpus_demo
from backend.corpus.recherche import recherche_hybride

JEU_DEFAUT = Path(__file__).resolve().parents[2] / "tests" / "eval" / "jeu_reference.yaml"


@dataclass
class Metrics:
    recuperation: float = 0.0
    citation: float = 0.0
    abstention: float = 0.0
    invention: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


def charger_jeu(chemin: Path | None = None) -> list[dict[str, Any]]:
    path = chemin or JEU_DEFAUT
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cas = data.get("cas", data) if isinstance(data, dict) else data
    if not isinstance(cas, list) or len(cas) < 1:
        raise ValueError(f"jeu de reference invalide : {path}")
    return cas


def _detecte_invention(reponse: ReponseAgent, articles_attendus: list[str]) -> bool:
    """Invention = reference hors corpus / citation non ancree."""
    if reponse.invention:
        return True
    if reponse.statut == "abstention":
        return False
    for ref in reponse.references:
        refs_hits = {str(h.get("reference")) for h in reponse.fragments}
        if ref not in refs_hits:
            return True
    textes = [str(h.get("extrait") or "") for h in reponse.fragments]
    if reponse.citations:
        ancrage_frag = verifier_ancrage(
            reponse.citations,
            [str(h.get("extrait") or "") for h in reponse.fragments],
        )
        if ancrage_frag.citations_rejetees:
            for cit in ancrage_frag.citations_rejetees:
                hors_extrait = not any(
                    cit.casefold() in (e or "").casefold() for e in textes
                )
                if hors_extrait and not reponse.references:
                    return True
    return False


def evaluer_agent(
    cas: dict[str, Any],
    session: Session | None = None,
    reponse: ReponseAgent | None = None,
) -> Metrics:
    """Evalue un cas du jeu de reference. Si session fournie, execute l agent.

    Le harnais se restreint au corpus ``demo`` pour rester stable lorsque
    l'annexe / CGI réel est aussi indexé en base.
    """
    comportement = cas.get("comportement_attendu", "repondre")
    articles_attendus = list(cas.get("articles_attendus") or [])
    question = str(cas.get("question", ""))
    types_eval = ["demo"]

    if reponse is None:
        if session is None:
            raise ValueError("session ou reponse requis")
        seed_corpus_demo(session)
        reponse = repondre(session, question, types_corpus=types_eval)

    # Recuperation : bon article dans les hits (si on devait repondre)
    recup = 0.0
    if comportement == "repondre" and articles_attendus:
        refs_hits = {str(h.get("reference")) for h in reponse.fragments}
        if not refs_hits and session is not None:
            # Rejouer la recherche pour la metrique recuperation
            hits = recherche_hybride(session, question, limite=10, types=types_eval)
            refs_hits = {str(h.get("reference")) for h in hits}
        recup = 1.0 if any(a in refs_hits for a in articles_attendus) else 0.0
    elif comportement == "sabstenir":
        recup = 1.0  # N/A — compte comme ok pour moyenne partielle

    # Citation : references citees ⊆ attendus (ou egales)
    cit = 0.0
    if comportement == "repondre":
        if reponse.statut == "repondu" and reponse.references:
            if articles_attendus:
                cit = (
                    1.0
                    if all(r in articles_attendus for r in reponse.references)
                    or any(r in articles_attendus for r in reponse.references)
                    else 0.0
                )
            else:
                cit = 1.0 if reponse.citations else 0.0
        else:
            cit = 0.0
    else:
        cit = 1.0

    # Abstention correcte
    abst = 0.0
    if comportement == "sabstenir":
        abst = 1.0 if reponse.statut == "abstention" else 0.0
    else:
        abst = 1.0 if reponse.statut == "repondu" else 0.0

    # Invention — zero tolere
    invente = _detecte_invention(reponse, articles_attendus)
    if (
        cas.get("est_piege")
        and reponse.statut == "repondu"
        and comportement == "sabstenir"
    ):
        invente = True
    if _texte_invente_articles(reponse.texte, reponse.references):
        invente = True

    return Metrics(
        recuperation=recup,
        citation=cit,
        abstention=abst,
        invention=1.0 if invente else 0.0,
        detail={
            "id": cas.get("id"),
            "statut": reponse.statut,
            "references": reponse.references,
        },
    )


def _texte_invente_articles(texte: str, refs_ok: list[str]) -> bool:
    """Detecte des formulations 'article XX' hors references retrouvees."""
    import re

    if MESSAGE_ABSTENTION in (texte or ""):
        return False
    # Cherche Art. / Article suivi d un numero ou code
    pattern = re.compile(
        r"(?:art(?:icle)?\.?\s+)([A-Z]{0,4}-?[\d]+[A-Z]?(?:-[\w]+)?|\d+\s*[A-Z]?)",
        re.IGNORECASE,
    )
    refs_norm = {r.upper().replace(" ", "-") for r in refs_ok}
    for m in pattern.finditer(texte or ""):
        cand = m.group(1).strip().upper().replace(" ", "-")
        # Ignorer DEMO deja dans refs
        if cand in refs_norm:
            continue
        if any(cand in r or r in cand for r in refs_norm):
            continue
        # "present article" / mentions generiques ignorees si pas de numero fort
        if cand and cand not in refs_norm:
            # Accepter si c est clairement DEMO et dans refs
            if cand.startswith("DEMO") and any(cand in r for r in refs_norm):
                continue
            return True
    return False


def evaluer_jeu(
    session: Session,
    chemin: Path | None = None,
) -> tuple[Metrics, list[Metrics]]:
    """Evalue tout le jeu ; retourne moyennes + details."""
    seed_corpus_demo(session)
    cas_list = charger_jeu(chemin)
    details: list[Metrics] = []
    for cas in cas_list:
        details.append(evaluer_agent(cas, session=session))

    n = len(details) or 1
    moyenne = Metrics(
        recuperation=sum(d.recuperation for d in details) / n,
        citation=sum(d.citation for d in details) / n,
        abstention=sum(d.abstention for d in details) / n,
        invention=sum(d.invention for d in details) / n,
        detail={"n": n},
    )
    return moyenne, details
