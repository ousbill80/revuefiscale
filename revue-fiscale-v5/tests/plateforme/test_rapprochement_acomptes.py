"""Rapprochement acomptes IS versés / IS théorique — vue consultative."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.rapprochement_acomptes import (
    MOTIF_MINIMUM_NON_CALCULABLE,
    NOTE_RAPPROCHEMENT_ACOMPTES,
    STATUT_EQUILIBRE,
    STATUT_EXCEDENT,
    STATUT_INDISPONIBLE,
    STATUT_SOLDE_A_PAYER,
    construire_rapprochement,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _passage(is_theorique: str, imf_possible: bool = False) -> dict:
    return {
        "disponible": True,
        "is_theorique": is_theorique,
        "imf": {"possible": imf_possible, "motif": None},
    }


def _acompte(nature: str, date_v: str, montant: str) -> dict:
    return {
        "id": 1,
        "nature": nature,
        "libelle_nature": nature,
        "date_versement": date_v,
        "montant": montant,
        "reference_quittance": None,
    }


def test_indisponible_sans_passage():
    # Projection du tableau de passage en échec → vue indisponible,
    # les acomptes saisis restent listés et totalisés.
    vue = construire_rapprochement(
        None, [_acompte("acompte_is", "2025-04-10", "1000000")]
    )
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["is_theorique"] is None
    assert Decimal(vue["totaux_saisis"]["total"]) == Decimal("1000000")
    assert len(vue["acomptes"]) == 1


def test_indisponible_passage_non_chiffrable():
    vue = construire_rapprochement(
        {"disponible": False, "is_theorique": "0", "imf": {}}, []
    )
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["solde_indicatif"]["montant"] == "0"


def test_solde_a_payer_indicatif():
    vue = construire_rapprochement(
        _passage("3750000"),
        [_acompte("acompte_is", "2025-04-10", "1000000")],
    )
    assert vue["disponible"] is True
    assert vue["statut"] == STATUT_SOLDE_A_PAYER
    assert Decimal(vue["solde_indicatif"]["montant"]) == Decimal("2750000")
    assert Decimal(vue["solde_indicatif"]["solde_signe"]) == Decimal(
        "2750000"
    )


def test_excedent_indicatif_credit_impot():
    # Acomptes saisis > IS théorique → crédit d'impôt indicatif /
    # excédent à faire valoir (formulation non accusatoire).
    vue = construire_rapprochement(
        _passage("1000000"),
        [_acompte("acompte_is", "2025-04-10", "6000000")],
    )
    assert vue["statut"] == STATUT_EXCEDENT
    assert Decimal(vue["solde_indicatif"]["montant"]) == Decimal("5000000")
    assert Decimal(vue["solde_indicatif"]["solde_signe"]) == Decimal(
        "-5000000"
    )
    assert "Crédit d'impôt indicatif" in vue["solde_indicatif"]["libelle"]
    assert "excédent à faire valoir" in vue["solde_indicatif"]["libelle"]


def test_equilibre_indicatif():
    vue = construire_rapprochement(
        _passage("2000000"),
        [_acompte("acompte_is", "2025-04-10", "2000000")],
    )
    assert vue["statut"] == STATUT_EQUILIBRE
    assert Decimal(vue["solde_indicatif"]["montant"]) == Decimal("0")


def test_acomptes_absents_valent_zero():
    # Aucun acompte saisi : total 0, solde = IS théorique entier.
    vue = construire_rapprochement(_passage("5000000"), [])
    assert vue["statut"] == STATUT_SOLDE_A_PAYER
    assert Decimal(vue["totaux_saisis"]["total"]) == Decimal("0")
    assert Decimal(vue["solde_indicatif"]["montant"]) == Decimal("5000000")
    assert vue["synthese"]["nb_versements"] == 0


def test_totaux_par_nature_toutes_cles_presentes():
    vue = construire_rapprochement(
        _passage("1000000"),
        [
            _acompte("acompte_is", "2025-04-10", "300000"),
            _acompte("retenue_source", "2025-05-10", "200000"),
        ],
    )
    totaux = vue["totaux_saisis"]
    assert set(totaux) == {
        "acompte_is", "retenue_source", "credit_reporte", "total",
    }
    assert Decimal(totaux["acompte_is"]) == Decimal("300000")
    assert Decimal(totaux["retenue_source"]) == Decimal("200000")
    assert Decimal(totaux["credit_reporte"]) == Decimal("0")
    assert Decimal(totaux["total"]) == Decimal("500000")


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "is_theorique", "is_source", "acomptes",
        "totaux_saisis", "solde_indicatif", "approximation",
        "minimum_perception", "statut", "synthese", "note",
        "references",
    }
    for vue in (
        construire_rapprochement(None, []),
        construire_rapprochement(
            _passage("100"),
            [_acompte("acompte_is", "2025-01-01", "50")],
        ),
    ):
        assert cles <= set(vue)
        assert vue["note"] == NOTE_RAPPROCHEMENT_ACOMPTES
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]
        assert vue["approximation"] is True
        assert vue["is_source"] == "resultat_fiscal_theorique"


def test_montants_serialises_en_str():
    vue = construire_rapprochement(
        _passage("3750000"),
        [
            {
                "id": 2,
                "nature": "acompte_is",
                "libelle_nature": "Acomptes IS versés",
                "date_versement": "2025-04-10",
                "montant": Decimal("1000000.00"),
                "reference_quittance": "Q-001",
            }
        ],
    )
    assert isinstance(vue["is_theorique"], str)
    assert isinstance(vue["totaux_saisis"]["total"], str)
    assert isinstance(vue["solde_indicatif"]["montant"], str)
    assert isinstance(vue["solde_indicatif"]["solde_signe"], str)
    for ligne in vue["acomptes"]:
        assert isinstance(ligne["montant"], str)


def test_minimum_perception_jamais_calculable_et_imf_relaye():
    # Le minimum de perception n'est JAMAIS calculé (motif explicite) ;
    # le signal IMF du tableau de passage est relayé tel quel.
    vue_sans = construire_rapprochement(_passage("100", False), [])
    vue_avec = construire_rapprochement(_passage("100", True), [])
    for vue in (vue_sans, vue_avec):
        mp = vue["minimum_perception"]
        assert mp["calculable"] is False
        assert mp["motif"] == MOTIF_MINIMUM_NON_CALCULABLE
    assert vue_sans["minimum_perception"]["imf_possible_signale"] is False
    assert vue_avec["minimum_perception"]["imf_possible_signale"] is True


def test_note_approximation_documentee_et_non_accusatoire():
    assert "consultati" in NOTE_RAPPROCHEMENT_ACOMPTES
    assert "APPROXIMATION ASSUMÉE" in NOTE_RAPPROCHEMENT_ACOMPTES
    assert "quittances" in NOTE_RAPPROCHEMENT_ACOMPTES
    assert "aucun recalcul" in NOTE_RAPPROCHEMENT_ACOMPTES
    assert "décide" in NOTE_RAPPROCHEMENT_ACOMPTES
    # Jamais accusatoire : un écart s'explique, jamais une conclusion.
    assert "à expliquer" in NOTE_RAPPROCHEMENT_ACOMPTES
    assert "jamais une conclusion" in NOTE_RAPPROCHEMENT_ACOMPTES


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-rapacptes-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="rapprochement acomptes")
    publier_version(session, lib, "rapacptes@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rapacptes.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RapprochementAcomptes {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _contribuable(session, tenant_id: int, nom: str) -> int:
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
    return int(cid)


def _mission(session, tenant_id: int, contribuable_id: int,
             exercice: int = 2025) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
    return int(mid)


def _solde(session, tenant_id: int, mission_id: int, compte: str,
           libelle: str, debit: str, credit: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO solde_compte (tenant_id, mission_id, "
                "compte, libelle, debit, credit) "
                "VALUES (:t, :m, :c, :l, :d, :cr)"
            ),
            {"t": tenant_id, "m": mission_id, "c": compte, "l": libelle,
             "d": debit, "cr": credit},
        )


def _saisir_acompte(session, tenant_id: int, mission_id: int,
                    montant: str, date_v: str = "2025-04-10") -> None:
    from backend.plateforme.acomptes import saisir_acompte

    saisir_acompte(
        session,
        tenant_id,
        mission_id,
        "acompte_is",
        montant,
        acteur="rapacptes@test.ci",
        date_versement=date_v,
    )


def _client_connecte(email: str):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/rapprochement-acomptes"


def test_api_solde_a_payer_indicatif(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RapAcptes FICTIVE")
    mid = _mission(session, tid, cid, exercice=2025)
    # Produits 20 M - charges 5 M : résultat fiscal 15 M → IS 3 750 000.
    _solde(session, tid, mid, "701", "Ventes FICTIVES", "0", "20000000")
    _solde(session, tid, mid, "601", "Achats FICTIFS", "5000000", "0")
    _saisir_acompte(session, tid, mid, "1000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["statut"] == "solde_a_payer_indicatif"
    assert corps["approximation"] is True
    assert Decimal(corps["is_theorique"]) == Decimal("3750000")
    assert Decimal(corps["totaux_saisis"]["total"]) == Decimal("1000000")
    assert Decimal(corps["solde_indicatif"]["montant"]) == Decimal(
        "2750000"
    )
    assert corps["minimum_perception"]["calculable"] is False
    assert corps["synthese"]["nb_versements"] == 1
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_excedent_indicatif(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RapAcptes Exc FICTIVE")
    mid = _mission(session, tid, cid, exercice=2025)
    # Résultat fiscal 4 M → IS 1 000 000 ; acomptes saisis 6 M.
    _solde(session, tid, mid, "701", "Ventes FICTIVES", "0", "9000000")
    _solde(session, tid, mid, "601", "Achats FICTIFS", "5000000", "0")
    _saisir_acompte(session, tid, mid, "6000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "excedent_indicatif"
    assert Decimal(corps["solde_indicatif"]["montant"]) == Decimal(
        "5000000"
    )
    assert Decimal(corps["solde_indicatif"]["solde_signe"]) == Decimal(
        "-5000000"
    )
    assert "Crédit d'impôt indicatif" in corps["solde_indicatif"][
        "libelle"
    ]


def test_api_indisponible_sans_balance_acomptes_listes(session):
    # Tolérance : sans balance, l'IS théorique ne se chiffre pas —
    # disponible=false, clés stables, acomptes saisis quand même
    # listés, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RapAcptes Vide FICTIVE")
    mid = _mission(session, tid, cid)
    _saisir_acompte(session, tid, mid, "500000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["is_theorique"] is None
    assert Decimal(corps["totaux_saisis"]["total"]) == Decimal("500000")
    assert len(corps["acomptes"]) == 1
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RapAcptes Journal FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(mid), headers=h).status_code == 200

    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m "
                    "AND action = 'consultation_rapprochement_acomptes'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_rapprochement_acomptes" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM RapAcptes Cross FICTIVE")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
