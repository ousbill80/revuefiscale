"""Provisionnement automatise d un cabinet abonne.

Flux (docs/09-multitenant.md §6) :
  tenant → admin → quotas → epinglage version publiee (si disponible) → demo optionnelle
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.billing.config_editeur import missions_effectives
from backend.plateforme.auth import hasher_mot_de_passe
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.paliers import TYPES_TENANT


class ErreurProvisionnement(Exception):
    """Echec de creation d un cabinet."""


@dataclass(frozen=True)
class ResultatProvisionnement:
    tenant_id: int
    utilisateur_id: int
    email_admin: str
    palier: str
    version_referentiel_id: int | None
    demo_contribuable_id: int | None


def _premier_jour_mois(aujourd_hui: date | None = None) -> date:
    j = aujourd_hui or date.today()
    return j.replace(day=1)


def derniere_version_publiee(session: Session) -> int | None:
    return session.execute(
        text(
            "SELECT id FROM version_referentiel "
            "WHERE publiee_le IS NOT NULL ORDER BY publiee_le DESC LIMIT 1"
        )
    ).scalar_one_or_none()


def provisionner_cabinet(
    session: Session,
    *,
    denomination: str,
    type_tenant: str,
    palier: str,
    email_admin: str,
    mot_de_passe_admin: str,
    creer_demo: bool = False,
    telephone: str | None = None,
) -> ResultatProvisionnement:
    if type_tenant not in TYPES_TENANT:
        raise ErreurProvisionnement(f"type invalide : {type_tenant}")
    try:
        n_missions = missions_effectives(session, palier)
    except ValueError as e:
        raise ErreurProvisionnement(str(e)) from e
    if not denomination.strip():
        raise ErreurProvisionnement("denomination obligatoire")
    if "@" not in email_admin:
        raise ErreurProvisionnement("email admin invalide")
    if len(mot_de_passe_admin) < 8:
        raise ErreurProvisionnement("mot de passe trop court (min. 8)")

    tel_e164: str | None = None
    if telephone is not None and telephone.strip():
        from backend.plateforme.telephone import ErreurTelephone, normaliser_e164

        try:
            tel_e164 = normaliser_e164(telephone)
        except ErreurTelephone as e:
            raise ErreurProvisionnement(str(e)) from e

    existe = session.execute(
        text("SELECT 1 FROM auth_lookup_utilisateur(:e)"),
        {"e": email_admin.strip().lower()},
    ).scalar_one_or_none()
    if existe:
        raise ErreurProvisionnement(f"email deja pris : {email_admin}")

    tenant_id = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES (:d, :t, :p) RETURNING id"
        ),
        {"d": denomination.strip(), "t": type_tenant, "p": palier},
    ).scalar_one()

    version_id = derniere_version_publiee(session)
    demo_id: int | None = None

    debut = _premier_jour_mois()

    with contexte_tenant(session, tenant_id):
        utilisateur_id = session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, telephone) "
                "VALUES (:tid, :email, 'admin', :ph, :tel) RETURNING id"
            ),
            {
                "tid": tenant_id,
                "email": email_admin.strip().lower(),
                "ph": hasher_mot_de_passe(mot_de_passe_admin),
                "tel": tel_e164,
            },
        ).scalar_one()

        session.execute(
            text(
                "INSERT INTO quota (tenant_id, periode, missions_incluses) "
                "VALUES (:tid, :per, :n)"
            ),
            {
                "tid": tenant_id,
                "per": debut,
                "n": n_missions,
            },
        )

        if creer_demo:
            demo_id = session.execute(
                text(
                    "INSERT INTO contribuable (tenant_id, denomination) "
                    "VALUES (:tid, :nom) RETURNING id"
                ),
                {"tid": tenant_id, "nom": f"Client demo — {denomination.strip()}"},
            ).scalar_one()

    effacer_contexte_tenant(session)

    # Historique contractuel — table plateforme (hors RLS abonne).
    session.execute(
        text(
            "INSERT INTO abonnement (tenant_id, palier, periode_debut, statut, note) "
            "VALUES (:tid, :p, :d, 'actif', :n)"
        ),
        {
            "tid": tenant_id,
            "p": palier,
            "d": debut,
            "n": "provisionnement initial",
        },
    )
    session.flush()

    from backend.plateforme.onboarding import initialiser_onboarding

    initialiser_onboarding(
        session,
        tenant_id,
        email_verifie=True,
        telephone_renseigne=bool(tel_e164),
    )

    return ResultatProvisionnement(
        tenant_id=tenant_id,
        utilisateur_id=utilisateur_id,
        email_admin=email_admin.strip().lower(),
        palier=palier,
        version_referentiel_id=version_id,
        demo_contribuable_id=demo_id,
    )
