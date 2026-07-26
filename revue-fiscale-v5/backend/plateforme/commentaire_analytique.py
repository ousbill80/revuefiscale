"""Commentaire IA de revue analytique — lecture commentée versionnée.

Le réviseur dispose des variations N/N-1 calculées de façon déterministe
(``revue_analytique.py``) ; le commentaire IA propose, pour chaque poste
en variation significative, une hypothèse explicative et la question à
poser au client. Traçabilité stricte : le contexte fourni au LLM ne
contient QUE les variations significatives calculées ; toute explication
dont le poste n'est pas dans ces variations est RETIRÉE. Jamais appliqué
automatiquement — l'humain valide.
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
TEXTE_MAX: Final[int] = 2000
ELEMENTS_MAX: Final[int] = 30
# Anti-rafale : une génération en_cours plus récente que ce délai bloque.
EN_COURS_BLOQUANT_MINUTES: Final[int] = 10

_PROMPT_COMMENTAIRE = """Tu es un expert-comptable réviseur pour un cabinet
de revue fiscale en Côte d'Ivoire (référentiel SYSCOHADA). On te fournit
les variations significatives de la revue analytique N/N-1 d'une mission :
pour chaque poste (compte), le solde N, le solde N-1, la variation en FCFA
et en %, le sens (hausse/baisse) et le classement (apparition,
disparition, variation forte). Rédige le COMMENTAIRE DE REVUE ANALYTIQUE
destiné au réviseur.

Règles strictes :
- N'utilise QUE les données fournies. AUCUNE invention de montant :
  reprends exactement les montants fournis, ne recalcule rien.
- Chaque explication reprend EXACTEMENT un "poste" présent dans les
  variations fournies (le champ "compte").
- "hypothese_explicative" : hypothèse comptable/fiscale plausible
  expliquant la variation (saisonnalité, changement d'activité,
  reclassement, erreur d'imputation, omission…), au conditionnel.
- "question_a_poser_au_client" : question concrète et directe que le
  réviseur posera au client pour instruire la variation.
- "gravite" parmi : faible | moyenne | haute (hiérarchise selon
  l'ampleur de la variation et le risque fiscal potentiel).
- "resume" : lecture d'ensemble des variations en 3 lignes maximum.
- "alertes_coherence" : incohérences entre variations fournies (ex :
  charges en forte hausse sans hausse d'activité) — d'après les seules
  données fournies.
- Français professionnel, concis. Pas de nom de fournisseur technique.

Réponds UNIQUEMENT en JSON valide :
{
  "resume": "…",
  "explications": [
    {"poste": "…", "hypothese_explicative": "…",
     "question_a_poser_au_client": "…", "gravite": "haute"}
  ],
  "alertes_coherence": ["…"]
}
"""


class ErreurCommentaireAnalytique(Exception):
    """Echec génération / lecture du commentaire de revue analytique."""


# ── Coercition pure ────────────────────────────────────────────────


def postes_du_contexte(contexte: dict[str, Any]) -> set[str]:
    """Postes (comptes) citables d'un contexte de commentaire — pure."""
    postes: set[str] = set()
    for item in contexte.get("variations") or []:
        poste = str((item or {}).get("poste") or "").strip()
        if poste:
            postes.add(poste)
    return postes


def _liste_textes(brut: Any) -> list[str]:
    out: list[str] = []
    for item in brut if isinstance(brut, list) else []:
        if isinstance(item, (dict, list)):
            continue
        texte = str(item or "").strip()[:TEXTE_MAX]
        if texte:
            out.append(texte)
    return out[:ELEMENTS_MAX]


def normaliser_contenu_commentaire(
    brut: Any, postes_connus: set[str]
) -> dict[str, Any]:
    """Coercition du JSON LLM vers le schéma strict — pure, testable.

    Toute explication dont le ``poste`` n'est pas dans les variations
    fournies est RETIRÉE ; gravité invalide → moyenne ; explications sans
    hypothèse ignorées ; listes plafonnées à ``ELEMENTS_MAX``.
    """
    src = brut if isinstance(brut, dict) else {}
    resume = str(src.get("resume") or "").strip()[:TEXTE_MAX]

    explications: list[dict[str, Any]] = []
    for item in (
        src.get("explications")
        if isinstance(src.get("explications"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        poste = str(item.get("poste") or "").strip()
        if poste not in postes_connus:
            continue  # traçabilité stricte : poste inconnu → retiré
        hypothese = str(
            item.get("hypothese_explicative") or ""
        ).strip()[:TEXTE_MAX]
        if not hypothese:
            continue
        question = str(
            item.get("question_a_poser_au_client") or ""
        ).strip()[:TEXTE_MAX]
        gravite = str(item.get("gravite") or "").strip().lower()
        if gravite not in GRAVITES:
            gravite = GRAVITE_DEFAUT
        explications.append(
            {
                "poste": poste,
                "hypothese_explicative": hypothese,
                "question_a_poser_au_client": question,
                "gravite": gravite,
            }
        )

    return {
        "resume": resume,
        "explications": explications[:ELEMENTS_MAX],
        "alertes_coherence": _liste_textes(src.get("alertes_coherence")),
    }


# ── Contexte déterministe (variations significatives uniquement) ───


def construire_contexte(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Contexte du commentaire — UNIQUEMENT les variations significatives.

    Source : ``revue_analytique_mission`` (déterministe, lecture seule).
    Lève si la mission est introuvable (404 amont) ou si la revue est
    indisponible / sans variation significative (rien à commenter).
    """
    from backend.plateforme.revue_analytique import (
        CLASSEMENT_STABLE,
        revue_analytique_mission,
    )

    try:
        revue = revue_analytique_mission(session, tenant_id, mission_id)
    except Exception as e:  # ErreurRevueAnalytique → mission introuvable
        raise ErreurCommentaireAnalytique(str(e)) from e

    if not revue.get("disponible"):
        raise ErreurCommentaireAnalytique(
            "revue analytique indisponible pour cette mission — "
            "il faut une mission N-1 avec des soldes comparables"
        )

    variations = [
        {
            "poste": str(ligne.get("compte") or ""),
            "libelle": ligne.get("libelle"),
            "solde_n": ligne.get("solde_n"),
            "solde_n1": ligne.get("solde_n1"),
            "variation_fcfa": ligne.get("variation"),
            "variation_pct": ligne.get("variation_pct"),
            "sens": ligne.get("sens"),
            "classement": ligne.get("classement"),
        }
        for ligne in revue.get("lignes") or []
        if str(ligne.get("classement") or "") != CLASSEMENT_STABLE
        and str(ligne.get("compte") or "").strip()
    ][:ELEMENTS_MAX]

    if not variations:
        raise ErreurCommentaireAnalytique(
            "aucune variation significative à commenter pour cette mission"
        )

    return {
        "mission_id": mission_id,
        "exercice_n": revue.get("exercice_n"),
        "exercice_n1": revue.get("exercice_n1"),
        "variations": variations,
    }


# ── LLM ────────────────────────────────────────────────────────────


def _parser_json_llm(contenu: str) -> dict[str, Any]:
    try:
        brut = json.loads(contenu)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", contenu)
        if not m:
            raise ErreurCommentaireAnalytique("réponse LLM non JSON") from None
        try:
            brut = json.loads(m.group(0))
        except json.JSONDecodeError:
            raise ErreurCommentaireAnalytique("réponse LLM non JSON") from None
    if not isinstance(brut, dict):
        raise ErreurCommentaireAnalytique("réponse LLM non JSON")
    return brut


def _appeler_llm_commentaire(
    contexte: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    from backend.abonne.extraction_identite import message_erreur_llm_fr
    from backend.socle import llm_providers

    if not llm_providers.providers_configures():
        raise ErreurCommentaireAnalytique(
            "Commentaire analytique indisponible pour le moment. "
            "Réessayez plus tard."
        )
    user = (
        "Variations significatives de la revue analytique (JSON) :\n"
        + json.dumps(contexte, ensure_ascii=False, default=str)
    )
    messages = [
        {"role": "system", "content": _PROMPT_COMMENTAIRE},
        {"role": "user", "content": user},
    ]
    t0 = time.perf_counter()
    try:
        contenu, provider_id, failover = llm_providers.appeler_chat(
            messages, capacite="chat", temperature=0, json_object=True
        )
    except llm_providers.ErreurLlm as e:
        logger.info(
            "commentaire_analytique_llm_echec duree_ms=%s",
            int((time.perf_counter() - t0) * 1000),
        )
        raise ErreurCommentaireAnalytique(message_erreur_llm_fr(e)) from e
    logger.info(
        "commentaire_analytique_llm_ok provider=%s failover_depuis=%s "
        "duree_ms=%s",
        provider_id,
        list(failover),
        int((time.perf_counter() - t0) * 1000),
    )
    return _parser_json_llm(contenu), provider_id


# ── Persistance versionnée ─────────────────────────────────────────


def _serialiser(row: dict[str, Any], *, avec_contenu: bool) -> dict[str, Any]:
    cree = row.get("cree_le")
    out: dict[str, Any] = {
        "id": int(row["id"]),
        "mission_id": int(row["mission_id"]),
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


def _exiger_mission(session: Session, mission_id: int) -> None:
    existe = session.execute(
        text("SELECT 1 FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).scalar_one_or_none()
    if existe is None:
        raise ErreurCommentaireAnalytique(
            f"mission {mission_id} introuvable"
        )


def generation_en_cours(
    session: Session, tenant_id: int, mission_id: int
) -> bool:
    """Anti-rafale : une génération ``en_cours`` récente bloque la suivante."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT 1 FROM commentaire_revue_analytique "
                "WHERE mission_id = :m AND statut = 'en_cours' "
                "AND cree_le > now() - make_interval(mins => :mn) LIMIT 1"
            ),
            {"m": mission_id, "mn": EN_COURS_BLOQUANT_MINUTES},
        ).scalar_one_or_none()
    return row is not None


def generer_commentaire(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    auteur: str | None = None,
) -> dict[str, Any]:
    """Génère une nouvelle version de commentaire (synchrone, consultatif)."""
    if generation_en_cours(session, tenant_id, mission_id):
        raise ErreurCommentaireAnalytique(
            "une génération est déjà en cours pour cette mission — "
            "réessayez dans quelques instants"
        )
    contexte = construire_contexte(session, tenant_id, mission_id)
    with contexte_tenant(session, tenant_id):
        version = session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 "
                "FROM commentaire_revue_analytique WHERE mission_id = :m"
            ),
            {"m": mission_id},
        ).scalar_one()
        commentaire_id = session.execute(
            text(
                "INSERT INTO commentaire_revue_analytique "
                "(tenant_id, mission_id, version, statut, auteur) "
                "VALUES (:t, :m, :v, 'en_cours', :aut) RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "v": int(version),
                "aut": (auteur or "").strip() or None,
            },
        ).scalar_one()
        session.flush()

    try:
        brut, provider_id = _appeler_llm_commentaire(contexte)
        contenu = normaliser_contenu_commentaire(
            brut, postes_du_contexte(contexte)
        )
    except ErreurCommentaireAnalytique as e:
        with contexte_tenant(session, tenant_id):
            row = session.execute(
                text(
                    "UPDATE commentaire_revue_analytique "
                    "SET statut = 'echec', erreur = :err WHERE id = :id "
                    "RETURNING id, mission_id, version, statut, contenu, "
                    "modele, erreur, auteur, cree_le"
                ),
                {"id": int(commentaire_id), "err": str(e)[:1000]},
            ).mappings().one()
            session.flush()
        return _serialiser(dict(row), avec_contenu=True)

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE commentaire_revue_analytique "
                "SET statut = 'disponible', "
                "contenu = CAST(:ct AS jsonb), modele = :mod, erreur = NULL "
                "WHERE id = :id "
                "RETURNING id, mission_id, version, statut, contenu, "
                "modele, erreur, auteur, cree_le"
            ),
            {
                "id": int(commentaire_id),
                "ct": json.dumps(contenu, ensure_ascii=False),
                "mod": provider_id,
            },
        ).mappings().one()
        session.flush()
    return _serialiser(dict(row), avec_contenu=True)


def lister_commentaires(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    """Versions du commentaire d'une mission — 404 si mission hors tenant."""
    with contexte_tenant(session, tenant_id):
        _exiger_mission(session, mission_id)
        rows = session.execute(
            text(
                "SELECT id, mission_id, version, statut, modele, erreur, "
                "auteur, cree_le FROM commentaire_revue_analytique "
                "WHERE mission_id = :m ORDER BY version DESC, id DESC"
            ),
            {"m": mission_id},
        ).mappings().all()
        return [_serialiser(dict(r), avec_contenu=False) for r in rows]


def obtenir_commentaire(
    session: Session,
    tenant_id: int,
    mission_id: int,
    version: int,
) -> dict[str, Any]:
    """Commentaire d'une mission par numéro de version (contenu inclus)."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, mission_id, version, statut, contenu, modele, "
                "erreur, auteur, cree_le FROM commentaire_revue_analytique "
                "WHERE mission_id = :m AND version = :v "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"m": mission_id, "v": version},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurCommentaireAnalytique(
                f"commentaire analytique v{version} introuvable "
                f"pour la mission {mission_id}"
            )
        return _serialiser(dict(row), avec_contenu=True)
