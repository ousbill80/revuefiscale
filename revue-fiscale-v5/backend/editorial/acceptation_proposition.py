"""Acceptation contrôlée d'une proposition éditoriale → YAML (domaine éditorial).

Règles :
- Sans suggestion structurée : statut workflow seulement, ou patch préparatoire.
- Avec ``appliquer_yaml`` + suggestion : écrit **uniquement** le champ ciblé.
- Retrait d'un ``a_confirmer`` précis : seulement si la suggestion l'autorise
  **et** l'humain passe ``retirer_mention_a_confirmer=true``.
- Backup YAML avant écriture. Journal append-only.
- Le refus / rejet ne touche aucun fichier.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

RACINE = Path(__file__).resolve().parents[2]
RACINE_REFERENTIEL = RACINE / "referentiel"
DIR_BACKUPS = RACINE_REFERENTIEL / ".backups_editorial"
JOURNAL = RACINE_REFERENTIEL / "journal_editorial_acceptations.jsonl"

ModeAcceptation = Literal["statut_seul", "preparer_patch", "appliquer"]


class ErreurAcceptation(Exception):
    pass


@dataclass
class SuggestionStructuree:
    champ: str | None
    valeur: Any
    index_a_confirmer: int | None
    entree_id: str | None
    retirer_a_confirmer_autorise: bool
    source_url: str | None = None
    extrait: str | None = None
    article_corpus: str | None = None

    @classmethod
    def depuis_charge(cls, charge: dict[str, Any]) -> SuggestionStructuree | None:
        raw = charge.get("suggestion_structuree")
        if not isinstance(raw, dict):
            # Repli minimal depuis catalogue piste
            if charge.get("entree_id") and (
                charge.get("suggestion_valeur") is not None
                or charge.get("extrait_cgi")
            ):
                eid = str(charge["entree_id"])
                idx = None
                if "#" in eid:
                    try:
                        idx = int(eid.split("#")[-1])
                    except ValueError:
                        idx = None
                return cls(
                    champ=None,
                    valeur=charge.get("suggestion_valeur"),
                    index_a_confirmer=idx,
                    entree_id=eid,
                    retirer_a_confirmer_autorise=False,
                    extrait=charge.get("extrait_cgi"),
                    article_corpus=charge.get("article_corpus"),
                )
            return None
        eid = raw.get("entree_id") or charge.get("entree_id")
        idx = raw.get("index_a_confirmer")
        if idx is None and isinstance(eid, str) and "#" in eid:
            try:
                idx = int(eid.split("#")[-1])
            except ValueError:
                idx = None
        return cls(
            champ=raw.get("champ"),
            valeur=raw.get("valeur", charge.get("suggestion_valeur")),
            index_a_confirmer=int(idx) if idx is not None else None,
            entree_id=str(eid) if eid else None,
            retirer_a_confirmer_autorise=bool(
                raw.get("retirer_a_confirmer_autorise", False)
            ),
            source_url=raw.get("source_url"),
            extrait=raw.get("extrait") or charge.get("extrait_cgi"),
            article_corpus=raw.get("article_corpus") or charge.get("article_corpus"),
        )


def _chemin_yaml(rule_id: str) -> Path:
    chemin = (RACINE_REFERENTIEL / f"{rule_id}.yaml").resolve()
    if not str(chemin).startswith(str(RACINE_REFERENTIEL.resolve())):
        raise ErreurAcceptation("chemin YAML refusé")
    if not chemin.is_file():
        raise ErreurAcceptation(f"YAML introuvable : {rule_id}.yaml")
    return chemin


def _charger_yaml(chemin: Path) -> dict[str, Any]:
    data = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ErreurAcceptation("YAML invalide")
    return data


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _backup(chemin: Path) -> Path:
    DIR_BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = DIR_BACKUPS / f"{chemin.stem}.{stamp}.yaml"
    shutil.copy2(chemin, dest)
    return dest


def _journaliser(entree: dict[str, Any]) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")


def preparer_patch_yaml(
    charge: dict[str, Any],
    *,
    retirer_mention: bool = False,
) -> dict[str, Any]:
    """Calcule un patch téléchargeable sans écrire le disque."""
    sug = SuggestionStructuree.depuis_charge(charge)
    if sug is None:
        raise ErreurAcceptation(
            "pas de suggestion structurée — impossible de préparer un patch ciblé"
        )
    rule_id = str(charge.get("rule_id") or "")
    if not rule_id:
        raise ErreurAcceptation("rule_id manquant")
    chemin = _chemin_yaml(rule_id)
    avant = _charger_yaml(chemin)
    apres = dict(avant)
    operations: list[dict[str, Any]] = []

    if sug.champ:
        if sug.champ not in apres and sug.champ != "a_confirmer":
            # champ nouveau autorisé seulement si déjà clé connue du format pivot
            raise ErreurAcceptation(
                f"champ inconnu dans le YAML : {sug.champ} "
                "(écriture limitée aux champs existants)"
            )
        if sug.champ == "a_confirmer":
            raise ErreurAcceptation(
                "utiliser retirer_mention_a_confirmer pour a_confirmer, pas champ="
            )
        operations.append(
            {
                "op": "set_champ",
                "champ": sug.champ,
                "avant": apres.get(sug.champ),
                "apres": sug.valeur,
            }
        )
        apres[sug.champ] = sug.valeur

    mention_retiree = None
    if retirer_mention:
        if not sug.retirer_a_confirmer_autorise:
            raise ErreurAcceptation(
                "cette proposition n'autorise pas le retrait a_confirmer "
                "(retirer_a_confirmer_autorise=false)"
            )
        if sug.index_a_confirmer is None:
            raise ErreurAcceptation("index_a_confirmer manquant")
        ac = list(apres.get("a_confirmer") or [])
        if sug.index_a_confirmer < 0 or sug.index_a_confirmer >= len(ac):
            raise ErreurAcceptation(
                f"index a_confirmer hors bornes : {sug.index_a_confirmer}"
            )
        mention_retiree = ac[sug.index_a_confirmer]
        ac_new = list(ac)
        del ac_new[sug.index_a_confirmer]
        operations.append(
            {
                "op": "retirer_a_confirmer",
                "index": sug.index_a_confirmer,
                "texte": mention_retiree,
            }
        )
        apres["a_confirmer"] = ac_new

    if not operations:
        # Patch « proposition » sans mutation : utile pour revue humaine / PR draft
        return {
            "rule_id": rule_id,
            "fichier": chemin.name,
            "entree_id": sug.entree_id,
            "operations": [],
            "mention_retiree": None,
            "yaml_avant": _dump_yaml(avant),
            "yaml_apres": (
                "# Proposition éditoriale (aucune mutation appliquée)\n"
                f"# entree_id: {sug.entree_id}\n"
                f"# valeur suggérée: {sug.valeur}\n"
                f"# extrait: {sug.extrait}\n"
                f"# retirer_a_confirmer_autorise: {sug.retirer_a_confirmer_autorise}\n"
                f"# Pour appliquer: mode=appliquer + champ et/ou "
                "retirer_mention_a_confirmer=true (si autorisé).\n\n"
                + _dump_yaml(avant)
            ),
            "suggestion": asdict(sug),
            "avertissement": (
                "Aucune mutation calculée (pas de champ ni retrait). "
                "Document de proposition seulement — YAML disque intact."
            ),
        }

    return {
        "rule_id": rule_id,
        "fichier": chemin.name,
        "entree_id": sug.entree_id,
        "operations": operations,
        "mention_retiree": mention_retiree,
        "yaml_avant": _dump_yaml(avant),
        "yaml_apres": _dump_yaml(apres),
        "suggestion": asdict(sug),
        "avertissement": (
            "Patch préparatoire — non écrit sur disque. "
            "Vérifier avant appliquer_yaml."
        ),
    }


def appliquer_patch_yaml(
    charge: dict[str, Any],
    *,
    par: str,
    retirer_mention: bool = False,
    proposition_id: int | None = None,
    sources: list[Any] | None = None,
) -> dict[str, Any]:
    """Écrit le YAML avec backup + journal. Un seul champ / une mention."""
    patch = preparer_patch_yaml(charge, retirer_mention=retirer_mention)
    chemin = _chemin_yaml(patch["rule_id"])
    backup = _backup(chemin)
    chemin.write_text(patch["yaml_apres"], encoding="utf-8")
    journal = {
        "quand": datetime.now(UTC).isoformat(),
        "par": par,
        "proposition_id": proposition_id,
        "rule_id": patch["rule_id"],
        "entree_id": patch.get("entree_id"),
        "operations": patch["operations"],
        "backup": str(backup.relative_to(RACINE)),
        "sources": sources or [],
        "extrait": (patch.get("suggestion") or {}).get("extrait"),
        "source_url": (patch.get("suggestion") or {}).get("source_url"),
    }
    _journaliser(journal)
    return {
        **patch,
        "ecrit": True,
        "backup": str(backup),
        "journal": journal,
        "yaml_avant": None,  # alléger la réponse API
        "yaml_apres": None,
    }


def traiter_acceptation(
    charge: dict[str, Any],
    *,
    par: str,
    mode: ModeAcceptation = "statut_seul",
    retirer_mention_a_confirmer: bool = False,
    proposition_id: int | None = None,
    sources: list[Any] | None = None,
) -> dict[str, Any]:
    """Orchestration selon le mode demandé par l'humain."""
    sug = SuggestionStructuree.depuis_charge(charge)
    base = {
        "mode": mode,
        "suggestion_structuree_presente": sug is not None,
        "retirer_mention_demande": retirer_mention_a_confirmer,
    }
    if mode == "statut_seul":
        patch_apercu = None
        if sug is not None:
            try:
                patch_apercu = preparer_patch_yaml(
                    charge, retirer_mention=retirer_mention_a_confirmer
                )
                # ne pas renvoyer les YAML complets en aperçu statut
                patch_apercu = {
                    k: v
                    for k, v in patch_apercu.items()
                    if k not in ("yaml_avant", "yaml_apres")
                }
            except ErreurAcceptation:
                patch_apercu = None
        return {
            **base,
            "yaml_modifie": False,
            "patch_propose": patch_apercu,
            "note": (
                "Statut workflow seulement — YAML intact. "
                "Passer mode=preparer_patch ou mode=appliquer pour un champ ciblé."
            ),
        }
    if mode == "preparer_patch":
        patch = preparer_patch_yaml(charge, retirer_mention=retirer_mention_a_confirmer)
        return {**base, "yaml_modifie": False, "patch": patch}
    if mode == "appliquer":
        if sug is None:
            raise ErreurAcceptation(
                "mode appliquer exige une suggestion_structuree "
                "(sinon mode=preparer_patch / statut_seul)"
            )
        if retirer_mention_a_confirmer and not sug.retirer_a_confirmer_autorise:
            raise ErreurAcceptation(
                "retrait a_confirmer refusé : la proposition ne l'autorise pas "
                "(contraste / risque). Utiliser preparer_patch ou visa séparé."
            )
        # Exiger au moins une mutation réelle
        try:
            apercu = preparer_patch_yaml(charge, retirer_mention=retirer_mention_a_confirmer)
        except ErreurAcceptation:
            raise
        if not apercu.get("operations"):
            raise ErreurAcceptation(
                "rien à écrire : définir suggestion_structuree.champ "
                "ou retirer_mention_a_confirmer=true (si autorisé). "
                "Sinon mode=preparer_patch."
            )
        resultat = appliquer_patch_yaml(
            charge,
            par=par,
            retirer_mention=retirer_mention_a_confirmer,
            proposition_id=proposition_id,
            sources=sources,
        )
        return {**base, "yaml_modifie": True, "resultat": resultat}
    raise ErreurAcceptation(f"mode inconnu : {mode}")
