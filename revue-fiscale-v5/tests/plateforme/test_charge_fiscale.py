"""Panorama consultatif de la charge fiscale estimée de la mission."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.charge_fiscale import (
    COMPOSANTES_CHARGE_PROPRE,
    COMPOSANTES_PANORAMA,
    NOTE_CHARGE_FISCALE,
    STATUT_COMPLET,
    STATUT_INDISPONIBLE,
    STATUT_PARTIEL,
    assembler_charge_fiscale,
    composante_indisponible,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_composante_indisponible_cles_stables():
    c = composante_indisponible("is")
    assert c["disponible"] is False
    assert c["montant_estime"] is None
    assert c["incluse_dans_total"] is True
    # TVA et acomptes ne sont jamais additionnés à la charge propre.
    assert composante_indisponible("tva")["incluse_dans_total"] is False
    assert (
        composante_indisponible("acomptes")["incluse_dans_total"] is False
    )


def test_assembler_panorama_complet_total_hors_tva_et_acomptes():
    panorama = assembler_charge_fiscale(
        {
            "is": {"disponible": True, "montant_estime": "2500000"},
            "patente": {"disponible": True, "montant_estime": "1000000"},
            "salaires": {"disponible": True, "montant_estime": "800000"},
            # TVA collectée : présentée séparément, jamais additionnée.
            "tva": {"disponible": True, "montant_estime": "9999999"},
            # Acomptes : position de trésorerie, jamais additionnée.
            "acomptes": {"disponible": True, "montant_estime": None},
        }
    )
    assert panorama["disponible"] is True
    # 2 500 000 + 1 000 000 + 800 000 — TVA et acomptes exclus.
    assert panorama["total_charge_propre_estimee"] == "4300000"
    assert panorama["composantes_incluses_total"] == [
        "is", "patente", "salaires",
    ]
    assert panorama["composantes_indisponibles"] == []
    s = panorama["synthese"]
    assert s["statut"] == STATUT_COMPLET
    assert s["nb_composantes_disponibles"] == 5
    assert s["total_partiel"] is True
    assert s["tva_nette_declaree"] == "9999999"
    assert panorama["note"] == NOTE_CHARGE_FISCALE
    assert panorama["references"]


def test_assembler_tolere_composantes_manquantes_ou_invalides():
    # Seul l'IS est fourni ; les autres sont absentes, None ou non-dict.
    panorama = assembler_charge_fiscale(
        {
            "is": {"disponible": True, "montant_estime": "500000"},
            "patente": None,
            "salaires": "n/a",
            "tva": {"sans_cle_disponible": True},
        }
    )
    # Toutes les clés existent toujours (jamais d'attribut absent).
    for cle in COMPOSANTES_PANORAMA:
        assert cle in panorama["composantes"]
        assert "disponible" in panorama["composantes"][cle]
        assert "libelle" in panorama["composantes"][cle]
        assert "montant_estime" in panorama["composantes"][cle]
    assert panorama["total_charge_propre_estimee"] == "500000"
    assert panorama["composantes_indisponibles"] == [
        "patente", "salaires", "tva", "acomptes",
    ]
    assert panorama["synthese"]["statut"] == STATUT_PARTIEL
    assert panorama["synthese"]["tva_nette_declaree"] is None


def test_assembler_tout_indisponible():
    panorama = assembler_charge_fiscale({})
    assert panorama["disponible"] is False
    assert panorama["total_charge_propre_estimee"] == "0"
    assert panorama["composantes_incluses_total"] == []
    assert list(panorama["composantes_indisponibles"]) == list(
        COMPOSANTES_PANORAMA
    )
    assert panorama["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert panorama["note"] == NOTE_CHARGE_FISCALE


def test_assembler_composante_disponible_sans_montant_ignoree_du_total():
    # Une composante « charge propre » disponible mais sans montant
    # (défensif) n'ajoute rien et n'apparaît pas dans les incluses.
    panorama = assembler_charge_fiscale(
        {
            "is": {"disponible": True, "montant_estime": None},
            "patente": {"disponible": True, "montant_estime": "300000"},
        }
    )
    assert panorama["total_charge_propre_estimee"] == "300000"
    assert panorama["composantes_incluses_total"] == ["patente"]


def test_composantes_charge_propre_excluent_tva_et_acomptes():
    assert "tva" not in COMPOSANTES_CHARGE_PROPRE
    assert "acomptes" not in COMPOSANTES_CHARGE_PROPRE
    assert set(COMPOSANTES_CHARGE_PROPRE) <= set(COMPOSANTES_PANORAMA)


def test_note_consultative_rappelle_les_limites():
    assert "consultatif" in NOTE_CHARGE_FISCALE
    assert "PARTIEL" in NOTE_CHARGE_FISCALE
    assert "collecté" in NOTE_CHARGE_FISCALE
    assert "décide" in NOTE_CHARGE_FISCALE


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

    lib = f"v-chargefisc-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="charge-fiscale")
    publier_version(session, lib, "chargefisc@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"chf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab ChargeFisc {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission(session, tenant_id: int, nom: str) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
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
    return f"/api/v1/missions/{mid}/charge-fiscale"


def test_api_structure_et_agregation_sans_recalcul(session):
    from backend.plateforme.rapprochement_salaires import (
        saisir_declaration_salaires,
    )
    from backend.plateforme.rapprochement_tva import (
        saisir_declaration_tva,
    )

    tid, email = _cabinet(session)
    mid = _mission(session, tid, "PM ChargeFisc FICTIF")
    # Balance : CA 200M (patente) et résultat 200M - 60M = 140M (IS).
    _solde(session, tid, mid, "701", "Ventes", "0", "200000000")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    # Déclarations saisies (sommes reprises telles quelles).
    saisir_declaration_salaires(
        session, tid, mid, "2025-01", "10000000", "700000", "300000",
        acteur="chargefisc@test.ci",
    )
    saisir_declaration_salaires(
        session, tid, mid, "2025-02", "10000000", "700000", "300000",
        acteur="chargefisc@test.ci",
    )
    saisir_declaration_tva(
        session, tid, mid, "2025-01", "3600000", "1600000",
        acteur="chargefisc@test.ci",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    for cle in COMPOSANTES_PANORAMA:
        assert cle in corps["composantes"]

    # IS : résultat fiscal 140M × 25 % = 35M (module resultat_fiscal).
    comp_is = corps["composantes"]["is"]
    assert comp_is["disponible"] is True
    assert Decimal(comp_is["montant_estime"]) == Decimal("35000000")
    assert comp_is["taux_is_normal"] == "0.25"

    # Patente : 200M × 0,5 % = 1M (module patente, estimation partielle).
    comp_pat = corps["composantes"]["patente"]
    assert comp_pat["disponible"] is True
    assert Decimal(comp_pat["montant_estime"]) == Decimal("1000000")
    assert comp_pat["estimation_partielle"] is True

    # Salaires : ITS 1,4M + contribution 0,6M = 2M (sommes déclarées).
    comp_sal = corps["composantes"]["salaires"]
    assert comp_sal["disponible"] is True
    assert Decimal(comp_sal["montant_estime"]) == Decimal("2000000")
    assert Decimal(comp_sal["its_retenu"]) == Decimal("1400000")
    assert Decimal(comp_sal["contribution_employeur"]) == Decimal(
        "600000"
    )
    assert comp_sal["nb_periodes_declarees"] == 2

    # TVA : nette déclarée 2M, présentée séparément (jamais additionnée).
    comp_tva = corps["composantes"]["tva"]
    assert comp_tva["disponible"] is True
    assert Decimal(comp_tva["montant_estime"]) == Decimal("2000000")
    assert comp_tva["incluse_dans_total"] is False
    assert comp_tva["impot_collecte"] is True

    # Acomptes : IS dû estimé non saisi → indisponible (toléré).
    comp_ac = corps["composantes"]["acomptes"]
    assert comp_ac["disponible"] is False
    assert comp_ac["incluse_dans_total"] is False

    # Total charge propre : 35M + 1M + 2M — hors TVA, hors acomptes.
    assert Decimal(corps["total_charge_propre_estimee"]) == Decimal(
        "38000000"
    )
    assert corps["composantes_incluses_total"] == [
        "is", "patente", "salaires",
    ]
    assert corps["composantes_indisponibles"] == ["acomptes"]
    assert corps["synthese"]["statut"] == STATUT_PARTIEL
    assert corps["synthese"]["total_partiel"] is True
    assert corps["note"] == NOTE_CHARGE_FISCALE
    assert corps["references"]

    # Consultation journalisée (append_journal).
    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'consultation_charge_fiscale'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) >= 1


def test_api_tolerance_mission_vide(session):
    # Sans balance ni déclaration ni saisie : le panorama se sert
    # quand même — toutes les composantes indisponibles, total 0,
    # aucun montant inventé.
    tid, email = _cabinet(session)
    mid = _mission(session, tid, "PM ChargeFisc Vide FICTIF")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["total_charge_propre_estimee"] == "0"
    assert list(corps["composantes_indisponibles"]) == list(
        COMPOSANTES_PANORAMA
    )
    for cle in COMPOSANTES_PANORAMA:
        comp = corps["composantes"][cle]
        assert comp["disponible"] is False
        assert comp["montant_estime"] is None
    assert corps["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert corps["note"] == NOTE_CHARGE_FISCALE


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    mid_a = _mission(session, tid_a, "PM ChargeFisc Cross FICTIF")
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
