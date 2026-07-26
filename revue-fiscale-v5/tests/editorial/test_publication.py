"""Publication editorial — avec base."""
import uuid

import pytest
from sqlalchemy import text

from backend.editorial.publication import (
    ErreurEditorial,
    charger_regle_yaml,
    creer_version_brouillon,
    publier_version,
)
from backend.referentiel.depot import lire_regles_version

pytestmark = pytest.mark.db


def _regle_synthetique(identifiant: str = "TST-SYN-01-DEMO") -> dict:
    """Expression synthetique — aucun taux legal affirme."""
    return {
        "identifiant": identifiant,
        "impot": "BIC",
        "reference_legale": "TEST SYNTHETIQUE — non CGI",
        "date_effet": "2026-01-01",
        "profils_applicables": ["reel"],
        "comptes_declencheurs": ["6582"],
        "nature": "permanente",
        "condition_declenchement": "solde(6582) > 0",
        "conditions_fond": "sans objet",
        "formule_plafonnement": "sans objet",
        "questions_generees": [],
        "resultat": "solde(6582) - 1000",
        "niveau_risque": "faible",
        "effets_croises": [],
        "a_confirmer": ["regle de test uniquement"],
    }


def test_creer_et_publier(session):
    libelle = f"v-test-pub-{uuid.uuid4().hex[:8]}"
    vid = creer_version_brouillon(session, libelle, note="test")
    assert vid > 0
    rv = charger_regle_yaml(
        session, vid, _regle_synthetique(f"TST-SYN-{uuid.uuid4().hex[:6].upper()}")
    )
    assert rv > 0
    publie = publier_version(session, libelle, par="testeur")
    assert publie == vid

    row = session.execute(
        text("SELECT publiee_le, publiee_par FROM version_referentiel WHERE id = :id"),
        {"id": vid},
    ).one()
    assert row.publiee_le is not None
    assert row.publiee_par == "testeur"

    regles = lire_regles_version(session, vid)
    assert len(regles) == 1


def test_publier_deux_fois_refuse(session):
    libelle = f"v-test-pub2-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, libelle)
    publier_version(session, libelle, par="a")
    with pytest.raises(ErreurEditorial, match="deja publiee"):
        publier_version(session, libelle, par="b")


def test_expression_invalide_refusee(session):
    libelle = f"v-test-pub3-{uuid.uuid4().hex[:8]}"
    vid = creer_version_brouillon(session, libelle)
    mauvaise = _regle_synthetique(f"TST-BAD-{uuid.uuid4().hex[:6].upper()}")
    mauvaise["condition_declenchement"] = "eval('hack')"
    with pytest.raises(ErreurEditorial):
        charger_regle_yaml(session, vid, mauvaise)
