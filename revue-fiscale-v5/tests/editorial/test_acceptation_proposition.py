"""Acceptation proposition → YAML contrôlé (champ unique / mention unique)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.editorial import acceptation_proposition as ap


@pytest.fixture()
def fiche_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ap, "RACINE_REFERENTIEL", tmp_path)
    monkeypatch.setattr(ap, "DIR_BACKUPS", tmp_path / ".backups_editorial")
    monkeypatch.setattr(ap, "JOURNAL", tmp_path / "journal_editorial_acceptations.jsonl")
    monkeypatch.setattr(ap, "RACINE", tmp_path)
    yaml_path = tmp_path / "BIC-TEST-ACCEPT.yaml"
    data = {
        "identifiant": "BIC-TEST-ACCEPT",
        "impot": "BIC",
        "reference_legale": "test",
        "date_effet": "2026-01-01",
        "niveau_risque": "moyen",
        "condition_declenchement": "solde(6582) > 0",
        "expression_resultat": "0",
        "a_confirmer": [
            "taux 2,5 % — a confirmer",
            "date d effet 01/01/2026",
        ],
    }
    yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return yaml_path


def _charge(**kwargs):
    base = {
        "rule_id": "BIC-TEST-ACCEPT",
        "entree_id": "BIC-TEST-ACCEPT#0",
        "suggestion_valeur": "0.025",
        "extrait_cgi": "double limite de 2,5 %",
        "suggestion_structuree": {
            "champ": None,
            "valeur": "0.025",
            "index_a_confirmer": 0,
            "entree_id": "BIC-TEST-ACCEPT#0",
            "retirer_a_confirmer_autorise": True,
            "extrait": "double limite de 2,5 %",
        },
    }
    base.update(kwargs)
    return base


def test_refus_ne_change_rien(fiche_tmp: Path):
    """Le module d'acceptation n'est pas appelé sur rejet — YAML intact.

    Ici on vérifie qu'un mode statut_seul sans appliquer laisse le fichier.
    """
    avant = fiche_tmp.read_text(encoding="utf-8")
    out = ap.traiter_acceptation(_charge(), par="test@2aaz.ci", mode="statut_seul")
    assert out["yaml_modifie"] is False
    assert fiche_tmp.read_text(encoding="utf-8") == avant


def test_preparer_patch_sans_ecriture(fiche_tmp: Path):
    avant = fiche_tmp.read_text(encoding="utf-8")
    out = ap.traiter_acceptation(
        _charge(),
        par="test@2aaz.ci",
        mode="preparer_patch",
        retirer_mention_a_confirmer=True,
    )
    assert out["yaml_modifie"] is False
    assert "taux 2,5 %" in out["patch"]["yaml_avant"]
    assert "taux 2,5 %" not in out["patch"]["yaml_apres"]
    assert fiche_tmp.read_text(encoding="utf-8") == avant


def test_appliquer_retire_seulement_la_mention_visee(fiche_tmp: Path):
    out = ap.traiter_acceptation(
        _charge(),
        par="fiscaliste@2aaz.ci",
        mode="appliquer",
        retirer_mention_a_confirmer=True,
        proposition_id=42,
    )
    assert out["yaml_modifie"] is True
    data = yaml.safe_load(fiche_tmp.read_text(encoding="utf-8"))
    assert data["a_confirmer"] == ["date d effet 01/01/2026"]
    assert data["date_effet"] == "2026-01-01"  # autres champs intacts
    assert (ap.DIR_BACKUPS).is_dir()
    assert ap.JOURNAL.is_file()
    journal = ap.JOURNAL.read_text(encoding="utf-8")
    assert "fiscaliste@2aaz.ci" in journal
    assert "retirer_a_confirmer" in journal


def test_appliquer_champ_uniquement_sans_purge(fiche_tmp: Path):
    charge = _charge(
        suggestion_structuree={
            "champ": "date_effet",
            "valeur": "2026-01-01",
            "index_a_confirmer": 0,
            "entree_id": "BIC-TEST-ACCEPT#0",
            "retirer_a_confirmer_autorise": False,
            "extrait": "…",
        }
    )
    out = ap.traiter_acceptation(
        charge, par="editeur@2aaz.ci", mode="appliquer", retirer_mention_a_confirmer=False
    )
    assert out["yaml_modifie"] is True
    data = yaml.safe_load(fiche_tmp.read_text(encoding="utf-8"))
    assert len(data["a_confirmer"]) == 2  # aucune purge
    assert data["date_effet"] == "2026-01-01"


def test_appliquer_autorise_sans_flag_ne_retire_pas(fiche_tmp: Path):
    """Autorisation catalogue ≠ retrait : sans flag humain, rien n'est écrit / retiré."""
    avant = yaml.safe_load(fiche_tmp.read_text(encoding="utf-8"))
    with pytest.raises(ap.ErreurAcceptation, match="rien à écrire"):
        ap.traiter_acceptation(
            _charge(
                suggestion_structuree={
                    "champ": None,
                    "valeur": "0.025",
                    "index_a_confirmer": 0,
                    "entree_id": "BIC-TEST-ACCEPT#0",
                    "retirer_a_confirmer_autorise": True,
                }
            ),
            par="editeur@2aaz.ci",
            mode="appliquer",
            retirer_mention_a_confirmer=False,
        )
    data = yaml.safe_load(fiche_tmp.read_text(encoding="utf-8"))
    assert data["a_confirmer"] == avant["a_confirmer"]


def test_preparer_patch_refuse_retrait_si_non_autorise(fiche_tmp: Path):
    charge = _charge(
        suggestion_structuree={
            "champ": None,
            "valeur": None,
            "index_a_confirmer": 0,
            "entree_id": "BIC-TEST-ACCEPT#0",
            "retirer_a_confirmer_autorise": False,
        }
    )
    avant = fiche_tmp.read_text(encoding="utf-8")
    with pytest.raises(ap.ErreurAcceptation, match="autorise pas"):
        ap.traiter_acceptation(
            charge,
            par="x@2aaz.ci",
            mode="preparer_patch",
            retirer_mention_a_confirmer=True,
        )
    assert fiche_tmp.read_text(encoding="utf-8") == avant


def test_rendre_csv_export_lecture_seule():
    from backend.editorial.inventaire_a_confirmer import (
        RACINE_REFERENTIEL,
        construire_inventaire,
        rendre_csv,
    )

    inventaire = construire_inventaire(RACINE_REFERENTIEL)
    csv = rendre_csv(inventaire)
    assert "identifiant;fichier;index" in csv.splitlines()[0]
    assert len(csv.splitlines()) >= 2


def test_retrait_refuse_si_non_autorise(fiche_tmp: Path):
    charge = _charge(
        suggestion_structuree={
            "champ": None,
            "valeur": None,
            "index_a_confirmer": 0,
            "entree_id": "BIC-TEST-ACCEPT#0",
            "retirer_a_confirmer_autorise": False,
        }
    )
    with pytest.raises(ap.ErreurAcceptation, match="autorise pas"):
        ap.traiter_acceptation(
            charge,
            par="x@2aaz.ci",
            mode="appliquer",
            retirer_mention_a_confirmer=True,
        )
    data = yaml.safe_load(fiche_tmp.read_text(encoding="utf-8"))
    assert len(data["a_confirmer"]) == 2
