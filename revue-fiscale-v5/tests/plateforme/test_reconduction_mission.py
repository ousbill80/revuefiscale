"""Reconduction d'une mission clôturée sur l'exercice suivant (N+1)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.reconduction_mission import (
    NOTE_RECONDUCTION,
    ErreurReconduction,
    ErreurReconductionConflit,
    construire_profil_reconduction,
    valider_reconduction,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_profil_reconduction_reprend_les_champs_connus():
    profil = construire_profil_reconduction(
        {
            "regime": "reel",
            "forme_juridique": "SA",
            "secteur": "commerce",
            "type_entite": "pme",
            "cross_border": False,
            "etiquette_profil": "standard",
            # Clé inconnue : jamais reprise (profil réel uniquement).
            "cle_inconnue": "x",
            # Valeur vide : ignorée.
            "champ_vide": "",
        }
    )
    assert profil == {
        "regime": "reel",
        "forme_juridique": "SA",
        "secteur": "commerce",
        "type_entite": "pme",
        "cross_border": False,
        "etiquette_profil": "standard",
    }


def test_profil_reconduction_minimal_regime_et_forme():
    profil = construire_profil_reconduction(
        {"regime": "reel", "forme_juridique": "SARL", "secteur": ""}
    )
    assert profil == {"regime": "reel", "forme_juridique": "SARL"}


def test_profil_reconduction_incomplet_ou_illisible():
    with pytest.raises(ErreurReconduction, match="forme_juridique"):
        construire_profil_reconduction({"regime": "reel"})
    with pytest.raises(ErreurReconduction, match="illisible"):
        construire_profil_reconduction(None)


def test_valider_reconduction_ok_retourne_exercice_suivant():
    assert (
        valider_reconduction(statut_source="cloturee", exercice_source=2024)
        == 2025
    )


@pytest.mark.parametrize("statut", ["cadrage", "en_cours", "", "inconnu"])
def test_valider_reconduction_refuse_non_cloturee(statut):
    with pytest.raises(ErreurReconductionConflit, match="clôturée"):
        valider_reconduction(statut_source=statut, exercice_source=2024)


def test_valider_reconduction_refuse_doublon_avec_id_existant():
    with pytest.raises(
        ErreurReconductionConflit, match=r"exercice 2025 \(mission #77\)"
    ):
        valider_reconduction(
            statut_source="cloturee",
            exercice_source=2024,
            mission_existante_id=77,
            denomination="PM Test",
        )


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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-recond-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="reconduction-mission")
    publier_version(session, lib, "recond@test.ci")


def _mission_cloturee(
    session,
    *,
    statut: str = "cloturee",
    honoraires: str | None = "500000",
    taux_horaire: str | None = "25000",
) -> tuple[int, int, int, str]:
    """Cabinet + contribuable + mission (statut forcé) → (tid, cid, mid, email)."""
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"recond.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Recond {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Recond FICTIF', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2024,
            profil={
                "regime": "reel",
                "forme_juridique": "SA",
                "secteur": "commerce",
            },
        )
        session.execute(
            text(
                "UPDATE mission SET statut = :s, honoraires = :h, "
                "taux_horaire = :th WHERE id = :m"
            ),
            {"s": statut, "h": honoraires, "th": taux_horaire, "m": mid},
        )
    return r.tenant_id, int(cid), int(mid), email


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


def test_api_reconduction_cree_mission_n_plus_1(session):
    tid, cid, mid, email = _mission_cloturee(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(f"/api/v1/missions/{mid}/reconduire", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["note"] == NOTE_RECONDUCTION
    nmid = corps["nouvelle_mission_id"]
    assert nmid != mid

    with contexte_tenant(session, tid):
        row = session.execute(
            text(
                "SELECT contribuable_id, exercice, statut, profil, "
                "honoraires, taux_horaire FROM mission WHERE id = :m"
            ),
            {"m": nmid},
        ).mappings().one()
    assert int(row["contribuable_id"]) == cid
    assert int(row["exercice"]) == 2025
    assert row["statut"] == "cadrage"
    # Profil repris (régime, forme juridique, secteur).
    profil = row["profil"]
    if isinstance(profil, str):
        import json as _json

        profil = _json.loads(profil)
    assert profil["regime"] == "reel"
    assert profil["forme_juridique"] == "SA"
    assert profil["secteur"] == "commerce"
    # Honoraires et taux horaire repris à titre indicatif.
    assert str(row["honoraires"]).startswith("500000")
    assert str(row["taux_horaire"]).startswith("25000")

    # Journal : reconduction_mission sur la SOURCE + creation_mission
    # sur la NOUVELLE mission.
    with contexte_tenant(session, tid):
        recond = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE mission_id = :m AND action = 'reconduction_mission'"
            ),
            {"m": mid},
        ).mappings().all()
        creations = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m AND action = 'creation_mission'"
            ),
            {"m": nmid},
        ).scalar_one()
    assert len(recond) == 1
    charge = recond[0]["charge_utile"]
    if isinstance(charge, str):
        import json as _json

        charge = _json.loads(charge)
    assert charge["nouvelle_mission_id"] == nmid
    assert charge["exercice"] == 2025
    assert int(creations) == 1


def test_api_reconduction_sans_honoraires_source(session):
    _tid, _cid, mid, email = _mission_cloturee(
        session, honoraires=None, taux_horaire=None
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(f"/api/v1/missions/{mid}/reconduire", headers=h)
    assert r.status_code == 200, r.text


def test_api_409_mission_non_cloturee(session):
    _tid, _cid, mid, email = _mission_cloturee(session, statut="en_cours")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(f"/api/v1/missions/{mid}/reconduire", headers=h)
    assert r.status_code == 409, r.text
    assert "clôturée" in r.json()["detail"]


def test_api_409_doublon_sur_retentative(session):
    _tid, _cid, mid, email = _mission_cloturee(session)
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(f"/api/v1/missions/{mid}/reconduire", headers=h)
    assert r1.status_code == 200, r1.text
    nmid = r1.json()["nouvelle_mission_id"]

    # Re-tentative : la mission N+1 existe déjà → 409 explicite avec l'id.
    r2 = client.post(f"/api/v1/missions/{mid}/reconduire", headers=h)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert f"#{nmid}" in detail
    assert "2025" in detail


def test_api_404_cross_tenant(session):
    _tid_a, _cid_a, mid_a, _email_a = _mission_cloturee(session)

    _assurer_version(session)
    email_b = f"recond.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Recond B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.post(f"/api/v1/missions/{mid_a}/reconduire", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.post("/api/v1/missions/1/reconduire")
    assert r.status_code == 401, r.text
