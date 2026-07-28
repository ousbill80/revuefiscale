"""Responsable de mission et charge du cabinet."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.responsable_mission import (
    LONGUEUR_MAX_EMAIL,
    NON_AFFECTE,
    ErreurResponsable,
    repartir_charge,
    valider_email_responsable,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_email_normalise():
    assert valider_email_responsable(" Awa.Kone@Cabinet.CI ") == (
        "awa.kone@cabinet.ci"
    )
    assert valider_email_responsable(None) is None


def test_valider_email_refuse_vide_et_formats():
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("   ")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("sans-arobase.ci")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("deux@@cabinet.ci")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("sans-point@cabinetci")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("@cabinet.ci")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("x@.cabinet.ci")
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("x@cabinet.ci.")


def test_valider_email_longueur_maximale():
    assert LONGUEUR_MAX_EMAIL == 254
    ok = "a" * (254 - len("@cab.ci")) + "@cab.ci"
    assert len(ok) == 254
    assert valider_email_responsable(ok) == ok
    with pytest.raises(ErreurResponsable):
        valider_email_responsable("a" + ok)


def test_repartir_charge_agrege_et_trie():
    rows = [
        {"responsable_email": "awa@cab.ci", "statut": "en_cours"},
        {"responsable_email": "awa@cab.ci", "statut": "cadrage"},
        {"responsable_email": "AWA@cab.ci ".strip(), "statut": "en_cours"},
        {"responsable_email": None, "statut": "cadrage"},
        {"responsable_email": "", "statut": "en_cours"},
        {"responsable_email": "ben@cab.ci", "statut": "en_cours"},
        {"responsable_email": "ben@cab.ci", "statut": "cadrage"},
    ]
    # Normalisation lower faite à l'écriture — ici la casse est conservée
    # telle quelle en base ; la ligne 3 est déjà en minuscules après strip.
    rows[2]["responsable_email"] = "awa@cab.ci"
    items = repartir_charge(rows)
    assert items[0] == {
        "responsable": "awa@cab.ci",
        "nb_missions": 3,
        "nb_en_cours": 2,
        "nb_cadrage": 1,
    }
    # « non affecté » regroupe NULL et vide ; à égalité (2 missions),
    # il passe après les personnes.
    assert [i["responsable"] for i in items] == [
        "awa@cab.ci",
        "ben@cab.ci",
        NON_AFFECTE,
    ]
    assert items[1] == {
        "responsable": "ben@cab.ci",
        "nb_missions": 2,
        "nb_en_cours": 1,
        "nb_cadrage": 1,
    }
    assert items[2] == {
        "responsable": NON_AFFECTE,
        "nb_missions": 2,
        "nb_en_cours": 1,
        "nb_cadrage": 1,
    }
    assert repartir_charge([]) == []


# ── Tests DB / API ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import (  # noqa: E402
    contexte_tenant,
    effacer_contexte_tenant,
)
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

    lib = f"v-respmis-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="responsable-mission")
    publier_version(session, lib, "respmis@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RespMis {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _collaborateur(session, tenant_id: int, actif: bool = True) -> str:
    from backend.plateforme.auth import hasher_mot_de_passe

    email = f"collab.{uuid.uuid4().hex[:8]}@demo.local"
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'reviseur', :h, :a)"
            ),
            {
                "t": tenant_id,
                "e": email,
                "h": hasher_mot_de_passe("x"),
                "a": actif,
            },
        )
    effacer_contexte_tenant(session)
    return email


def _mission(
    session,
    tenant_id: int,
    denomination: str,
    statut: str = "en_cours",
    exercice: int = 2025,
) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": denomination},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return int(mid)


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


def test_api_affectation_ok_et_journal(session):
    tid, email = _cabinet(session, "respmis.aff")
    collab = _collaborateur(session, tid)
    mid = _mission(session, tid, "SA Affectation FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": collab.upper()},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "mission_id": mid,
        "responsable_email": collab,
        "precedent": None,
    }

    # Lecture du responsable courant.
    lu = client.get(f"/api/v1/missions/{mid}/responsable", headers=h)
    assert lu.status_code == 200, lu.text
    assert lu.json()["responsable_email"] == collab

    # Journal chaîné : action + de/à.
    with contexte_tenant(session, tid):
        j = session.execute(
            text(
                "SELECT acteur, charge_utile FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'affectation_responsable_mission' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"m": mid},
        ).mappings().one()
    effacer_contexte_tenant(session)
    assert j["acteur"] == email
    assert j["charge_utile"] == {"de": None, "a": collab}


def test_api_email_inconnu_ou_inactif_422(session):
    tid, email = _cabinet(session, "respmis.inc")
    inactif = _collaborateur(session, tid, actif=False)
    mid = _mission(session, tid, "SA Inconnu FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": "hors.cabinet@ailleurs.ci"},
    )
    assert r.status_code == 422, r.text
    assert "aucun utilisateur actif" in r.json()["detail"]

    # Un compte désactivé n'est pas affectable non plus.
    r2 = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": inactif},
    )
    assert r2.status_code == 422, r2.text

    # Format invalide → 422 aussi.
    r3 = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": "pas-un-email"},
    )
    assert r3.status_code == 422, r3.text


def test_api_desaffectation(session):
    tid, email = _cabinet(session, "respmis.des")
    collab = _collaborateur(session, tid)
    mid = _mission(session, tid, "SA Désaffectation FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    aff = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": collab},
    )
    assert aff.status_code == 200, aff.text

    des = client.post(
        f"/api/v1/missions/{mid}/responsable",
        headers=h,
        json={"email": None},
    )
    assert des.status_code == 200, des.text
    assert des.json() == {
        "mission_id": mid,
        "responsable_email": None,
        "precedent": collab,
    }
    lu = client.get(f"/api/v1/missions/{mid}/responsable", headers=h)
    assert lu.json()["responsable_email"] is None


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "respmis.a")
    mid_a = _mission(session, tid_a, "SA Isolée FICTIVE")
    tid_b, email_b = _cabinet(session, "respmis.b")
    collab_b = _collaborateur(session, tid_b)
    session.commit()

    client, h_b = _client_connecte(email_b)
    r = client.post(
        f"/api/v1/missions/{mid_a}/responsable",
        headers=h_b,
        json={"email": collab_b},
    )
    assert r.status_code == 404, r.text
    lu = client.get(f"/api/v1/missions/{mid_a}/responsable", headers=h_b)
    assert lu.status_code == 404, lu.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert (
        client.post(
            "/api/v1/missions/1/responsable", json={"email": "x@y.ci"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/missions/1/responsable").status_code == 401
    assert client.get("/api/v1/cabinet/charge").status_code == 401


def test_api_charge_cabinet(session):
    tid, email = _cabinet(session, "respmis.chg")
    collab = _collaborateur(session, tid)
    mid1 = _mission(session, tid, "SA Charge Un FICTIVE", statut="en_cours")
    _mission(
        session,
        tid,
        "SARL Charge Deux FICTIVE",
        statut="cadrage",
        exercice=2024,
    )
    # Une mission clôturée n'entre pas dans la charge.
    _mission(
        session,
        tid,
        "SA Charge Close FICTIVE",
        statut="cloturee",
        exercice=2023,
    )
    session.commit()

    client, h = _client_connecte(email)
    aff = client.post(
        f"/api/v1/missions/{mid1}/responsable",
        headers=h,
        json={"email": collab},
    )
    assert aff.status_code == 200, aff.text

    r = client.get("/api/v1/cabinet/charge", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["items"] == [
        {
            "responsable": collab,
            "nb_missions": 1,
            "nb_en_cours": 1,
            "nb_cadrage": 0,
        },
        {
            "responsable": NON_AFFECTE,
            "nb_missions": 1,
            "nb_en_cours": 0,
            "nb_cadrage": 1,
        },
    ]
    assert corps["synthese"] == {
        "missions_actives": 2,
        "responsables": 1,
        "non_affectees": 1,
    }
    assert "note" in corps
