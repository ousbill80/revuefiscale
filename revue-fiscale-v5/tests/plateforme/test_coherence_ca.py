"""Cohérence CA comptable / CA reconstitué depuis les déclarations TVA."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.coherence_ca import (
    NOTE_COHERENCE_CA,
    SEUIL_ECART_RELATIF_PCT,
    STATUT_COHERENT,
    STATUT_ECART,
    STATUT_INDISPONIBLE,
    TAUX_TVA_NORMAL,
    calculer_ecart_relatif_pct,
    evaluer_coherence_ca,
    reconstituer_ca,
    totaliser_tva_collectee,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_constantes():
    assert str(TAUX_TVA_NORMAL) == "0.18"
    assert str(SEUIL_ECART_RELATIF_PCT) == "5.0"


def test_reconstitution_ca_taux_normal():
    # 18 000 000 de TVA collectée ÷ 0,18 = 100 000 000 de CA.
    assert reconstituer_ca(Decimal("18000000")) == Decimal(
        "100000000.00"
    )
    assert reconstituer_ca(Decimal("0")) == Decimal("0.00")


def test_totaliser_tva_collectee():
    decls = [
        {"periode": "2025-01", "tva_collectee": "1500000"},
        {"periode": "2025-02", "tva_collectee": "2500000"},
        {"periode": "2025-03", "tva_collectee": None},
    ]
    assert totaliser_tva_collectee(decls) == Decimal("4000000")
    assert totaliser_tva_collectee([]) == Decimal("0")


def test_ecart_relatif_une_decimale_point():
    # 12 500 000 / 100 000 000 = 12,5 % — str avec point.
    rel = calculer_ecart_relatif_pct(
        Decimal("12500000"), Decimal("100000000")
    )
    assert str(rel) == "12.5"
    # Écart négatif : le CA comptable est en deçà du reconstitué.
    rel_neg = calculer_ecart_relatif_pct(
        Decimal("-3000000"), Decimal("100000000")
    )
    assert str(rel_neg) == "-3.0"
    # CA comptable nul : pas de base, aucun pourcentage inventé.
    assert calculer_ecart_relatif_pct(
        Decimal("1"), Decimal("0")
    ) is None


def _soldes_ca(credit: str) -> list[dict]:
    return [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": credit},
    ]


def test_coherent_sous_seuil():
    # CA comptable 100 000 000 ; TVA 17 820 000 ÷ 0,18 = 99 000 000.
    # Écart 1 000 000 → 1,0 % ≤ 5,0 % → cohérent.
    vue = evaluer_coherence_ca(
        _soldes_ca("100000000"),
        [{"periode": "2025-01", "tva_collectee": "17820000"}],
    )
    assert vue["disponible"] is True
    assert vue["ca_comptable"] == "100000000"
    assert vue["ca_reconstitue"] == "99000000.00"
    assert vue["ecart"] == "1000000.00"
    assert vue["ecart_relatif_pct"] == "1.0"
    assert vue["statut"] == STATUT_COHERENT
    assert vue["approximation"] is True


def test_ecart_a_expliquer_au_dela_du_seuil():
    # CA comptable 100 000 000 ; TVA 16 200 000 ÷ 0,18 = 90 000 000.
    # Écart 10 000 000 → 10,0 % > 5,0 % → écart à expliquer.
    vue = evaluer_coherence_ca(
        _soldes_ca("100000000"),
        [{"periode": "2025-01", "tva_collectee": "16200000"}],
    )
    assert vue["ecart_relatif_pct"] == "10.0"
    assert vue["statut"] == STATUT_ECART
    # Jamais accusatoire : « à expliquer », l'humain apprécie.
    assert "expliquer" in vue["synthese"]["libelle_statut"]
    assert "apprécie" in vue["synthese"]["libelle_statut"]


def test_borne_exactement_au_seuil_coherent():
    # Écart exactement à 5,0 % : |écart relatif| ≤ seuil → cohérent.
    # TVA 17 100 000 ÷ 0,18 = 95 000 000 → écart 5 000 000 = 5,0 %.
    vue = evaluer_coherence_ca(
        _soldes_ca("100000000"),
        [{"periode": "2025-01", "tva_collectee": "17100000"}],
    )
    assert vue["ecart_relatif_pct"] == "5.0"
    assert vue["statut"] == STATUT_COHERENT


def test_ecart_negatif_symetrique():
    # CA reconstitué SUPÉRIEUR au comptable : -6,0 % → à expliquer
    # (le seuil s'applique en valeur absolue).
    # TVA 19 080 000 ÷ 0,18 = 106 000 000 → écart -6 000 000.
    vue = evaluer_coherence_ca(
        _soldes_ca("100000000"),
        [{"periode": "2025-01", "tva_collectee": "19080000"}],
    )
    assert vue["ecart"] == "-6000000.00"
    assert vue["ecart_relatif_pct"] == "-6.0"
    assert vue["statut"] == STATUT_ECART


def test_rrr_709_en_moins_du_ca():
    # Les 709x (RRR accordés, débiteurs) viennent en moins du CA.
    soldes = [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "105000000"},
        {"compte": "7091", "libelle": "RRR accordés",
         "debit": "5000000", "credit": "0"},
        {"compte": "771", "libelle": "Intérêts", "debit": "0",
         "credit": "999999"},
    ]
    vue = evaluer_coherence_ca(
        soldes, [{"periode": "2025-01", "tva_collectee": "18000000"}]
    )
    assert vue["ca_comptable"] == "100000000"
    assert vue["synthese"]["nb_comptes_ca"] == 2


def test_indisponible_sans_balance():
    vue = evaluer_coherence_ca(
        [], [{"periode": "2025-01", "tva_collectee": "18000000"}]
    )
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["ca_reconstitue"] == "0"
    assert vue["ecart"] == "0"
    assert vue["ecart_relatif_pct"] is None


def test_indisponible_sans_declaration():
    vue = evaluer_coherence_ca(_soldes_ca("100000000"), [])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["nb_declarations"] == 0


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "ca_comptable", "nb_declarations",
        "tva_collectee_totale", "taux_normal", "ca_reconstitue",
        "approximation", "ecart", "ecart_relatif_pct", "seuil_pct",
        "statut", "synthese", "note", "references",
    }
    for vue in (
        evaluer_coherence_ca([], []),
        evaluer_coherence_ca(
            _soldes_ca("1000"),
            [{"periode": "2025-01", "tva_collectee": "180"}],
        ),
    ):
        assert cles <= set(vue)
        assert vue["approximation"] is True
        assert vue["seuil_pct"] == "5.0"
        assert vue["taux_normal"] == "0.18"
        assert vue["note"] == NOTE_COHERENCE_CA
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]


def test_note_approximation_documentee_et_non_accusatoire():
    assert "consultati" in NOTE_COHERENCE_CA
    assert "APPROXIMATION" in NOTE_COHERENCE_CA
    assert "exonérations" in NOTE_COHERENCE_CA
    assert "taux réduits" in NOTE_COHERENCE_CA
    assert "hors champ" in NOTE_COHERENCE_CA
    assert "à expliquer" in NOTE_COHERENCE_CA
    assert "décide" in NOTE_COHERENCE_CA


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

    lib = f"v-cca-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="coherence ca")
    publier_version(session, lib, "cca@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"cca.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CoherenceCa {email}",
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


def _declaration(session, tenant_id: int, mission_id: int,
                 periode: str, tva_collectee: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO declaration_tva (tenant_id, mission_id, "
                "periode, tva_collectee, tva_deductible) "
                "VALUES (:t, :m, :p, :c, 0)"
            ),
            {"t": tenant_id, "m": mission_id, "p": periode,
             "c": tva_collectee},
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
    return f"/api/v1/missions/{mid}/coherence-ca"


def test_api_structure_complete(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CoherenceCa FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "100000000")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    _declaration(session, tid, mid, "2025-01", "9000000")
    _declaration(session, tid, mid, "2025-02", "8820000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["ca_comptable"] == "100000000.00"
    assert corps["nb_declarations"] == 2
    assert corps["tva_collectee_totale"] == "17820000.00"
    assert corps["taux_normal"] == "0.18"
    # 17 820 000 ÷ 0,18 = 99 000 000 → écart 1 000 000 = 1,0 %.
    assert corps["ca_reconstitue"] == "99000000.00"
    assert corps["approximation"] is True
    assert corps["ecart"] == "1000000.00"
    assert corps["ecart_relatif_pct"] == "1.0"
    assert corps["seuil_pct"] == "5.0"
    assert corps["statut"] == "coherent"
    assert corps["synthese"]["statut"] == "coherent"
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_tolerance_sans_donnees(session):
    # Tolérance : sans balance ni déclaration, la vue se sert quand
    # même — disponible=false, clés stables, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CoherenceCa Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["ca_reconstitue"] == "0"
    assert corps["ecart_relatif_pct"] is None
    assert corps["approximation"] is True
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM CoherenceCa Journal FICTIF")
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
                    "AND action = 'consultation_coherence_ca'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_coherence_ca" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM CoherenceCa Cross FICTIF")
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
