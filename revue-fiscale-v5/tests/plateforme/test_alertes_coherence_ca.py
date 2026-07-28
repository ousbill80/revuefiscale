"""Centre d'alertes — source cohérence CA (écart comptable / TVA)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.centre_alertes import (
    TYPES_ALERTE,
    alertes_depuis_coherence_ca,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.coherence_ca import evaluer_coherence_ca

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _soldes_ca(credit: str) -> list[dict]:
    return [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": credit},
    ]


def _vue(client: str, mission_id: int, coherence: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "coherence": coherence,
    }


def _coherence(credit: str, tva: str, exercice: int = 2025) -> dict:
    vue = evaluer_coherence_ca(
        _soldes_ca(credit),
        [{"periode": "2025-01", "tva_collectee": tva}],
    )
    vue["exercice"] = exercice
    return vue


def test_type_coherence_ca_dans_le_referentiel():
    assert "coherence_ca" in TYPES_ALERTE
    a = normaliser_alerte(
        {"type": "coherence_ca", "gravite": "vigilance"}
    )
    assert a["type"] == "coherence_ca"
    s = synthese_alertes([a])
    assert s["par_type"]["coherence_ca"] == 1


def test_ecart_a_expliquer_emet_vigilance_jamais_critique():
    # CA 100 000 000 ; TVA 16 200 000 ÷ 0,18 = 90 000 000 → 10,0 %.
    coherence = _coherence("100000000", "16200000")
    assert coherence["statut"] == "ecart_a_expliquer"
    alertes = alertes_depuis_coherence_ca(
        [_vue("SA FICTIVE", 7, coherence)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "coherence_ca"
    # JAMAIS critique — approximation mono-taux, non accusatoire.
    assert a["gravite"] == "vigilance"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "coherence_ca"
    assert "exercice 2025" in a["libelle"]
    assert "écart relatif 10,0 %" in a["libelle"]
    assert (
        "approximation mono-taux — écart à expliquer "
        "(exonérations, taux réduits, décalages)"
    ) in a["libelle"]


def test_rien_si_coherent_ou_indisponible():
    # Cohérent : 17 820 000 ÷ 0,18 = 99 000 000 → écart 1,0 %.
    coherent = _coherence("100000000", "17820000")
    assert coherent["statut"] == "coherent"
    # Indisponible : aucune balance.
    indisponible = evaluer_coherence_ca(
        [], [{"periode": "2025-01", "tva_collectee": "18000000"}]
    )
    indisponible["exercice"] = 2025
    assert indisponible["disponible"] is False
    alertes = alertes_depuis_coherence_ca(
        [
            _vue("A", 1, coherent),
            _vue("B", 2, indisponible),
            _vue("C", 3, {}),
        ]
    )
    assert alertes == []


def test_ca_comptable_nul_libelle_sans_pourcentage():
    # CA comptable nul mais TVA déclarée : écart sans base relative.
    coherence = _coherence("0", "18000000")
    assert coherence["statut"] == "ecart_a_expliquer"
    assert coherence["ecart_relatif_pct"] is None
    alertes = alertes_depuis_coherence_ca([_vue("D", 4, coherence)])
    assert len(alertes) == 1
    assert alertes[0]["gravite"] == "vigilance"
    assert "écart relatif" not in alertes[0]["libelle"]
    assert "exercice 2025" in alertes[0]["libelle"]


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/alertes"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-alcca-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="alertes coherence ca")
    publier_version(session, lib, "alcca@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alcca.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alcca {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission_en_cours(session, tenant_id: int, nom: str) -> int:
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
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": int(mid)},
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


def _point_en_retard(session, tenant_id: int, mission_id: int) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, date_cible) "
                "VALUES (:t, :m, :lib, CAST(:dc AS DATE))"
            ),
            {"t": tenant_id, "m": mission_id,
             "lib": "Justifier les exonérations TVA", "dc": "2020-01-15"},
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


def test_api_ecart_emet_alerte_vigilance_structure_stable(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alcca Ecart FICTIVE")
    # CA 100 000 000 ; TVA 16 200 000 ÷ 0,18 = 90 000 000 → 10,0 %.
    _solde(session, tid, mid, "701", "Ventes", "0", "100000000")
    _declaration(session, tid, mid, "2025-01", "16200000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = [
        a for a in corps["alertes"] if a["type"] == "coherence_ca"
    ]
    assert len(alertes) == 1
    a = alertes[0]
    # JAMAIS critique — approximation mono-taux documentée.
    assert a["gravite"] == "vigilance"
    assert a["client"] == "PM Alcca Ecart FICTIVE"
    assert a["mission_id"] == mid
    assert "exercice 2025" in a["libelle"]
    assert "écart relatif 10,0 %" in a["libelle"]
    assert "approximation mono-taux" in a["libelle"]
    assert "écart à expliquer" in a["libelle"]
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["lien"] == "coherence_ca"
    assert corps["synthese"]["par_type"]["coherence_ca"] == 1


def test_api_coherent_et_indisponible_aucune_alerte(session):
    tid, email = _cabinet(session)
    # Mission cohérente : 17 820 000 ÷ 0,18 = 99 000 000 → 1,0 %.
    mid_ok = _mission_en_cours(session, tid, "PM Alcca Coherent FICTIVE")
    _solde(session, tid, mid_ok, "701", "Ventes", "0", "100000000")
    _declaration(session, tid, mid_ok, "2025-01", "17820000")
    # Mission indisponible : ni balance ni déclaration.
    _mission_en_cours(session, tid, "PM Alcca Vide FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"] if a["type"] == "coherence_ca"
    ]
    assert corps["synthese"]["par_type"]["coherence_ca"] == 0


def test_api_source_coherence_ca_en_echec_jamais_bloquante(
    session, monkeypatch
):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alcca Panne FICTIVE")
    _point_en_retard(session, tid, mid)
    session.commit()

    import backend.plateforme.coherence_ca as cca

    def _boom(*args, **kwargs):
        raise RuntimeError("cohérence CA indisponible")

    monkeypatch.setattr(cca, "coherence_ca_mission", _boom)

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée, les autres alertes restent là.
    assert "coherence_ca" in corps["sources_en_echec"]
    assert any(
        a["type"] == "point_convenu" for a in corps["alertes"]
    )
    assert corps["note"]
