"""Inventaire des mentions ``a_confirmer`` du référentiel YAML.

Lecture seule. Ne retire rien, n'invente aucun taux / article / date.
La purge reste un circuit éditorial 2AàZ (humain valide).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

Categorie = Literal["date", "taux", "seuil", "agregat", "autre"]
PrioriteEditoriale = Literal["sourcable", "bloqueur", "hors_perimetre"]

CATEGORIES: tuple[Categorie, ...] = ("date", "taux", "seuil", "agregat", "autre")
PRIORITES: tuple[PrioriteEditoriale, ...] = (
    "sourcable",
    "bloqueur",
    "hors_perimetre",
)

LIBELLES_PRIORITE: dict[PrioriteEditoriale, str] = {
    "sourcable": (
        "Déjà sourçable — chemin CGI / annexe clair ; "
        "validation humaine 2AàZ requise avant purge"
    ),
    "bloqueur": (
        "Bloqueur — définition / périmètre à figer avant certification "
        "(pas un simple lookup de montant)"
    ),
    "hors_perimetre": (
        "Hors périmètre immédiat — note de provenance seed / validation métier "
        "en lot, pas une purge fiscale prioritaire"
    ),
}

RACINE_PROJET = Path(__file__).resolve().parents[2]
RACINE_REFERENTIEL = RACINE_PROJET / "referentiel"
CHEMIN_INVENTAIRE_MD = RACINE_REFERENTIEL / "INVENTAIRE_A_CONFIRMER.md"
CHEMIN_FILE_VALIDATION = RACINE_REFERENTIEL / "file_validation_a_confirmer.json"
# Overlay workflow éditeur — ne touche jamais les YAML ``a_confirmer``.
CHEMIN_WORKFLOW = RACINE_REFERENTIEL / "workflow_a_confirmer.json"

StatutWorkflow = Literal["en_attente", "en_revue"]
STATUTS_WORKFLOW: tuple[StatutWorkflow, ...] = ("en_attente", "en_revue")

_RE_AGREGAT = re.compile(
    r"FRAIS_GENERAUX|RESULTAT_AVANT_IMPOT|\bagregat\b|assiette",
    re.IGNORECASE,
)
_RE_TAUX = re.compile(r"\btaux\b|%|BCEAO", re.IGNORECASE)
_RE_SEUIL = re.compile(
    r"\bplafond\b|\bseuil|\bseuils\b|FCFA|\bMd\b",
    re.IGNORECASE,
)
_RE_DATE = re.compile(r"\bdate\b|\beffet\b|\d{2}/\d{2}/\d{4}", re.IGNORECASE)
_RE_DOC_CLIENT = re.compile(r"docs?\s+client", re.IGNORECASE)
_RE_BLOQUEUR_SEMANTIQUE = re.compile(
    r"perimetre|limites\s*\(|fraction|definition|a\s+figer",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MentionAConfirmer:
    """Une entrée de la liste ``a_confirmer`` d'une fiche YAML."""

    identifiant: str
    fichier: str
    index: int
    texte: str
    categorie: Categorie
    priorite: PrioriteEditoriale
    impot: str | None
    reference_legale: str | None


def categoriser(texte: str) -> Categorie:
    """Attribue une catégorie primaire (priorité : agrégat > taux > seuil > date > autre).

    Heuristique de tri éditorial uniquement — ne certifie aucun droit positif.
    """
    t = texte.strip()
    if _RE_AGREGAT.search(t):
        return "agregat"
    if _RE_TAUX.search(t):
        return "taux"
    if _RE_SEUIL.search(t):
        return "seuil"
    if _RE_DATE.search(t):
        return "date"
    return "autre"


def classer_priorite(texte: str, categorie: Categorie | None = None) -> PrioriteEditoriale:
    """Classe éditoriale exclusive pour prioriser la file de validation.

    - ``hors_perimetre`` : provenance seed (« doc client ») — hors sprint fiscal.
    - ``bloqueur`` : agrégats / périmètres / définitions à figer (pas un lookup).
    - ``sourcable`` : taux, seuil, date, comptes — chemin CGI/annexe/plan comptable
      clair ; **ne purge pas** sans validation humaine sourcée.

    N'affirme aucun droit positif. Ne retire aucun ``a_confirmer``.
    """
    t = texte.strip()
    cat = categorie if categorie is not None else categoriser(t)
    if _RE_DOC_CLIENT.search(t):
        return "hors_perimetre"
    if cat == "agregat" or _RE_BLOQUEUR_SEMANTIQUE.search(t):
        return "bloqueur"
    if cat in ("taux", "seuil", "date"):
        return "sourcable"
    if re.search(r"\bcomptes?\b", t, re.IGNORECASE):
        return "sourcable"
    return "bloqueur"


def lister_yaml(racine: Path | None = None) -> list[Path]:
    """Fiches métier à la racine de ``referentiel/`` (pas les sous-dossiers)."""
    base = racine or RACINE_REFERENTIEL
    return sorted(base.glob("*.yaml"))


def scanner_mentions(racine: Path | None = None) -> list[MentionAConfirmer]:
    """Parcourt les YAML et extrait chaque item ``a_confirmer``."""
    mentions: list[MentionAConfirmer] = []
    for chemin in lister_yaml(racine):
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        brut = data.get("a_confirmer") or []
        if isinstance(brut, str):
            brut = [brut]
        if not isinstance(brut, list):
            continue
        identifiant = str(data.get("identifiant") or chemin.stem)
        impot = data.get("impot")
        ref = data.get("reference_legale")
        for i, item in enumerate(brut):
            texte = str(item).strip()
            if not texte:
                continue
            cat = categoriser(texte)
            mentions.append(
                MentionAConfirmer(
                    identifiant=identifiant,
                    fichier=chemin.name,
                    index=i,
                    texte=texte,
                    categorie=cat,
                    priorite=classer_priorite(texte, cat),
                    impot=str(impot) if impot is not None else None,
                    reference_legale=str(ref) if ref is not None else None,
                )
            )
    return mentions


def empreinte_a_confirmer(mentions: list[MentionAConfirmer] | None = None) -> str:
    """Empreinte stable des paires (identifiant, texte) — détecte une purge fictive."""
    items = mentions if mentions is not None else scanner_mentions()
    lignes = sorted(f"{m.identifiant}\t{m.index}\t{m.texte}" for m in items)
    digest = hashlib.sha256("\n".join(lignes).encode("utf-8")).hexdigest()
    return digest


def construire_inventaire(racine: Path | None = None) -> dict[str, Any]:
    """Structure JSON de l'inventaire (lecture seule)."""
    mentions = scanner_mentions(racine)
    par_categorie: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
    par_priorite: dict[str, list[dict[str, Any]]] = {p: [] for p in PRIORITES}
    par_regle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in mentions:
        d = asdict(m)
        par_categorie[m.categorie].append(d)
        par_priorite[m.priorite].append(d)
        par_regle[m.identifiant].append(d)

    themes = {
        "dates": par_categorie["date"],
        "taux_et_seuils": par_categorie["taux"] + par_categorie["seuil"],
        "agregats_FRAIS_GENERAUX_RESULTAT_AVANT_IMPOT": par_categorie["agregat"],
        "autre": par_categorie["autre"],
    }

    return {
        "genere_le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "avertissement": (
            "Inventaire généré — ne constitue pas une validation fiscale. "
            "Purge = circuit éditorial 2AàZ (humain), jamais seed auto. "
            "Aucune mention n'est retirée sans source CGI CI 2026 certaine. "
            "a_confirmer et en_attente_corpus ne bloquent pas le runtime SaaS."
        ),
        "note_sources": (
            "Annexe fiscale 2026 (LF 2025-987) liée dans corpus_sources/ : "
            "texte extractible, aucune occurrence « 18 G » ; le 2,5 % trouvé "
            "est la taxe touristique ≠ dons. CGI intégral absent → "
            "statut_editorial=en_attente_corpus (déposer corpus_sources/CGI-CI-2026.pdf) "
            "— 0 purge auto ; bloque_runtime=non. "
            "Fiche session : docs/15-session-fiscaliste-7-seuils.md."
        ),
        "total_mentions": len(mentions),
        "total_regles_concernees": len(par_regle),
        "comptes_par_categorie": {c: len(par_categorie[c]) for c in CATEGORIES},
        "comptes_par_priorite": {p: len(par_priorite[p]) for p in PRIORITES},
        "libelles_priorite": dict(LIBELLES_PRIORITE),
        "empreinte": empreinte_a_confirmer(mentions),
        "par_categorie": par_categorie,
        "par_priorite": par_priorite,
        "par_theme": themes,
        "par_regle": dict(sorted(par_regle.items())),
        "mentions": [asdict(m) for m in mentions],
    }


def rendre_markdown(inventaire: dict[str, Any]) -> str:
    """Markdown humain pour ``referentiel/INVENTAIRE_A_CONFIRMER.md``."""
    lignes: list[str] = [
        "# Inventaire `a_confirmer` — généré",
        "",
        "> **Ne pas éditer à la main.** Régénérer via "
        "`python -m backend.scripts.inventaire_a_confirmer`.",
        ">",
        f"> {inventaire['avertissement']}",
        "",
        f"- Généré le : `{inventaire['genere_le']}`",
        f"- Total mentions : **{inventaire['total_mentions']}**",
        f"- Règles concernées : **{inventaire['total_regles_concernees']}**",
        f"- Empreinte : `{inventaire['empreinte']}`",
        "",
        "## Comptes par catégorie",
        "",
        "| Catégorie | Nb |",
        "|---|---:|",
    ]
    for cat, n in inventaire["comptes_par_categorie"].items():
        lignes.append(f"| `{cat}` | {n} |")

    lignes.extend(
        [
            "",
            "## Priorité éditoriale",
            "",
            "| Priorité | Nb | Sens |",
            "|---|---:|---|",
        ]
    )
    for p in PRIORITES:
        n = inventaire["comptes_par_priorite"][p]
        lignes.append(f"| `{p}` | {n} | {LIBELLES_PRIORITE[p]} |")

    if inventaire.get("note_sources"):
        lignes.extend(["", f"> **Sources :** {inventaire['note_sources']}", ""])

    lignes.extend(["", "## Par priorité", ""])
    for p in PRIORITES:
        items = inventaire["par_priorite"][p]
        lignes.append(f"### `{p}` ({len(items)})")
        lignes.append("")
        if not items:
            lignes.append("_Aucune mention._")
            lignes.append("")
            continue
        for m in items:
            lignes.append(
                f"- `{m['identifiant']}` [{m['categorie']}] — {m['texte']}"
            )
        lignes.append("")

    lignes.extend(["", "## Par thème", ""])
    libelles_theme = {
        "dates": "Dates",
        "taux_et_seuils": "Taux et seuils",
        "agregats_FRAIS_GENERAUX_RESULTAT_AVANT_IMPOT": (
            "Agrégats (FRAIS_GENERAUX / RESULTAT_AVANT_IMPOT / assiette)"
        ),
        "autre": "Autre (sources docs, périmètre, comptes…)",
    }
    for cle, titre in libelles_theme.items():
        items = inventaire["par_theme"][cle]
        lignes.append(f"### {titre} ({len(items)})")
        lignes.append("")
        if not items:
            lignes.append("_Aucune mention._")
            lignes.append("")
            continue
        for m in items:
            lignes.append(
                f"- `{m['identifiant']}` [{m['categorie']}/{m['priorite']}] "
                f"— {m['texte']}"
            )
        lignes.append("")

    lignes.extend(["## Par règle", ""])
    for identifiant, items in inventaire["par_regle"].items():
        lignes.append(f"### `{identifiant}` ({len(items)})")
        lignes.append("")
        for m in items:
            lignes.append(
                f"- [{m['categorie']}/{m['priorite']}] {m['texte']}"
            )
        lignes.append("")

    lignes.extend(
        [
            "---",
            "",
            "Purge = circuit éditorial 2AàZ, pas seed auto. "
            "L'IA propose, l'humain valide. Aucun taux/article inventé ici.",
            "",
        ]
    )
    return "\n".join(lignes)


def charger_workflow(chemin: Path | None = None) -> dict[str, Any]:
    """Charge l'overlay workflow (``en_revue`` / notes) — jamais de purge YAML."""
    path = chemin or CHEMIN_WORKFLOW
    if not path.is_file():
        return {
            "avertissement": (
                "Workflow éditeur — statut en_revue / note uniquement. "
                "Ne retire aucun a_confirmer des YAML."
            ),
            "entrees": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"avertissement": "", "entrees": {}}
    entrees = data.get("entrees") or {}
    if not isinstance(entrees, dict):
        entrees = {}
    return {
        "avertissement": str(
            data.get("avertissement")
            or "Workflow éditeur — ne purge pas les YAML a_confirmer."
        ),
        "entrees": entrees,
    }


def ecrire_workflow(workflow: dict[str, Any], chemin: Path | None = None) -> Path:
    """Persiste l'overlay workflow (domaine éditorial, hors YAML règles)."""
    path = chemin or CHEMIN_WORKFLOW
    payload = {
        "avertissement": workflow.get("avertissement")
        or (
            "Workflow éditeur — statut en_revue / note uniquement. "
            "Ne retire aucun a_confirmer des YAML."
        ),
        "maj_le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entrees": workflow.get("entrees") or {},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def marquer_en_revue(
    entree_id: str,
    *,
    note_editeur: str | None = None,
    revue_par: str | None = None,
    chemin: Path | None = None,
) -> dict[str, Any]:
    """Passe une entrée en ``en_revue`` (workflow) sans toucher aux YAML.

    N'autorise pas ``valide`` / purge. Le marqueur ``a_confirmer`` reste dans
    le référentiel jusqu'à validation humaine sourcée hors de cet endpoint.
    """
    eid = (entree_id or "").strip()
    if not eid or "#" not in eid:
        raise ValueError("entree_id invalide (attendu IDENTIFIANT#index)")
    # Vérifie que l'entrée existe encore dans l'inventaire courant
    ids_connus = {
        f"{m.identifiant}#{m.index}" for m in scanner_mentions()
    }
    if eid not in ids_connus:
        raise ValueError(f"entree introuvable dans l'inventaire : {eid}")

    wf = charger_workflow(chemin)
    entrees = dict(wf.get("entrees") or {})
    prev = entrees.get(eid) if isinstance(entrees.get(eid), dict) else {}
    entrees[eid] = {
        "statut": "en_revue",
        "note_editeur": (
            (note_editeur if note_editeur is not None else prev.get("note_editeur"))
            or ""
        ).strip()
        or None,
        "revue_par": (revue_par or prev.get("revue_par") or "").strip() or None,
        "revue_le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    wf["entrees"] = entrees
    ecrire_workflow(wf, chemin)
    return {"id": eid, **entrees[eid], "yaml_a_confirmer_purge": False}


def remettre_en_attente(
    entree_id: str,
    *,
    chemin: Path | None = None,
) -> dict[str, Any]:
    """Retire l'overlay ``en_revue`` — l'entrée redevient en_attente (défaut)."""
    eid = (entree_id or "").strip()
    if not eid:
        raise ValueError("entree_id invalide")
    wf = charger_workflow(chemin)
    entrees = dict(wf.get("entrees") or {})
    entrees.pop(eid, None)
    wf["entrees"] = entrees
    ecrire_workflow(wf, chemin)
    return {"id": eid, "statut": "en_attente", "yaml_a_confirmer_purge": False}


def construire_file_validation(
    inventaire: dict[str, Any] | None = None,
    *,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """File de validation — statut workflow fusionné (défaut ``en_attente``)."""
    inv = inventaire or construire_inventaire()
    wf = workflow if workflow is not None else charger_workflow()
    overlay = wf.get("entrees") or {}
    entrees = []
    comptes_statut: dict[str, int] = dict.fromkeys(STATUTS_WORKFLOW, 0)
    for m in inv["mentions"]:
        eid = f"{m['identifiant']}#{m['index']}"
        ov = overlay.get(eid) if isinstance(overlay.get(eid), dict) else {}
        statut_brut = str(ov.get("statut") or "en_attente")
        statut: StatutWorkflow = (
            "en_revue" if statut_brut == "en_revue" else "en_attente"
        )
        comptes_statut[statut] = comptes_statut.get(statut, 0) + 1
        entrees.append(
            {
                "id": eid,
                "identifiant": m["identifiant"],
                "fichier": m["fichier"],
                "index": m["index"],
                "texte": m["texte"],
                "categorie": m["categorie"],
                "priorite": m["priorite"],
                "impot": m.get("impot"),
                "reference_legale": m.get("reference_legale"),
                "statut": statut,
                "note_editeur": ov.get("note_editeur"),
                "revue_par": ov.get("revue_par"),
                "revue_le": ov.get("revue_le"),
            }
        )
    return {
        "genere_le": inv["genere_le"],
        "avertissement": (
            "File éditoriale — workflow en_revue / note uniquement. "
            "Le retrait YAML a_confirmer est un acte humain 2AàZ sourcé "
            "(jamais via cet overlay)."
        ),
        "total": len(entrees),
        "comptes_par_priorite": inv["comptes_par_priorite"],
        "comptes_par_statut": comptes_statut,
        "empreinte": inv["empreinte"],
        "entrees": entrees,
    }


def rendre_csv(inventaire: dict[str, Any]) -> str:
    """Export CSV checklist fiscaliste — lecture seule, aucune purge."""
    entetes = [
        "identifiant",
        "fichier",
        "index",
        "categorie",
        "priorite",
        "texte",
    ]
    lignes = [";".join(entetes)]
    for m in inventaire.get("mentions") or []:
        cellules = [
            str(m.get("identifiant") or ""),
            str(m.get("fichier") or ""),
            str(m.get("index") if m.get("index") is not None else ""),
            str(m.get("categorie") or ""),
            str(m.get("priorite") or ""),
            str(m.get("texte") or "").replace(";", ",").replace("\n", " "),
        ]
        lignes.append(";".join(cellules))
    return "\n".join(lignes) + "\n"


def ecrire_artefacts(
    racine: Path | None = None,
    *,
    ecrire_md: bool = True,
    ecrire_file: bool = True,
    ecrire_csv: bool = True,
) -> dict[str, Any]:
    """Génère inventaire + fichiers Markdown / JSON / CSV sous ``referentiel/``."""
    base = racine or RACINE_REFERENTIEL
    inventaire = construire_inventaire(base)
    chemins: dict[str, str] = {}
    if ecrire_md:
        md_path = base / "INVENTAIRE_A_CONFIRMER.md"
        md_path.write_text(rendre_markdown(inventaire), encoding="utf-8")
        chemins["markdown"] = str(md_path)
    if ecrire_file:
        file_path = base / "file_validation_a_confirmer.json"
        file_path.write_text(
            json.dumps(
                construire_file_validation(inventaire),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        chemins["file_validation"] = str(file_path)
    if ecrire_csv:
        csv_path = base / "INVENTAIRE_A_CONFIRMER.csv"
        csv_path.write_text(rendre_csv(inventaire), encoding="utf-8")
        chemins["csv"] = str(csv_path)
    inventaire["chemins_ecrits"] = chemins
    return inventaire


def charger_file_validation(chemin: Path | None = None) -> dict[str, Any]:
    """Charge la file JSON ; la régénère en mémoire si le fichier est absent."""
    path = chemin or CHEMIN_FILE_VALIDATION
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return construire_file_validation()
