"""Inventaire a_confirmer — lecture seule, sans purge fictive."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

from backend.editorial.inventaire_a_confirmer import (
    categoriser,
    classer_priorite,
    construire_inventaire,
    ecrire_artefacts,
    empreinte_a_confirmer,
    scanner_mentions,
)

RACINE = Path(__file__).resolve().parents[2]
REFERENTIEL = RACINE / "referentiel"


def test_inventaire_compte_au_moins_une_mention():
    mentions = scanner_mentions(REFERENTIEL)
    assert len(mentions) >= 1
    inventaire = construire_inventaire(REFERENTIEL)
    assert inventaire["total_mentions"] >= 1
    assert inventaire["total_regles_concernees"] >= 1
    assert sum(inventaire["comptes_par_categorie"].values()) == inventaire["total_mentions"]


def test_categoriser_priorites():
    assert categoriser("definition FRAIS_GENERAUX") == "agregat"
    assert categoriser("assiette 30 % — RESULTAT_AVANT_IMPOT a figer") == "agregat"
    assert categoriser("taux 2,5 % — verifier art. 18 G") == "taux"
    assert categoriser("plafond 200 000 000 FCFA") == "seuil"
    assert categoriser("date d effet 01/01/2026") == "date"
    assert categoriser("valeurs issues doc client 5 — a valider metier") == "autre"


def test_classer_priorite_editoriale():
    assert classer_priorite("taux 2,5 % — verifier art. 18 G") == "sourcable"
    assert classer_priorite("plafond 200 000 000 FCFA") == "sourcable"
    assert classer_priorite("date d effet 01/01/2026") == "sourcable"
    assert classer_priorite("comptes 622/628") == "sourcable"
    assert classer_priorite("definition FRAIS_GENERAUX") == "bloqueur"
    assert (
        classer_priorite("assiette 30 % — RESULTAT_AVANT_IMPOT a figer")
        == "bloqueur"
    )
    assert classer_priorite("perimetre exclusions 18 E 1°") == "bloqueur"
    assert (
        classer_priorite("valeurs issues doc client 5 — a valider metier")
        == "hors_perimetre"
    )


def test_inventaire_expose_priorites():
    inventaire = construire_inventaire(REFERENTIEL)
    assert set(inventaire["comptes_par_priorite"]) == {
        "sourcable",
        "bloqueur",
        "hors_perimetre",
    }
    assert sum(inventaire["comptes_par_priorite"].values()) == inventaire[
        "total_mentions"
    ]
    # Aucune purge fictive : les trois classes coexistent sur le dépôt réel.
    assert inventaire["comptes_par_priorite"]["hors_perimetre"] >= 1
    assert inventaire["comptes_par_priorite"]["sourcable"] >= 1
    for m in inventaire["mentions"]:
        assert m["priorite"] in ("sourcable", "bloqueur", "hors_perimetre")



def test_script_cli_ne_plante_pas(tmp_path: Path):
    """Le CLI s'exécute et produit MD + JSON sans erreur."""
    # Copie minimale d'un YAML réel pour ne pas dépendre d'écriture sur le dépôt.
    source = next(REFERENTIEL.glob("*.yaml"))
    (tmp_path / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.scripts.inventaire_a_confirmer",
            "--racine",
            str(tmp_path),
        ],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (tmp_path / "INVENTAIRE_A_CONFIRMER.md").is_file()
    assert (tmp_path / "file_validation_a_confirmer.json").is_file()
    assert "Mentions a_confirmer" in result.stdout


def test_aucune_purge_fictive_des_a_confirmer():
    """Garantit qu'on n'a pas retiré fictivement les a_confirmer des YAML métier.

    Empreinte = ensemble (identifiant, index, texte). Toute baisse du total
    ou changement d'empreinte hors régénération volontaire doit être revue.
    """
    mentions = scanner_mentions(REFERENTIEL)
    assert len(mentions) >= 1

    # Chaque YAML métier présent conserve sa clé a_confirmer non vide.
    vides = []
    for chemin in sorted(REFERENTIEL.glob("*.yaml")):
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        ac = data.get("a_confirmer")
        if not ac:
            vides.append(chemin.name)
    assert not vides, (
        "Règles sans a_confirmer (purge fictive interdite sans validation humaine) : "
        + ", ".join(vides)
    )

    empreinte = empreinte_a_confirmer(mentions)
    assert len(empreinte) == 64
    assert empreinte == hashlib.sha256(
        "\n".join(
            sorted(f"{m.identifiant}\t{m.index}\t{m.texte}" for m in mentions)
        ).encode("utf-8")
    ).hexdigest()


def test_ecrire_artefacts_sur_depot_ne_modifie_pas_les_yaml(tmp_path: Path):
    """Régression : l'écriture d'artefacts ne touche pas les fiches métier."""
    avant = {
        p.name: p.read_bytes()
        for p in REFERENTIEL.glob("*.yaml")
    }
    # Écrit dans un répertoire isolé pour ne pas polluer le dépôt pendant le test.
    for name, contenu in list(avant.items())[:3]:
        (tmp_path / name).write_bytes(contenu)
    ecrire_artefacts(tmp_path)
    apres = {
        p.name: p.read_bytes()
        for p in REFERENTIEL.glob("*.yaml")
    }
    assert avant == apres

def test_marquer_en_revue_ne_purge_pas_yaml(tmp_path: Path):
    """Workflow en_revue = overlay ; les a_confirmer YAML restent intacts."""
    from backend.editorial.inventaire_a_confirmer import (
        construire_file_validation,
        marquer_en_revue,
        remettre_en_attente,
        scanner_mentions,
    )

    mentions = scanner_mentions(REFERENTIEL)
    assert mentions
    m = mentions[0]
    eid = f"{m.identifiant}#{m.index}"
    wf_path = tmp_path / "workflow_a_confirmer.json"

    avant = empreinte_a_confirmer(mentions)

    res = marquer_en_revue(
        eid,
        note_editeur="note test workflow",
        revue_par="test@2aaz.ci",
        chemin=wf_path,
    )
    assert res["statut"] == "en_revue"
    assert res["yaml_a_confirmer_purge"] is False
    assert wf_path.is_file()

    file_val = construire_file_validation(workflow={"entrees": {eid: res}})
    entree = next(e for e in file_val["entrees"] if e["id"] == eid)
    assert entree["statut"] == "en_revue"
    assert entree["note_editeur"] == "note test workflow"

    apres = scanner_mentions(REFERENTIEL)
    assert empreinte_a_confirmer(apres) == avant
    yaml_path = REFERENTIEL / m.fichier
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data.get("a_confirmer")

    remettre_en_attente(eid, chemin=wf_path)
    wf2 = construire_file_validation(workflow={"entrees": {}})
    entree2 = next(e for e in wf2["entrees"] if e["id"] == eid)
    assert entree2["statut"] == "en_attente"

