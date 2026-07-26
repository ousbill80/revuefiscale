"""Phase A — portail abonné commercial : factures, signalement, demandes palier."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.billing.auth import emettre_jeton_staff  # noqa: E402
from backend.billing.factures import (  # noqa: E402
    creer_facture_brouillon,
    emettre_facture,
    lire_facture,
)
from backend.billing.service import creer_tenant  # noqa: E402
from backend.main import app  # noqa: E402
from backend.plateforme.auth import emettre_jeton  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _cabinet(session, palier: str = "standard"):
    email = _email("cab")
    r = creer_tenant(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier=palier,
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    return r, email


def _headers_abonne(r, email: str, role: str = "admin") -> dict[str, str]:
    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role=role,
        email=email,
    )
    return {"Authorization": f"Bearer {jeton}"}


def _headers_staff(session) -> dict[str, str]:
    row = session.execute(
        text(
            "SELECT id, email, role FROM staff_2aaz "
            "WHERE actif AND role IN ('billing','ops') ORDER BY id LIMIT 1"
        )
    ).mappings().one()
    jeton = emettre_jeton_staff(
        staff_id=int(row["id"]),
        role=str(row["role"]),
        email=str(row["email"]),
    )
    return {"Authorization": f"Bearer {jeton}"}


def test_isolation_factures_et_demandes_paiement(session):
    a, email_a = _cabinet(session)
    b, email_b = _cabinet(session)
    fa = creer_facture_brouillon(session, a.tenant_id)
    fb = creer_facture_brouillon(session, b.tenant_id)
    emettre_facture(session, fa.id)
    emettre_facture(session, fb.id)
    session.commit()

    client = TestClient(app)
    ha = _headers_abonne(a, email_a)
    hb = _headers_abonne(b, email_b)

    la = client.get("/api/v1/factures", headers=ha)
    assert la.status_code == 200
    ids_a = {int(f["id"]) for f in la.json()["factures"]}
    assert fa.id in ids_a
    assert fb.id not in ids_a

    # Cross-tenant détail / PDF
    assert (
        client.get(f"/api/v1/factures/{fb.id}", headers=ha).status_code == 404
    )
    assert (
        client.get(f"/api/v1/factures/{fb.id}/pdf", headers=ha).status_code
        == 404
    )

    # Signaler chez B depuis A → 404 / 400 (facture hors tenant)
    sig = client.post(
        f"/api/v1/factures/{fb.id}/signaler-paiement",
        headers=ha,
        json={"note": "intrusion"},
    )
    assert sig.status_code in {400, 404}

    # Signaler correctement chez A
    ok = client.post(
        f"/api/v1/factures/{fa.id}/signaler-paiement",
        headers=ha,
        json={"note": "VIR-TEST"},
    )
    assert ok.status_code == 201
    assert ok.json()["facture_statut"] == "emise"
    assert ok.json()["statut"] == "ouvert"

    # Facture toujours émise (pas payée)
    session.expire_all()
    assert lire_facture(session, fa.id)["statut"] == "emise"

    # B ne voit pas la demande A (RLS)
    from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

    with contexte_tenant(session, b.tenant_id):
        n = session.execute(
            text("SELECT count(*) FROM demande_paiement WHERE facture_id = :f"),
            {"f": fa.id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    assert int(n) == 0

    # RLS facture : sans SET LOCAL → zéro ligne (refus par défaut)
    effacer_contexte_tenant(session)
    n_facture = session.execute(text("SELECT count(*) FROM facture")).scalar_one()
    assert int(n_facture) == 0

    # Avec contexte A : voit fa, pas fb
    with contexte_tenant(session, a.tenant_id):
        ids = set(
            session.execute(text("SELECT id FROM facture")).scalars().all()
        )
    effacer_contexte_tenant(session)
    assert fa.id in ids
    assert fb.id not in ids


def test_rls_facture_forcee_et_grants_demande(session):
    """Migration 022 : FORCE RLS facture ; pas d'UPDATE/DELETE abonné sur demande_*."""
    row = session.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'facture'"
        )
    ).one()
    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is True

    for table in ("demande_paiement", "demande_palier"):
        for verbe in ("UPDATE", "DELETE"):
            autorise = session.execute(
                text(
                    "SELECT has_table_privilege(current_user, :t, :v)"
                ),
                {"t": table, "v": verbe},
            ).scalar_one()
            assert autorise is False, f"{verbe} ne doit pas être sur {table}"


def test_abonne_ne_peut_pas_marquer_payee(session):
    r, email = _cabinet(session)
    f = creer_facture_brouillon(session, r.tenant_id)
    emettre_facture(session, f.id)
    session.commit()

    client = TestClient(app)
    h = _headers_abonne(r, email)

    # Route staff uniquement
    pay = client.post(f"/api/v1/billing/factures/{f.id}/payer", headers=h)
    assert pay.status_code in {401, 403}

    # Signaler ≠ payer
    sig = client.post(
        f"/api/v1/factures/{f.id}/signaler-paiement",
        headers=h,
        json={},
    )
    assert sig.status_code == 201
    session.expire_all()
    assert lire_facture(session, f.id)["statut"] == "emise"


def test_staff_traite_demandes_paiement_et_palier(session):
    r, email = _cabinet(session, palier="essentiel")
    f = creer_facture_brouillon(session, r.tenant_id)
    emettre_facture(session, f.id)
    session.commit()

    client = TestClient(app)
    ha = _headers_abonne(r, email)
    hs = _headers_staff(session)

    assert (
        client.post(
            f"/api/v1/factures/{f.id}/signaler-paiement",
            headers=ha,
            json={"note": "ok"},
        ).status_code
        == 201
    )
    dem_pal = client.post(
        "/api/v1/abonnement/demande-palier",
        headers=ha,
        json={"palier_cible": "standard", "motif": "quota"},
    )
    assert dem_pal.status_code == 201
    # Palier inchangé côté abonné
    abo = client.get("/api/v1/abonnement", headers=ha)
    assert abo.status_code == 200
    assert abo.json()["palier"] == "essentiel"

    liste_p = client.get("/api/v1/billing/demandes-paiement", headers=hs)
    assert liste_p.status_code == 200
    ouvertes_p = [d for d in liste_p.json() if d["statut"] == "ouvert"]
    assert any(int(d["facture_id"]) == f.id for d in ouvertes_p)
    did_p = next(int(d["id"]) for d in ouvertes_p if int(d["facture_id"]) == f.id)

    acc_p = client.post(
        f"/api/v1/billing/demandes-paiement/{did_p}/accepter",
        headers=hs,
        json={"marquer_facture_payee": True},
    )
    assert acc_p.status_code == 200
    session.expire_all()
    assert lire_facture(session, f.id)["statut"] == "payee"

    liste_l = client.get("/api/v1/billing/demandes-palier", headers=hs)
    assert liste_l.status_code == 200
    ouvertes_l = [d for d in liste_l.json() if d["statut"] == "ouvert"]
    assert any(int(d["tenant_id"]) == r.tenant_id for d in ouvertes_l)
    did_l = next(
        int(d["id"]) for d in ouvertes_l if int(d["tenant_id"]) == r.tenant_id
    )

    acc_l = client.post(
        f"/api/v1/billing/demandes-palier/{did_l}/accepter",
        headers=hs,
        json={"note_staff": "ok commercial"},
    )
    assert acc_l.status_code == 200
    abo2 = client.get("/api/v1/abonnement", headers=ha)
    assert abo2.json()["palier"] == "standard"


def test_compte_patch_sans_mutation_palier(session):
    r, email = _cabinet(session, palier="premium")
    session.commit()
    client = TestClient(app)
    h = _headers_abonne(r, email)

    before = client.get("/api/v1/compte", headers=h)
    assert before.status_code == 200
    assert before.json()["tenant"]["palier"] == "premium"
    assert before.json()["tenant"].get("ncc") is None

    patch = client.patch(
        "/api/v1/compte",
        headers=h,
        json={
            "denomination": "Cabinet Renommé SA",
            "telephone": "+22507000000",
            "ncc": "1234567A",
            "rccm": "CI-ABJ-2020-B-12345",
            "forme_juridique": "SA",
            "siege_social": "Cocody Angré 7e tranche",
            "commune": "Abidjan",
            "capital_social": 10_000_000,
        },
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["tenant"]["denomination"] == "Cabinet Renommé SA"
    assert body["tenant"]["palier"] == "premium"
    assert body["tenant"]["ncc"] == "1234567A"
    assert body["tenant"]["rccm"] == "CI-ABJ-2020-B-12345"
    assert body["tenant"]["forme_juridique"] == "SA"
    assert body["tenant"]["commune"] == "Abidjan"
    assert float(body["tenant"]["capital_social"]) == 10_000_000
    assert body["utilisateur"]["telephone"] == "+22507000000"

    # Contact seul ne doit pas effacer l'identité légale
    patch_tel = client.patch(
        "/api/v1/compte",
        headers=h,
        json={"telephone": "+22507001111"},
    )
    assert patch_tel.status_code == 200
    assert patch_tel.json()["tenant"]["ncc"] == "1234567A"
    assert patch_tel.json()["utilisateur"]["telephone"] == "+22507001111"
