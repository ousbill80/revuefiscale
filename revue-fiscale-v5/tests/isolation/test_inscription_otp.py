"""Tests inscription OTP, emails jetables, téléphone E.164, onboarding."""
from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from backend.plateforme.email_otp import (
    ErreurOtp,
    consommer_jeton_inscription,
    demarrer_otp,
    supprimer_pending,
    verifier_otp,
)
from backend.plateforme.emails_jetables import est_email_jetable, valider_email_inscription
from backend.plateforme.onboarding import lire_onboarding, marquer_etape
from backend.plateforme.provisionnement import provisionner_cabinet
from backend.plateforme.telephone import ErreurTelephone, normaliser_e164


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@cabinet-test.ci"


@pytest.mark.db
def test_emails_jetables_rejetes():
    assert est_email_jetable("a@yopmail.com")
    assert est_email_jetable("x@mailinator.com")
    assert est_email_jetable("x@guerrillamail.com")
    assert not est_email_jetable("admin@cabinet.ci")
    with pytest.raises(ValueError, match="temporaires|jetables"):
        valider_email_inscription("spam@yopmail.com")


@pytest.mark.db
def test_telephone_e164_ci():
    assert normaliser_e164("07 00 00 00 00", "CI").startswith("+225")
    assert normaliser_e164("+2250700000000") == "+2250700000000"
    with pytest.raises(ErreurTelephone):
        normaliser_e164("123", "CI")


@pytest.mark.db
def test_otp_flux_et_finaliser(session, monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    from backend import config as cfg

    monkeypatch.setattr(cfg.config, "env", "dev")
    monkeypatch.setattr(cfg.config, "resend_api_key", "")
    monkeypatch.setattr(cfg.config, "otp_cooldown_seconds", 0)

    # Table présente ?
    try:
        session.execute(text("SELECT 1 FROM inscription_pending LIMIT 1"))
    except Exception:
        pytest.skip("migration 007 non appliquée — make migrate")

    email = _email("otp")
    dem = demarrer_otp(session, email)
    assert dem.otp_debug is not None
    assert len(dem.otp_debug) == 6

    with pytest.raises(ErreurOtp, match="incorrect"):
        verifier_otp(session, email, "000000")

    ver = verifier_otp(session, email, dem.otp_debug)
    assert ver.email == email
    assert len(ver.jeton_inscription) > 16

    mail = consommer_jeton_inscription(session, ver.jeton_inscription)
    assert mail == email

    tel = normaliser_e164("+2250700123456")
    r = provisionner_cabinet(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="demo-demo1",
        telephone=tel,
    )
    supprimer_pending(session, email)
    session.flush()

    from backend.plateforme.contexte import contexte_tenant

    with contexte_tenant(session, r.tenant_id):
        t = session.execute(
            text("SELECT telephone FROM utilisateur WHERE id = :id"),
            {"id": r.utilisateur_id},
        ).scalar_one()
        assert t == tel
        onb = lire_onboarding(session, r.tenant_id)
        assert onb["etapes"]["email_verifie"] is True
        assert onb["etapes"]["telephone_renseigne"] is True
        marquer_etape(session, r.tenant_id, "premier_client")
        onb2 = lire_onboarding(session, r.tenant_id)
        assert onb2["etapes"]["premier_client"] is True


@pytest.mark.db
def test_otp_cooldown(session, monkeypatch):
    from backend import config as cfg

    monkeypatch.setattr(cfg.config, "env", "dev")
    monkeypatch.setattr(cfg.config, "resend_api_key", "")
    monkeypatch.setattr(cfg.config, "otp_cooldown_seconds", 60)

    try:
        session.execute(text("SELECT 1 FROM inscription_pending LIMIT 1"))
    except Exception:
        pytest.skip("migration 007 non appliquée — make migrate")

    email = _email("cool")
    demarrer_otp(session, email)
    session.flush()
    with pytest.raises(ErreurOtp, match="patientez"):
        demarrer_otp(session, email)
    time.sleep(0.01)
