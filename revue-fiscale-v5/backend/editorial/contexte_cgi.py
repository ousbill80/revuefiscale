"""Contexte CGI pour une entrée ``a_confirmer`` / proposition.

Outillage éditorial — recherche corpus déterministe (pas de LLM, pas de visa).
N'invente aucun taux. Ne purge aucun YAML.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.corpus.recherche import recherche_hybride
from backend.editorial.croisement_cgi import (
    extraire_references_article,
    index_classes_croisement,
)
from backend.editorial.inventaire_a_confirmer import construire_inventaire

MILLESIME_CGI_DEFAUT = 2026
MESSAGE_AUCUN_FRAGMENT = "pas de fragment CGI trouvé — reste bloqué"


def _trouver_mention(entree_id: str) -> dict[str, Any] | None:
    eid = (entree_id or "").strip()
    if "#" not in eid:
        return None
    rule_id, _, idx_s = eid.rpartition("#")
    try:
        idx = int(idx_s)
    except ValueError:
        return None
    inventaire = construire_inventaire()
    for m in inventaire.get("mentions") or []:
        if m.get("identifiant") == rule_id and m.get("index") == idx:
            return m
    return None


def requete_depuis_references(refs: list[str]) -> str:
    """Construit une requête lexicale à partir de références article."""
    parties: list[str] = []
    for r in refs:
        r = (r or "").strip()
        if not r:
            continue
        if r.upper().startswith("ART"):
            parties.append(r)
        else:
            parties.append(f"art. {r}")
    return " ".join(parties[:3]).strip()


def references_pour_entree(
    entree_id: str | None = None,
    *,
    rule_id: str | None = None,
    reference_legale: str | None = None,
    article_corpus: str | None = None,
) -> tuple[str | None, list[str], dict[str, Any] | None]:
    """Résout (entree_id, refs, mention) sans appeler le corpus."""
    mention: dict[str, Any] | None = None
    eid = (entree_id or "").strip() or None
    rid = rule_id
    ref_leg = reference_legale
    if eid:
        mention = _trouver_mention(eid)
        if mention:
            rid = rid or str(mention.get("identifiant") or "")
            ref_leg = ref_leg or (
                str(mention["reference_legale"])
                if mention.get("reference_legale") is not None
                else None
            )
    refs: list[str] = []
    if article_corpus:
        refs.append(str(article_corpus).strip())
    if rid:
        refs.extend(extraire_references_article(rid, ref_leg))
    # Dédupliquer en préservant l'ordre
    vues: set[str] = set()
    uniques: list[str] = []
    for r in refs:
        cle = r.strip().lower()
        if cle and cle not in vues:
            vues.add(cle)
            uniques.append(r.strip())
    return eid, uniques, mention


def construire_contexte_cgi(
    session: Session,
    *,
    entree_id: str | None = None,
    rule_id: str | None = None,
    reference_legale: str | None = None,
    article_corpus: str | None = None,
    requete: str | None = None,
    millesime: int = MILLESIME_CGI_DEFAUT,
    limite: int = 3,
) -> dict[str, Any]:
    """1–3 extraits CGI (type=cgi, millésime) pour accélérer la revue humaine.

    Si aucune hit : message ``pas de fragment CGI trouvé — reste bloqué``.
    """
    eid, refs, mention = references_pour_entree(
        entree_id,
        rule_id=rule_id,
        reference_legale=reference_legale,
        article_corpus=article_corpus,
    )
    q = (requete or "").strip() or requete_depuis_references(refs)
    if not q and mention:
        # Repli : texte de la mention (dates / marqueurs) — toujours filtré cgi
        q = str(mention.get("texte") or "").strip()[:120]

    hits: list[dict[str, object]] = []
    if q:
        hits = recherche_hybride(
            session,
            q,
            limite=max(limite, 5),
            types=["cgi"],
            millesime=millesime,
            millesime_prioritaire=millesime,
        )

    # Préférer les hits dont la référence matche une ref candidate
    refs_norm = {r.lower().replace(" ", "") for r in refs}
    ranges: list[dict[str, object]] = []
    for h in hits:
        ref_h = str(h.get("reference") or "")
        ref_n = ref_h.lower().replace(" ", "")
        priorite = 0
        for cand in refs_norm:
            if cand and (cand == ref_n or ref_n.startswith(cand) or cand.startswith(ref_n)):
                priorite = 1
                break
        ranges.append({**h, "_prio": priorite})
    ranges.sort(key=lambda x: (-int(x.get("_prio") or 0), -float(x.get("score") or 0)))
    fragments = []
    for h in ranges[:limite]:
        fragments.append(
            {
                "fragment_id": h.get("fragment_id"),
                "article_id": h.get("article_id"),
                "reference": h.get("reference"),
                "extrait": h.get("extrait"),
                "score": h.get("score"),
                "type": h.get("type"),
                "millesime": h.get("millesime"),
            }
        )

    aucun = len(fragments) == 0
    # Catalogue croisement (lecture seule) — faux amis si présents, sans inventer.
    meta_croisement: dict[str, Any] | None = None
    faux_amis: list[str] = []
    classe_croisement: str | None = None
    if eid:
        meta_croisement = index_classes_croisement().get(eid)
        if meta_croisement:
            classe_croisement = (
                str(meta_croisement.get("classe_croisement") or "") or None
            )
            raw_faux = meta_croisement.get("faux_amis_potentiels") or meta_croisement.get(
                "faux_amis"
            )
            if isinstance(raw_faux, list):
                faux_amis = [str(x) for x in raw_faux if x is not None and str(x).strip()]

    return {
        "entree_id": eid,
        "rule_id": (
            str(mention["identifiant"])
            if mention and mention.get("identifiant")
            else rule_id
        ),
        "reference_legale": (
            mention.get("reference_legale") if mention else reference_legale
        ),
        "references_candidates": refs,
        "requete": q or None,
        "type": "cgi",
        "millesime": millesime,
        "fragments": fragments,
        "n_fragments": len(fragments),
        "bloque": aucun,
        "message": MESSAGE_AUCUN_FRAGMENT if aucun else None,
        "classe_croisement": classe_croisement,
        "faux_amis_potentiels": faux_amis,
        "avertissement": (
            "Extraits corpus CGI — aide à la revue. "
            "Pas une validation fiscale. Aucune purge a_confirmer."
        ),
    }
