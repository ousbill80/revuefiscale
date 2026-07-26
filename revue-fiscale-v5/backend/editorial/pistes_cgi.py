"""Pistes CGI 2026 × file a_confirmer — outillage éditorial, pas visa."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

RACINE = Path(__file__).resolve().parents[2]
FICHIER_PISTES = RACINE / "referentiel" / "propositions_cgi_2026_pistes.json"
SOURCE_PROPOSITION = "cgi_2026_croisement"


def charger_catalogue_pistes(chemin: Path | None = None) -> dict[str, Any]:
    path = chemin or FICHIER_PISTES
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("pistes"), list):
        raise ValueError("catalogue pistes CGI invalide : clé pistes absente")
    return data


def index_pistes_par_entree(catalogue: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    cat = catalogue or charger_catalogue_pistes()
    out: dict[str, dict[str, Any]] = {}
    for p in cat.get("pistes") or []:
        if not isinstance(p, dict):
            continue
        eid = str(p.get("entree_id") or "").strip()
        if eid:
            out[eid] = p
    return out


def ids_entrees_pistes(catalogue: dict[str, Any] | None = None) -> frozenset[str]:
    return frozenset(index_pistes_par_entree(catalogue).keys())


def _charge_utile(piste: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    charge: dict[str, Any] = {
        "lot": catalogue.get("lot"),
        "piste_id": piste["piste_id"],
        "entree_id": piste["entree_id"],
        "rule_id": piste["rule_id"],
        "categorie_mention": piste.get("categorie_mention"),
        "article_corpus": piste.get("article_corpus"),
        "extrait_cgi": piste.get("extrait_cgi"),
        "suggestion": piste.get("suggestion"),
        "suggestion_valeur": piste.get("suggestion_valeur"),
        "interdiction": piste.get("interdiction"),
        "statut_editorial": piste.get("statut_editorial") or "a_valider_humain",
        "rapport": catalogue.get("rapport"),
        "checklist": catalogue.get("checklist"),
        "avertissement": catalogue.get("avertissement"),
    }
    # Transmettre le garde-fou catalogue (jamais inventé ici).
    if isinstance(piste.get("suggestion_structuree"), dict):
        charge["suggestion_structuree"] = piste["suggestion_structuree"]
    return charge


def _sources(piste: dict[str, Any], catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "cgi",
            "document": catalogue.get("source_document"),
            "texte_juridique": catalogue.get("texte_juridique"),
            "article_corpus": piste.get("article_corpus"),
            "extrait": piste.get("extrait_cgi"),
            "rapport": catalogue.get("rapport"),
        }
    ]


def deposer_propositions_pistes(
    session: Session,
    *,
    chemin: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Dépose les propositions en file (statut ouverte) — idempotent par piste_id.

    N'accepte / ne rejette / ne purge rien. Domaine éditorial.
    """
    catalogue = charger_catalogue_pistes(chemin)
    creees: list[dict[str, Any]] = []
    ignorees: list[dict[str, Any]] = []
    for piste in catalogue["pistes"]:
        piste_id = str(piste["piste_id"])
        existant = session.execute(
            text(
                "SELECT id FROM proposition_editoriale "
                "WHERE source = :src "
                "AND charge_utile->>'piste_id' = :pid "
                "AND statut = 'ouverte' "
                "LIMIT 1"
            ),
            {"src": SOURCE_PROPOSITION, "pid": piste_id},
        ).scalar_one_or_none()
        if existant is not None and not force:
            ignorees.append(
                {
                    "piste_id": piste_id,
                    "entree_id": piste["entree_id"],
                    "proposition_id": int(existant),
                    "raison": "deja_ouverte",
                }
            )
            continue
        pid = session.execute(
            text(
                "INSERT INTO proposition_editoriale (source, charge_utile, sources) "
                "VALUES (:src, CAST(:cu AS jsonb), CAST(:sources AS jsonb)) "
                "RETURNING id"
            ),
            {
                "src": SOURCE_PROPOSITION,
                "cu": json.dumps(
                    _charge_utile(piste, catalogue), ensure_ascii=False, default=str
                ),
                "sources": json.dumps(
                    _sources(piste, catalogue), ensure_ascii=False, default=str
                ),
            },
        ).scalar_one()
        creees.append(
            {
                "piste_id": piste_id,
                "entree_id": piste["entree_id"],
                "rule_id": piste["rule_id"],
                "proposition_id": int(pid),
            }
        )
    session.flush()
    return {
        "lot": catalogue.get("lot"),
        "source": SOURCE_PROPOSITION,
        "creees": creees,
        "ignorees": ignorees,
        "n_creees": len(creees),
        "n_ignorees": len(ignorees),
        "avertissement": catalogue.get("avertissement"),
    }


def lier_propositions_ouvertes(
    session: Session,
    catalogue: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map entree_id → méta piste CGI + proposition_id ouverte (si seedée)."""
    cat = catalogue or charger_catalogue_pistes()
    index = index_pistes_par_entree(cat)
    rows = session.execute(
        text(
            "SELECT id, charge_utile FROM proposition_editoriale "
            "WHERE source = :src AND statut = 'ouverte' "
            "ORDER BY id DESC"
        ),
        {"src": SOURCE_PROPOSITION},
    ).mappings().all()
    prop_par_piste: dict[str, int] = {}
    for r in rows:
        cu = r["charge_utile"] or {}
        if isinstance(cu, str):
            cu = json.loads(cu)
        pid_piste = str(cu.get("piste_id") or "")
        if pid_piste and pid_piste not in prop_par_piste:
            prop_par_piste[pid_piste] = int(r["id"])

    out: dict[str, dict[str, Any]] = {}
    for eid, piste in index.items():
        prop_id = prop_par_piste.get(str(piste["piste_id"]))
        sug = piste.get("suggestion_structuree")
        sug_d = sug if isinstance(sug, dict) else {}
        retirer_ok = bool(sug_d.get("retirer_a_confirmer_autorise", False))
        champ = sug_d.get("champ")
        out[eid] = {
            "piste_cgi": True,
            "lot": cat.get("lot"),
            "piste_id": piste["piste_id"],
            "rule_id": piste["rule_id"],
            "article_corpus": piste.get("article_corpus"),
            "extrait_cgi": piste.get("extrait_cgi"),
            "suggestion": piste.get("suggestion"),
            "suggestion_valeur": piste.get("suggestion_valeur"),
            "suggestion_structuree": sug_d or None,
            "retirer_a_confirmer_autorise": retirer_ok,
            "peut_preparer_patch": bool(prop_id),
            "peut_appliquer": bool(
                prop_id and (champ or retirer_ok)
            ),
            "statut_editorial": piste.get("statut_editorial") or "a_valider_humain",
            "proposition_id": prop_id,
            "checklist": cat.get("checklist"),
            "rapport": cat.get("rapport"),
        }
    return out


def enrichir_entrees_file(
    entrees: list[dict[str, Any]],
    liens: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ajoute badge / lien proposition CGI sur les entrées de la file a_confirmer."""
    enrichies: list[dict[str, Any]] = []
    for e in entrees:
        if not isinstance(e, dict):
            continue
        copie = dict(e)
        eid = str(e.get("id") or "")
        meta = liens.get(eid)
        if meta:
            copie["piste_cgi"] = True
            copie["piste_cgi_meta"] = meta
            # Ne pas écraser une proposition Annexe déjà liée
            if not copie.get("proposition_id"):
                copie["proposition_id"] = meta.get("proposition_id")
            copie["proposition_id_cgi"] = meta.get("proposition_id")
            copie["peut_preparer_patch"] = bool(
                copie.get("peut_preparer_patch") or meta.get("peut_preparer_patch")
            )
            copie["peut_appliquer"] = bool(
                copie.get("peut_appliquer") or meta.get("peut_appliquer")
            )
            if meta.get("retirer_a_confirmer_autorise") is not None:
                copie["retirer_a_confirmer_autorise"] = bool(
                    copie.get("retirer_a_confirmer_autorise")
                    or meta.get("retirer_a_confirmer_autorise")
                )
        else:
            copie["piste_cgi"] = False
        copie["piste_sourcee"] = bool(copie.get("piste_annexe") or copie.get("piste_cgi"))
        enrichies.append(copie)
    return enrichies
