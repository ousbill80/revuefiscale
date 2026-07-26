"""Note de synthèse de mission — executive summary IA versionné.

L'associé signataire n'a pas le temps de lire toute la restitution : la
note rassemble contexte, principaux constats chiffrés hiérarchisés par
gravité, exposition estimée, points d'attention (fiabilité source, revue
analytique) et recommandations prioritaires. Traçabilité stricte : chaque
constat cite la règle (``regle_id``) dont il provient ; tout constat dont
la règle est inconnue du contexte fourni est RETIRÉ. Jamais appliquée
automatiquement — l'humain signe.
"""
from __future__ import annotations

import json
import logging
import re
import time
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

logger = logging.getLogger(__name__)

GRAVITES: Final[frozenset[str]] = frozenset({"faible", "moyenne", "haute"})
GRAVITE_DEFAUT: Final[str] = "moyenne"
TEXTE_MAX: Final[int] = 2000
ELEMENTS_MAX: Final[int] = 30
# Statuts de conclusion retenus dans la note : anomalies et points à
# instruire (non vérifiables) — jamais les conformes / hors périmètre.
STATUTS_CONSTAT: Final[frozenset[str]] = frozenset(
    {"anomalie", "non_verifiable"}
)
# Anti-rafale : une génération en_cours plus récente que ce délai bloque.
EN_COURS_BLOQUANT_MINUTES: Final[int] = 10

_PROMPT_NOTE = """Tu es un assistant de rédaction pour un cabinet de revue
fiscale en Côte d'Ivoire. On te fournit le dossier chiffré d'une mission :
identification, constats issus des règles du référentiel (chacun porte un
"regle_id"), exposition du registre des risques, contrôles de fiabilité de
la source (FEC) et revue analytique N/N-1 si disponible. Rédige la NOTE DE
SYNTHÈSE de mission destinée à l'associé signataire.

Règles strictes :
- N'utilise QUE les données fournies. Si une information manque, n'en
  parle pas. N'invente rien.
- Ne cite aucun article de loi ni référence légale non présent dans les
  données fournies.
- Chaque constat reprend EXACTEMENT un "regle_id" présent dans les
  constats fournis, avec le montant fourni (ne recalcule rien).
- "gravite" parmi : faible | moyenne | haute (hiérarchise les constats).
- "contexte" : contexte et périmètre de la mission en 2 lignes maximum.
- "exposition" : exposition estimée d'après les montants fournis.
- "points_attention" : fiabilité de la source (contrôles FEC en alerte),
  revue analytique, limites du périmètre — d'après les données fournies.
- "recommandations" : actions prioritaires concrètes pour le cabinet.
- Français professionnel, concis. Pas de nom de fournisseur technique.

Réponds UNIQUEMENT en JSON valide :
{
  "contexte": "…",
  "constats": [
    {"regle_id": "…", "resume": "…", "montant": "…", "gravite": "haute"}
  ],
  "exposition": "…",
  "points_attention": ["…"],
  "recommandations": ["…"]
}
"""


class ErreurNoteSynthese(Exception):
    """Echec génération / lecture de note de synthèse de mission."""


# ── Coercition pure ────────────────────────────────────────────────


def regles_du_contexte(contexte: dict[str, Any]) -> set[str]:
    """Identifiants de règles citables d'un contexte de note — pure."""
    regles: set[str] = set()
    for item in contexte.get("constats") or []:
        ref = str((item or {}).get("regle_id") or "").strip()
        if ref:
            regles.add(ref)
    return regles


def _liste_textes(brut: Any) -> list[str]:
    out: list[str] = []
    for item in brut if isinstance(brut, list) else []:
        if isinstance(item, (dict, list)):
            continue
        texte = str(item or "").strip()[:TEXTE_MAX]
        if texte:
            out.append(texte)
    return out[:ELEMENTS_MAX]


def normaliser_contenu_note(
    brut: Any, regles_connues: set[str]
) -> dict[str, Any]:
    """Coercition du JSON LLM vers le schéma strict — pure, testable.

    Tout constat dont ``regle_id`` est inconnu du contexte est RETIRÉ ;
    gravité invalide → moyenne ; éléments sans résumé ignorés.
    """
    src = brut if isinstance(brut, dict) else {}
    contexte = str(src.get("contexte") or "").strip()[:TEXTE_MAX]
    exposition = str(src.get("exposition") or "").strip()[:TEXTE_MAX]

    constats: list[dict[str, Any]] = []
    for item in (
        src.get("constats") if isinstance(src.get("constats"), list) else []
    ):
        if not isinstance(item, dict):
            continue
        regle_id = str(item.get("regle_id") or "").strip()
        if regle_id not in regles_connues:
            continue  # traçabilité stricte : règle inconnue → constat retiré
        resume = str(item.get("resume") or "").strip()[:TEXTE_MAX]
        if not resume:
            continue
        gravite = str(item.get("gravite") or "").strip().lower()
        if gravite not in GRAVITES:
            gravite = GRAVITE_DEFAUT
        montant_brut = item.get("montant")
        montant = (
            str(montant_brut).strip()[:100]
            if montant_brut is not None and str(montant_brut).strip()
            else None
        )
        constats.append(
            {
                "regle_id": regle_id,
                "resume": resume,
                "montant": montant,
                "gravite": gravite,
            }
        )

    return {
        "contexte": contexte,
        "constats": constats[:ELEMENTS_MAX],
        "exposition": exposition,
        "points_attention": _liste_textes(src.get("points_attention")),
        "recommandations": _liste_textes(src.get("recommandations")),
    }


# ── Contexte déterministe (sources stables) ────────────────────────


def _dec_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return str(Decimal(str(v)))
    except Exception:  # noqa: BLE001 — valeur non numérique tolérée
        return str(v)


def construire_contexte(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rassemble de façon déterministe le dossier chiffré de la mission.

    Lecture seule : conclusions de la dernière exécution (anomalies / à
    instruire avec regle_id, montant, comptes source), exposition du
    registre des risques, contrôles FEC en alerte, revue analytique.
    """
    from backend.plateforme.revue_analytique import (
        ErreurRevueAnalytique,
        revue_analytique_mission,
    )
    from backend.plateforme.risques import STATUTS_NON_CLOS, lister_risques
    from backend.restitution.service import (
        _charger_conclusions,
        _derniere_execution,
    )
    from backend.socle.depot import derniers_controles_fec

    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT m.id, m.exercice, m.statut, m.contribuable_id, "
                "m.type_engagement, m.perimetre_impots, "
                "m.exclusions_declarees, m.seuil_signification, "
                "c.denomination, c.ncc, c.regime_fiscal, c.forme_juridique "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurNoteSynthese(f"mission {mission_id} introuvable")
        exec_id = _derniere_execution(session, mission_id)
        conclusions = (
            _charger_conclusions(session, int(exec_id))
            if exec_id is not None
            else []
        )
        controles = derniers_controles_fec(session, mission_id)

    try:
        revue = revue_analytique_mission(session, tenant_id, mission_id)
    except ErreurRevueAnalytique:
        revue = None

    risques = [
        r
        for r in lister_risques(
            session, tenant_id, contribuable_id=int(mission["contribuable_id"])
        )
        if str(r.get("statut") or "ouvert") in STATUTS_NON_CLOS
    ]

    constats = [
        {
            "regle_id": str(c["regle_id"]),
            "statut": str(c.get("statut") or "anomalie"),
            "montant": _dec_str(c.get("montant")),
            "sens": c.get("sens"),
            "niveau_risque": c.get("niveau_risque"),
            "commentaire": (
                str(c.get("commentaire"))[:500]
                if c.get("commentaire")
                else None
            ),
            "comptes_source": [
                {
                    "compte": str(cs.get("compte") or ""),
                    "libelle": cs.get("libelle"),
                    "solde": _dec_str(cs.get("solde")),
                }
                for cs in (c.get("comptes_source") or [])
                if isinstance(cs, dict)
            ][:10],
        }
        for c in conclusions
        if str(c.get("statut") or "anomalie") in STATUTS_CONSTAT
    ]

    total_expo = Decimal("0")
    lignes_expo: list[dict[str, Any]] = []
    for r in risques:
        mt = r.get("montant_estime")
        if mt is not None:
            try:
                total_expo += Decimal(str(mt))
            except Exception:  # noqa: BLE001
                pass
        lignes_expo.append(
            {
                "impot": r.get("impot"),
                "libelle": r.get("libelle"),
                "statut": r.get("statut"),
                "probabilite": r.get("probabilite"),
                "montant_estime": _dec_str(mt),
                "penalites_estimees": _dec_str(r.get("penalites_estimees")),
            }
        )

    alertes_fec: list[dict[str, Any]] = []
    if controles is not None:
        for ctl in controles.get("controles") or []:
            if not isinstance(ctl, dict):
                continue
            if str(ctl.get("statut") or "") != "alerte":
                continue
            alertes_fec.append(
                {
                    "code": ctl.get("code"),
                    "libelle": ctl.get("libelle"),
                    "compteur": ctl.get("compteur"),
                }
            )

    revue_ctx: dict[str, Any] = {"disponible": False}
    if revue is not None and revue.get("disponible"):
        lignes = [
            ligne
            for ligne in revue.get("lignes") or []
            if str(ligne.get("classement") or "") != "stable"
        ]
        revue_ctx = {
            "disponible": True,
            "exercice_n": revue.get("exercice_n"),
            "exercice_n1": revue.get("exercice_n1"),
            "nb_variations_significatives": len(lignes),
            "lignes_significatives": lignes[:20],
            "totaux_par_classe": revue.get("totaux_par_classe") or [],
        }

    seuil = mission.get("seuil_signification")
    return {
        "mission": {
            "mission_id": int(mission["id"]),
            "exercice": mission.get("exercice"),
            "statut": mission.get("statut"),
            "denomination": mission.get("denomination"),
            "ncc": mission.get("ncc"),
            "regime_fiscal": mission.get("regime_fiscal"),
            "forme_juridique": mission.get("forme_juridique"),
            "type_engagement": mission.get("type_engagement"),
            "perimetre_impots": mission.get("perimetre_impots"),
            "exclusions_declarees": mission.get("exclusions_declarees"),
            "seuil_signification": _dec_str(seuil),
        },
        "constats": constats,
        "exposition": {
            "total_estime": str(total_expo) if lignes_expo else None,
            "nb_risques_ouverts": len(lignes_expo),
            "risques": lignes_expo[:30],
        },
        "controles_fec": {
            "disponible": controles is not None,
            "exercice": controles.get("exercice") if controles else None,
            "alertes": alertes_fec,
        },
        "revue_analytique": revue_ctx,
    }


# ── LLM ────────────────────────────────────────────────────────────


def _parser_json_llm(contenu: str) -> dict[str, Any]:
    try:
        brut = json.loads(contenu)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", contenu)
        if not m:
            raise ErreurNoteSynthese("réponse LLM non JSON") from None
        try:
            brut = json.loads(m.group(0))
        except json.JSONDecodeError:
            raise ErreurNoteSynthese("réponse LLM non JSON") from None
    if not isinstance(brut, dict):
        raise ErreurNoteSynthese("réponse LLM non JSON")
    return brut


def _appeler_llm_note(contexte: dict[str, Any]) -> tuple[dict[str, Any], str]:
    from backend.abonne.extraction_identite import message_erreur_llm_fr
    from backend.socle import llm_providers

    if not llm_providers.providers_configures():
        raise ErreurNoteSynthese(
            "Note de synthèse indisponible pour le moment. Réessayez plus tard."
        )
    user = (
        "Dossier mission (JSON) :\n"
        + json.dumps(contexte, ensure_ascii=False, default=str)
    )
    messages = [
        {"role": "system", "content": _PROMPT_NOTE},
        {"role": "user", "content": user},
    ]
    t0 = time.perf_counter()
    try:
        contenu, provider_id, failover = llm_providers.appeler_chat(
            messages, capacite="chat", temperature=0, json_object=True
        )
    except llm_providers.ErreurLlm as e:
        logger.info(
            "note_synthese_llm_echec duree_ms=%s",
            int((time.perf_counter() - t0) * 1000),
        )
        raise ErreurNoteSynthese(message_erreur_llm_fr(e)) from e
    logger.info(
        "note_synthese_llm_ok provider=%s failover_depuis=%s duree_ms=%s",
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
        raise ErreurNoteSynthese(f"mission {mission_id} introuvable")


def generation_en_cours(
    session: Session, tenant_id: int, mission_id: int
) -> bool:
    """Anti-rafale : une génération ``en_cours`` récente bloque la suivante."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT 1 FROM note_synthese_mission "
                "WHERE mission_id = :m AND statut = 'en_cours' "
                "AND cree_le > now() - make_interval(mins => :mn) LIMIT 1"
            ),
            {"m": mission_id, "mn": EN_COURS_BLOQUANT_MINUTES},
        ).scalar_one_or_none()
    return row is not None


def generer_note(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    auteur: str | None = None,
) -> dict[str, Any]:
    """Génère une nouvelle version de note (synchrone, consultative)."""
    contexte = construire_contexte(session, tenant_id, mission_id)
    if generation_en_cours(session, tenant_id, mission_id):
        raise ErreurNoteSynthese(
            "une génération est déjà en cours pour cette mission — "
            "réessayez dans quelques instants"
        )
    with contexte_tenant(session, tenant_id):
        version = session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 "
                "FROM note_synthese_mission WHERE mission_id = :m"
            ),
            {"m": mission_id},
        ).scalar_one()
        note_id = session.execute(
            text(
                "INSERT INTO note_synthese_mission "
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
        brut, provider_id = _appeler_llm_note(contexte)
        contenu = normaliser_contenu_note(brut, regles_du_contexte(contexte))
    except ErreurNoteSynthese as e:
        with contexte_tenant(session, tenant_id):
            row = session.execute(
                text(
                    "UPDATE note_synthese_mission "
                    "SET statut = 'echec', erreur = :err WHERE id = :id "
                    "RETURNING id, mission_id, version, statut, contenu, "
                    "modele, erreur, auteur, cree_le"
                ),
                {"id": int(note_id), "err": str(e)[:1000]},
            ).mappings().one()
            session.flush()
        return _serialiser(dict(row), avec_contenu=True)

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE note_synthese_mission "
                "SET statut = 'disponible', "
                "contenu = CAST(:ct AS jsonb), modele = :mod, erreur = NULL "
                "WHERE id = :id "
                "RETURNING id, mission_id, version, statut, contenu, "
                "modele, erreur, auteur, cree_le"
            ),
            {
                "id": int(note_id),
                "ct": json.dumps(contenu, ensure_ascii=False),
                "mod": provider_id,
            },
        ).mappings().one()
        session.flush()
    return _serialiser(dict(row), avec_contenu=True)


def lister_notes(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    """Versions de la note d'une mission — 404 si mission hors tenant."""
    with contexte_tenant(session, tenant_id):
        _exiger_mission(session, mission_id)
        rows = session.execute(
            text(
                "SELECT id, mission_id, version, statut, modele, erreur, "
                "auteur, cree_le FROM note_synthese_mission "
                "WHERE mission_id = :m ORDER BY version DESC, id DESC"
            ),
            {"m": mission_id},
        ).mappings().all()
        return [_serialiser(dict(r), avec_contenu=False) for r in rows]


def obtenir_note(
    session: Session,
    tenant_id: int,
    mission_id: int,
    version: int,
) -> dict[str, Any]:
    """Note d'une mission par numéro de version (contenu inclus)."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, mission_id, version, statut, contenu, modele, "
                "erreur, auteur, cree_le FROM note_synthese_mission "
                "WHERE mission_id = :m AND version = :v "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"m": mission_id, "v": version},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurNoteSynthese(
                f"note de synthèse v{version} introuvable "
                f"pour la mission {mission_id}"
            )
        return _serialiser(dict(row), avec_contenu=True)
