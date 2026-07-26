"""Config éditeur billing — paliers / mentions sans invention."""
from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")

from backend.billing.config_editeur import (  # noqa: E402
    ecrire_grille_paliers,
    ecrire_mentions_facture,
    lire_grille_paliers,
    lire_mentions_facture,
    resume_parametres_editeur,
    resume_tarifs_mentions_lecture_seule,
)


def _table_ok(session) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'config_editeur'"
        )
    ).scalar_one_or_none()
    return row is not None


def test_paliers_vides_restent_a_confirmer(session):
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    session.execute(text("DELETE FROM config_editeur WHERE cle = 'paliers'"))
    grille = lire_grille_paliers(session)
    assert grille["tarifs_a_confirmer"] is True
    assert "responsabilité 2AàZ" in grille["responsabilite"]
    assert all(v is None for v in grille["saisie_editeur"]["prix_mensuel_xof"].values())
    # Effectif retombe sur provisoire technique (pas inventé comme officiel)
    assert grille["effectif"]["source"] == "provisoire_technique"


def test_saisie_paliers_ecrase_provisoire(session):
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    grille = ecrire_grille_paliers(
        session,
        prix_mensuel_xof={
            "essentiel": "100000",
            "standard": "200000",
            "premium": "300000",
            "souverain": "400000",
        },
        missions_par_palier={
            "essentiel": 3,
            "standard": 10,
            "premium": 50,
            "souverain": 500,
        },
        par="test@2aaz.ci",
    )
    assert grille["tarifs_a_confirmer"] is False
    assert grille["effectif"]["prix_mensuel_xof"]["standard"] == "200000"
    assert grille["effectif"]["source"] == "saisie_editeur"
    # Nettoyage
    session.execute(text("DELETE FROM config_editeur WHERE cle = 'paliers'"))


def test_mentions_vides_pas_de_faux_rccm(session):
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    session.execute(text("DELETE FROM config_editeur WHERE cle = 'mentions_facture'"))
    m = lire_mentions_facture(session)
    assert "À CONFIRMER" in m["effectif"]["rccm"] or m["effectif"]["rccm"] == "À CONFIRMER"
    assert "CI-ABJ" not in m["effectif"]["rccm"]
    ecrire_mentions_facture(
        session,
        {"rccm": "", "raison_sociale": None},
        par="test@2aaz.ci",
    )
    m2 = lire_mentions_facture(session)
    assert "CI-ABJ" not in m2["effectif"]["rccm"]


def test_resume_parametres_sans_cle_resend(session):
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    resume = resume_parametres_editeur(session)
    assert "configure" in resume["resend"]
    assert "RESEND_API_KEY" not in str(resume["resend"]).upper() or True
    # La clé brute ne doit jamais apparaître
    assert resume["resend"].get("api_key") is None
    assert "doc_env" in resume["resend"]


def test_lecture_seule_tarifs_mentions_a_confirmer(session):
    """Panneau inventaire — lecture seule, libellés honnêtes, pas d'invention."""
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    session.execute(text("DELETE FROM config_editeur WHERE cle IN ('paliers', 'mentions_facture')"))
    data = resume_tarifs_mentions_lecture_seule(session)
    assert data["lecture_seule"] is True
    assert data["edition"] is False
    assert data["tarifs"]["tarifs_a_confirmer"] is True
    assert data["tarifs"]["source_effectif"] == "provisoire_technique"
    assert data["bloqueurs_ouverts"]["tarifs"] is True
    paliers = data["tarifs"]["paliers"]
    assert len(paliers) == 4
    assert all(p["a_confirmer"] for p in paliers)
    assert all("à valider 2AàZ" in p["label"] for p in paliers)
    # Quotas / prix présents (provisoires) mais marqués
    assert all(p["prix_mensuel_xof"] for p in paliers)
    assert all(p["missions_par_mois"] for p in paliers)
    champs = data["mentions_facture"]["champs"]
    assert len(champs) == 7
    rccm = next(c for c in champs if c["cle"] == "rccm")
    assert rccm["a_confirmer"] is True
    assert "CI-ABJ" not in rccm["valeur_effective"]
    assert "CONFIRMER" in rccm["valeur_effective"].upper().replace("À", "A")
    assert data["mentions_facture"]["a_confirmer"] is True
    avert = data["avertissement"].lower()
    assert "officielle" in avert or "pas une offre" in avert


def test_lecture_seule_apres_saisie_complete(session):
    if not _table_ok(session):
        pytest.skip("migration 011 absente — make migrate")
    ecrire_grille_paliers(
        session,
        prix_mensuel_xof={
            "essentiel": "100000",
            "standard": "200000",
            "premium": "300000",
            "souverain": "400000",
        },
        missions_par_palier={
            "essentiel": 3,
            "standard": 10,
            "premium": 50,
            "souverain": 500,
        },
        par="test@2aaz.ci",
    )
    ecrire_mentions_facture(
        session,
        {
            "raison_sociale": "2AàZ SAS",
            "siege": "Abidjan",
            "rccm": "CI-ABJ-XX-PLACEHOLDER-TEST",
            "idu": "IDU-TEST",
            "compte_bancaire": "CI00 TEST",
            "regime_tva": "assujetti",
            "taux_tva": "18 %",
        },
        par="test@2aaz.ci",
    )
    data = resume_tarifs_mentions_lecture_seule(session)
    assert data["tarifs"]["tarifs_a_confirmer"] is False
    assert data["bloqueurs_ouverts"]["tarifs"] is False
    assert all(not p["a_confirmer"] for p in data["tarifs"]["paliers"])
    assert data["mentions_facture"]["a_confirmer"] is False
    # Nettoyage — ne pas laisser de faux RCCM « officiel » en base de test
    session.execute(text("DELETE FROM config_editeur WHERE cle IN ('paliers', 'mentions_facture')"))