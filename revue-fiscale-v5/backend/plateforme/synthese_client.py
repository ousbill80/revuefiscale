"""Synthèse IA client — Data Room phase 2, document consultatif versionné.

La synthèse rassemble le dossier du contribuable (identité, mémoire,
risques, pièces, missions), le soumet au LLM et stocke un JSON structuré
sourcé. Elle n'est JAMAIS appliquée automatiquement — l'humain valide.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

logger = logging.getLogger(__name__)

GRAVITES: Final[frozenset[str]] = frozenset({"faible", "moyenne", "haute"})
GRAVITE_DEFAUT: Final[str] = "moyenne"
RESUME_MAX: Final[int] = 6000
TEXTE_MAX: Final[int] = 2000
ELEMENTS_MAX: Final[int] = 30

_PROMPT_SYNTHESE = """Tu es un assistant d'analyse pour un cabinet de revue
fiscale en Côte d'Ivoire. On te fournit le dossier d'un contribuable :
identité, mémoire client, risques (avec score agrégé), pièces déposées et
missions. Chaque élément porte un identifiant de source stable
(ex. "memoire:12", "risque:40", "piece:123", "mission:7", "score_risque").

Règles strictes :
- Ne calcule aucun montant fiscal, taxe, pénalité ou plafonnement.
- N'invente rien : chaque affirmation s'appuie sur les éléments fournis.
- "sources" : uniquement des identifiants présents dans le dossier.
- "gravite" parmi : faible | moyenne | haute.
- Français professionnel, concis. Pas de nom de fournisseur technique.
- "incoherences" : contradictions ou manques factuels entre éléments
  (identité ↔ pièces, risques sans suivi, mémoire ↔ missions…).
- "recommandations" : actions concrètes pour le cabinet, jamais de
  conclusion fiscale chiffrée.

Réponds UNIQUEMENT en JSON valide :
{
  "resume": "…",
  "points_cles": [{"texte": "…", "sources": ["memoire:12"]}],
  "incoherences": [
    {"description": "…", "sources": ["piece:123"], "gravite": "moyenne"}
  ],
  "recommandations": [{"texte": "…", "sources": ["risque:40"]}]
}
"""


class ErreurSyntheseClient(Exception):
    """Echec génération / lecture de synthèse client."""


def _nettoyer_sources(brut: Any, sources_connues: set[str]) -> list[str]:
    out: list[str] = []
    for s in brut if isinstance(brut, list) else []:
        ref = str(s or "").strip()
        if ref in sources_connues and ref not in out:
            out.append(ref)
    return out


def normaliser_contenu_synthese(
    brut: Any, sources_connues: set[str]
) -> dict[str, Any]:
    """Coercition du JSON LLM vers le schéma strict — pure, testable.

    Toute source citée inconnue est retirée ; gravité invalide → moyenne ;
    éléments sans texte ignorés.
    """
    src = brut if isinstance(brut, dict) else {}
    resume = str(src.get("resume") or "").strip()[:RESUME_MAX]

    points_cles: list[dict[str, Any]] = []
    for item in (
        src.get("points_cles")
        if isinstance(src.get("points_cles"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        texte = str(item.get("texte") or "").strip()[:TEXTE_MAX]
        if not texte:
            continue
        points_cles.append(
            {
                "texte": texte,
                "sources": _nettoyer_sources(
                    item.get("sources"), sources_connues
                ),
            }
        )

    incoherences: list[dict[str, Any]] = []
    for item in (
        src.get("incoherences")
        if isinstance(src.get("incoherences"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()[:TEXTE_MAX]
        if not description:
            continue
        gravite = str(item.get("gravite") or "").strip().lower()
        if gravite not in GRAVITES:
            gravite = GRAVITE_DEFAUT
        incoherences.append(
            {
                "description": description,
                "sources": _nettoyer_sources(
                    item.get("sources"), sources_connues
                ),
                "gravite": gravite,
            }
        )

    recommandations: list[dict[str, Any]] = []
    for item in (
        src.get("recommandations")
        if isinstance(src.get("recommandations"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        texte = str(item.get("texte") or "").strip()[:TEXTE_MAX]
        if not texte:
            continue
        recommandations.append(
            {
                "texte": texte,
                "sources": _nettoyer_sources(
                    item.get("sources"), sources_connues
                ),
            }
        )

    return {
        "resume": resume,
        "points_cles": points_cles[:ELEMENTS_MAX],
        "incoherences": incoherences[:ELEMENTS_MAX],
        "recommandations": recommandations[:ELEMENTS_MAX],
    }


def sources_du_contexte(contexte: dict[str, Any]) -> set[str]:
    """Identifiants de sources citables d'un contexte de synthèse — pure."""
    sources: set[str] = {"score_risque"}
    for cle in ("memoire", "risques", "pieces", "missions"):
        for item in contexte.get(cle) or []:
            ref = str(item.get("source") or "").strip()
            if ref:
                sources.add(ref)
    return sources


def construire_contexte_synthese(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Rassemble de façon déterministe le dossier du contribuable."""
    from backend.plateforme.risques import (
        STATUTS_NON_CLOS,
        lister_risques,
        score_risque_contribuable,
    )

    with contexte_tenant(session, tenant_id):
        identite = session.execute(
            text(
                "SELECT id, denomination, ncc, rccm, forme, dfe, "
                "regime_fiscal, forme_juridique, siege_social, commune, "
                "centre_impots, capital_social, mois_cloture, "
                "activite_principale, date_immatriculation "
                "FROM contribuable WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if identite is None:
            raise ErreurSyntheseClient(
                f"contribuable {contribuable_id} introuvable"
            )
        memoire_rows = session.execute(
            text(
                "SELECT id, type_entree, contenu, source_type, source_ref, "
                "cree_le FROM memoire_client "
                "WHERE contribuable_id = :c AND actif "
                "ORDER BY cree_le DESC, id DESC LIMIT 100"
            ),
            {"c": contribuable_id},
        ).mappings().all()
        pieces_rows = session.execute(
            text(
                "SELECT id, type_piece, nom_fichier, cree_le "
                "FROM piece_contribuable WHERE contribuable_id = :c "
                "ORDER BY cree_le DESC, id DESC LIMIT 100"
            ),
            {"c": contribuable_id},
        ).mappings().all()
        missions_rows = session.execute(
            text(
                "SELECT id, exercice, statut, cree_le FROM mission "
                "WHERE contribuable_id = :c "
                "ORDER BY exercice DESC, id DESC LIMIT 50"
            ),
            {"c": contribuable_id},
        ).mappings().all()

    risques = [
        r
        for r in lister_risques(
            session, tenant_id, contribuable_id=contribuable_id
        )
        if str(r.get("statut") or "ouvert") in STATUTS_NON_CLOS
    ]
    score = score_risque_contribuable(session, tenant_id, contribuable_id)

    def _iso(v: Any) -> Any:
        return v.isoformat() if hasattr(v, "isoformat") else v

    ident = dict(identite)
    contexte: dict[str, Any] = {
        "identite": {
            "denomination": ident.get("denomination"),
            "ncc": ident.get("ncc"),
            "rccm": ident.get("rccm"),
            "forme": ident.get("forme"),
            "dfe": ident.get("dfe"),
            "regime_fiscal": ident.get("regime_fiscal"),
            "forme_juridique": ident.get("forme_juridique"),
            "siege_social": ident.get("siege_social"),
            "commune": ident.get("commune"),
            "centre_impots": ident.get("centre_impots"),
            "capital_social": (
                str(ident["capital_social"])
                if ident.get("capital_social") is not None
                else None
            ),
            "mois_cloture": ident.get("mois_cloture"),
            "activite_principale": ident.get("activite_principale"),
            "date_immatriculation": _iso(ident.get("date_immatriculation")),
        },
        "memoire": [
            {
                "source": f"memoire:{r['id']}",
                "type_entree": r["type_entree"],
                "contenu": str(r["contenu"])[:1000],
                "source_type": r["source_type"],
                "cree_le": _iso(r.get("cree_le")),
            }
            for r in memoire_rows
        ],
        "risques": [
            {
                "source": f"risque:{r['id']}",
                "impot": r.get("impot"),
                "libelle": r.get("libelle"),
                "statut": r.get("statut"),
                "probabilite": r.get("probabilite"),
                "exercice_origine": r.get("exercice_origine"),
                "montant_estime": r.get("montant_estime"),
            }
            for r in risques
        ],
        "score_risque": {
            "source": "score_risque",
            "score": score.get("score"),
            "niveau": score.get("niveau"),
            "libelle_niveau": score.get("libelle_niveau"),
            "facteurs": score.get("facteurs"),
            "alertes": score.get("alertes"),
        },
        "pieces": [
            {
                "source": f"piece:{p['id']}",
                "type_piece": p["type_piece"],
                "nom_fichier": p["nom_fichier"],
                "cree_le": _iso(p.get("cree_le")),
            }
            for p in pieces_rows
        ],
        "missions": [
            {
                "source": f"mission:{m['id']}",
                "exercice": m["exercice"],
                "statut": m["statut"],
                "cree_le": _iso(m.get("cree_le")),
            }
            for m in missions_rows
        ],
    }
    return contexte


def _parser_json_llm(contenu: str) -> dict[str, Any]:
    try:
        brut = json.loads(contenu)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", contenu)
        if not m:
            raise ErreurSyntheseClient("réponse LLM non JSON") from None
        try:
            brut = json.loads(m.group(0))
        except json.JSONDecodeError:
            raise ErreurSyntheseClient("réponse LLM non JSON") from None
    if not isinstance(brut, dict):
        raise ErreurSyntheseClient("réponse LLM non JSON")
    return brut


def _serialiser(row: dict[str, Any], *, avec_contenu: bool) -> dict[str, Any]:
    cree = row.get("cree_le")
    out: dict[str, Any] = {
        "id": int(row["id"]),
        "contribuable_id": int(row["contribuable_id"]),
        "version": int(row["version"]),
        "statut": str(row["statut"]),
        "modele": row.get("modele"),
        "erreur": row.get("erreur"),
        "auteur": row.get("auteur"),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
    }
    if avec_contenu:
        contenu = row.get("contenu")
        out["contenu"] = dict(contenu) if isinstance(contenu, dict) else None
    return out


def _appeler_llm_synthese(contexte: dict[str, Any]) -> tuple[dict[str, Any], str]:
    from backend.abonne.extraction_identite import message_erreur_llm_fr
    from backend.socle import llm_providers

    if not llm_providers.providers_configures():
        raise ErreurSyntheseClient(
            "Synthèse indisponible pour le moment. Réessayez plus tard."
        )
    user = (
        "Dossier contribuable (JSON) :\n"
        + json.dumps(contexte, ensure_ascii=False)
    )
    messages = [
        {"role": "system", "content": _PROMPT_SYNTHESE},
        {"role": "user", "content": user},
    ]
    t0 = time.perf_counter()
    try:
        contenu, provider_id, failover = llm_providers.appeler_chat(
            messages, capacite="chat", temperature=0, json_object=True
        )
    except llm_providers.ErreurLlm as e:
        logger.info(
            "synthese_llm_echec duree_ms=%s",
            int((time.perf_counter() - t0) * 1000),
        )
        raise ErreurSyntheseClient(message_erreur_llm_fr(e)) from e
    logger.info(
        "synthese_llm_ok provider=%s failover_depuis=%s duree_ms=%s",
        provider_id,
        list(failover),
        int((time.perf_counter() - t0) * 1000),
    )
    return _parser_json_llm(contenu), provider_id


def generer_synthese(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    *,
    auteur: str | None = None,
) -> dict[str, Any]:
    """Génère une nouvelle version de synthèse (synchrone, consultative)."""
    contexte = construire_contexte_synthese(
        session, tenant_id, contribuable_id
    )
    with contexte_tenant(session, tenant_id):
        version = session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM synthese_client "
                "WHERE contribuable_id = :c"
            ),
            {"c": contribuable_id},
        ).scalar_one()
        synthese_id = session.execute(
            text(
                "INSERT INTO synthese_client "
                "(tenant_id, contribuable_id, version, statut, auteur) "
                "VALUES (:t, :c, :v, 'en_cours', :aut) RETURNING id"
            ),
            {
                "t": tenant_id,
                "c": contribuable_id,
                "v": int(version),
                "aut": (auteur or "").strip() or None,
            },
        ).scalar_one()
        session.flush()

    try:
        brut, provider_id = _appeler_llm_synthese(contexte)
        contenu = normaliser_contenu_synthese(
            brut, sources_du_contexte(contexte)
        )
    except ErreurSyntheseClient as e:
        with contexte_tenant(session, tenant_id):
            row = session.execute(
                text(
                    "UPDATE synthese_client "
                    "SET statut = 'echec', erreur = :err WHERE id = :id "
                    "RETURNING id, contribuable_id, version, statut, "
                    "contenu, modele, erreur, auteur, cree_le"
                ),
                {"id": int(synthese_id), "err": str(e)[:1000]},
            ).mappings().one()
            session.flush()
        return _serialiser(dict(row), avec_contenu=True)

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE synthese_client "
                "SET statut = 'disponible', "
                "contenu = CAST(:ct AS jsonb), modele = :mod, erreur = NULL "
                "WHERE id = :id "
                "RETURNING id, contribuable_id, version, statut, "
                "contenu, modele, erreur, auteur, cree_le"
            ),
            {
                "id": int(synthese_id),
                "ct": json.dumps(contenu, ensure_ascii=False),
                "mod": provider_id,
            },
        ).mappings().one()
        session.flush()
    return _serialiser(dict(row), avec_contenu=True)


def lister_syntheses(
    session: Session, tenant_id: int, contribuable_id: int
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT id, contribuable_id, version, statut, modele, "
                "erreur, auteur, cree_le FROM synthese_client "
                "WHERE contribuable_id = :c ORDER BY version DESC, id DESC"
            ),
            {"c": contribuable_id},
        ).mappings().all()
        return [_serialiser(dict(r), avec_contenu=False) for r in rows]


def obtenir_synthese(
    session: Session,
    tenant_id: int,
    contribuable_id: int,
    synthese_id: int,
) -> dict[str, Any]:
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, contribuable_id, version, statut, contenu, "
                "modele, erreur, auteur, cree_le FROM synthese_client "
                "WHERE id = :id AND contribuable_id = :c"
            ),
            {"id": synthese_id, "c": contribuable_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurSyntheseClient(
                f"synthèse {synthese_id} introuvable"
            )
        return _serialiser(dict(row), avec_contenu=True)
