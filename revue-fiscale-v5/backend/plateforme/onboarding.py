"""État d'onboarding abonné — engagement post-inscription."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

ETAPES_CLES = (
    "email_verifie",
    "telephone_renseigne",
    "premier_client",
    "premiere_mission",
    "equipe_invitee",
)

_ETAPES_DEFAUT: dict[str, bool] = {k: False for k in ETAPES_CLES}


class ErreurOnboarding(Exception):
    pass


def _maintenant() -> datetime:
    return datetime.now(UTC)


def _fusion_etapes(brut: Any) -> dict[str, bool]:
    out = dict(_ETAPES_DEFAUT)
    if isinstance(brut, dict):
        for k in ETAPES_CLES:
            if k in brut:
                out[k] = bool(brut[k])
    return out


def initialiser_onboarding(
    session: Session,
    tenant_id: int,
    *,
    email_verifie: bool = True,
    telephone_renseigne: bool = False,
) -> None:
    etapes = dict(_ETAPES_DEFAUT)
    etapes["email_verifie"] = email_verifie
    etapes["telephone_renseigne"] = telephone_renseigne
    import json

    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO onboarding_etat (tenant_id, etapes, maj_le) "
                "VALUES (:t, CAST(:e AS jsonb), :now) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {
                "t": tenant_id,
                "e": json.dumps(etapes),
                "now": _maintenant(),
            },
        )
    session.flush()


def _enrichir_auto(session: Session, etapes: dict[str, bool]) -> dict[str, bool]:
    n_clients = int(session.execute(text("SELECT count(*) FROM contribuable")).scalar_one())
    n_missions = int(session.execute(text("SELECT count(*) FROM mission")).scalar_one())
    n_invites = int(
        session.execute(
            text("SELECT count(*) FROM invitation WHERE statut = 'en_attente'")
        ).scalar_one()
    )
    n_users = int(session.execute(text("SELECT count(*) FROM utilisateur")).scalar_one())
    n_tel = int(
        session.execute(
            text(
                "SELECT count(*) FROM utilisateur "
                "WHERE telephone IS NOT NULL AND length(trim(telephone)) > 0"
            )
        ).scalar_one()
    )
    out = dict(etapes)
    if n_tel > 0:
        out["telephone_renseigne"] = True
    if n_clients > 0:
        out["premier_client"] = True
    if n_missions > 0:
        out["premiere_mission"] = True
    if n_invites > 0 or n_users > 1:
        out["equipe_invitee"] = True
    return out


def lire_onboarding(session: Session, tenant_id: int) -> dict[str, Any]:
    import json

    row = session.execute(
        text("SELECT etapes, complete_le FROM onboarding_etat WHERE tenant_id = :t"),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if row is None:
        initialiser_onboarding(session, tenant_id)
        row = session.execute(
            text("SELECT etapes, complete_le FROM onboarding_etat WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).mappings().one()

    etapes = _fusion_etapes(row["etapes"])
    etapes = _enrichir_auto(session, etapes)

    # Persiste l'enrichissement auto
    complete = all(etapes.values())
    complete_le = row["complete_le"]
    session.execute(
        text(
            "UPDATE onboarding_etat SET etapes = CAST(:e AS jsonb), maj_le = :now, "
            "complete_le = CASE WHEN :c THEN COALESCE(complete_le, :now) ELSE complete_le END "
            "WHERE tenant_id = :t"
        ),
        {
            "t": tenant_id,
            "e": json.dumps(etapes),
            "now": _maintenant(),
            "c": complete,
        },
    )
    session.flush()
    if complete and complete_le is None:
        complete_le = _maintenant()

    return {
        "etapes": etapes,
        "complete": complete,
        "complete_le": complete_le.isoformat() if complete_le else None,
        "progression": sum(1 for v in etapes.values() if v),
        "total": len(ETAPES_CLES),
    }


def marquer_etape(session: Session, tenant_id: int, etape_id: str) -> dict[str, Any]:
    if etape_id not in ETAPES_CLES:
        raise ErreurOnboarding(f"étape inconnue : {etape_id}")
    import json

    row = session.execute(
        text("SELECT etapes FROM onboarding_etat WHERE tenant_id = :t"),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if row is None:
        initialiser_onboarding(session, tenant_id)
        row = session.execute(
            text("SELECT etapes FROM onboarding_etat WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).mappings().one()

    etapes = _fusion_etapes(row["etapes"])
    etapes[etape_id] = True
    etapes = _enrichir_auto(session, etapes)
    complete = all(etapes.values())
    session.execute(
        text(
            "UPDATE onboarding_etat SET etapes = CAST(:e AS jsonb), maj_le = :now, "
            "complete_le = CASE WHEN :c THEN COALESCE(complete_le, :now) ELSE complete_le END "
            "WHERE tenant_id = :t"
        ),
        {
            "t": tenant_id,
            "e": json.dumps(etapes),
            "now": _maintenant(),
            "c": complete,
        },
    )
    session.flush()
    return lire_onboarding(session, tenant_id)
