"""Epinglage : mission sur v1 ignore la publication de v2."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from backend.editorial.publication import (
    charger_regle_yaml,
    creer_version_brouillon,
    publier_version,
)
from backend.moteur.service import executer_mission
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.missions import creer_mission
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

pytestmark = pytest.mark.db


def _regle(identifiant: str, resultat: str) -> dict:
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
        "resultat": resultat,
        "niveau_risque": "faible",
        "effets_croises": [],
        "a_confirmer": ["test"],
    }


def test_epinglage_stable_apres_nouvelle_publication(session):
    suffix = uuid.uuid4().hex[:8]
    lib_v1 = f"v-epinglage-v1-{suffix}"
    lib_v2 = f"v-epinglage-v2-{suffix}"
    regle_id = f"TST-PIN-{suffix.upper()}"

    # Versions distinctes : v1 resultat = solde - 1000 ; v2 = solde - 9999
    v1 = creer_version_brouillon(session, lib_v1)
    charger_regle_yaml(session, v1, _regle(regle_id, "solde(6582) - 1000"))
    publier_version(session, lib_v1, par="editeur")

    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Pin', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tid):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Pin') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
    effacer_contexte_tenant(session)

    mid = creer_mission(
        session,
        tid,
        contribuable_id=cid,
        exercice=2025,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )

    with contexte_tenant(session, tid):
        pin = session.execute(
            text("SELECT version_referentiel_id FROM mission WHERE id = :m"),
            {"m": mid},
        ).scalar_one()
    assert pin == v1

    lignes = [
        LigneBalance(compte="6582", libelle="Dons", debit=Decimal("5000"), credit=Decimal("0")),
        LigneBalance(compte="521", libelle="Banque", debit=Decimal("0"), credit=Decimal("5000")),
    ]
    assert fiabiliser_balance(session, tid, mid, lignes).statut == "ok"

    c1 = executer_mission(session, tid, mid, acteur="testeur", reponses={})
    declenchees_1 = [c for c in c1 if c.declenchee]
    assert len(declenchees_1) == 1
    assert declenchees_1[0].montant == Decimal("4000")  # 5000 - 1000

    # Publie v2 avec une formule differente
    v2 = creer_version_brouillon(session, lib_v2)
    charger_regle_yaml(session, v2, _regle(regle_id, "solde(6582) - 9999"))
    publier_version(session, lib_v2, par="editeur")

    # Re-execution : meme soldes → meme conclusions (toujours v1)
    c2 = executer_mission(session, tid, mid, acteur="testeur", reponses={})
    declenchees_2 = [c for c in c2 if c.declenchee]
    assert len(declenchees_2) == 1
    assert declenchees_2[0].montant == Decimal("4000")
    assert declenchees_2[0].regle_version_id == declenchees_1[0].regle_version_id
