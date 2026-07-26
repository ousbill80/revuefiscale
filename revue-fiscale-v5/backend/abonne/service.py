"""Module espace abonne — invitations, equipe, liens client."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.abonne.contribuable_identite import (
    COLONNES_IDENTITE,
    ErreurIdentiteLegale,
    normaliser_payload,
    serialiser_identite,
    valider_identite_legale,
)
from backend.plateforme.auth import hasher_mot_de_passe


class ErreurAbonne(Exception):
    """Echec metier espace abonne."""


ROLES_INVITABLES = frozenset({"admin", "reviseur", "lecteur"})

_COLS_C = ", ".join(f"c.{c}" for c in ("id", *COLONNES_IDENTITE))
_SELECT_CONTRIBUABLE = (
    f"SELECT {_COLS_C}, c.cree_le, c.cree_par, "  # noqa: S608 — colonnes constantes
    "u.email AS cree_par_email "
    "FROM contribuable c "
    "LEFT JOIN utilisateur u ON u.id = c.cree_par"
)


def _hash_token(brut: str) -> str:
    return hashlib.sha256(brut.encode()).hexdigest()


def generer_token() -> tuple[str, str]:
    """Retourne (token_clair, token_hash). Le clair n est montre qu une fois."""
    brut = secrets.token_urlsafe(32)
    return brut, _hash_token(brut)


def lister_contribuables(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(f"{_SELECT_CONTRIBUABLE} ORDER BY c.denomination, c.id")  # noqa: S608
    ).mappings().all()
    return [serialiser_identite(dict(r)) for r in rows]


def lire_contribuable(session: Session, contribuable_id: int) -> dict[str, Any]:
    row = session.execute(
        text(f"{_SELECT_CONTRIBUABLE} WHERE c.id = :id"),  # noqa: S608
        {"id": contribuable_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurAbonne(f"contribuable {contribuable_id} introuvable")
    return serialiser_identite(dict(row))


def creer_contribuable(
    session: Session,
    *,
    tenant_id: int,
    cree_par: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Crée une fiche cloisonnée + horodatage / auteur."""
    cid = session.execute(
        text(
            "INSERT INTO contribuable ("
            "tenant_id, denomination, ncc, rccm, forme, "
            "dfe, regime_fiscal, forme_juridique, siege_social, "
            "commune, centre_impots, "
            "capital_social, mois_cloture, activite_principale, date_immatriculation, "
            "cree_par, cree_le"
            ") VALUES ("
            ":t, :denomination, :ncc, :rccm, :forme, "
            ":dfe, :regime_fiscal, :forme_juridique, :siege_social, "
            ":commune, :centre_impots, "
            ":capital_social, :mois_cloture, :activite_principale, :date_immatriculation, "
            ":cree_par, now()"
            ") RETURNING id"
        ),
        {"t": tenant_id, "cree_par": cree_par, **payload},
    ).scalar_one()
    return lire_contribuable(session, int(cid))


def patcher_contribuable(
    session: Session,
    contribuable_id: int,
    *,
    denomination: str | None = None,
    ncc: str | None = None,
    rccm: str | None = None,
    forme: str | None = None,
    dfe: str | None = None,
    regime_fiscal: str | None = None,
    forme_juridique: str | None = None,
    siege_social: str | None = None,
    commune: str | None = None,
    centre_impots: str | None = None,
    capital_social: object | None = None,
    mois_cloture: object | None = None,
    activite_principale: str | None = None,
    date_immatriculation: object | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    row = lire_contribuable(session, contribuable_id)

    try:
        payload = normaliser_payload(
            denomination=denomination if denomination is not None else row["denomination"],
            ncc=ncc if ncc is not None else row["ncc"],
            rccm=rccm if rccm is not None else row["rccm"],
            forme=forme if forme is not None else row["forme"],
            dfe=dfe if dfe is not None else row.get("dfe"),
            regime_fiscal=(
                regime_fiscal
                if regime_fiscal is not None
                else row.get("regime_fiscal")
            ),
            forme_juridique=(
                forme_juridique
                if forme_juridique is not None
                else row.get("forme_juridique")
            ),
            siege_social=(
                siege_social
                if siege_social is not None
                else row.get("siege_social")
            ),
            commune=commune if commune is not None else row.get("commune"),
            centre_impots=(
                centre_impots
                if centre_impots is not None
                else row.get("centre_impots")
            ),
            capital_social=(
                capital_social
                if capital_social is not None
                else row.get("capital_social")
            ),
            mois_cloture=(
                mois_cloture
                if mois_cloture is not None
                else row.get("mois_cloture")
            ),
            activite_principale=(
                activite_principale
                if activite_principale is not None
                else row.get("activite_principale")
            ),
            date_immatriculation=(
                date_immatriculation
                if date_immatriculation is not None
                else row.get("date_immatriculation")
            ),
        )
        valider_identite_legale(payload, strict=strict)
    except ErreurIdentiteLegale as e:
        raise ErreurAbonne(str(e)) from e

    session.execute(
        text(
            "UPDATE contribuable SET "
            "denomination = :denomination, ncc = :ncc, rccm = :rccm, forme = :forme, "
            "dfe = :dfe, regime_fiscal = :regime_fiscal, "
            "forme_juridique = :forme_juridique, siege_social = :siege_social, "
            "commune = :commune, centre_impots = :centre_impots, "
            "capital_social = :capital_social, mois_cloture = :mois_cloture, "
            "activite_principale = :activite_principale, "
            "date_immatriculation = :date_immatriculation "
            "WHERE id = :id"
        ),
        {**payload, "id": contribuable_id},
    )
    return lire_contribuable(session, contribuable_id)


def lister_missions(
    session: Session,
    *,
    statut: str | None = None,
    exercice: int | None = None,
    contribuable_id: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    sql = (
        "SELECT m.id, m.exercice, m.statut, m.cree_le, m.version_referentiel_id, "
        "m.contribuable_id, m.type_engagement, m.perimetre_impots, "
        "c.denomination AS contribuable_denomination "
        "FROM mission m "
        "JOIN contribuable c ON c.id = m.contribuable_id "
        "WHERE 1=1"
    )
    if statut:
        sql += " AND m.statut = :statut"
        params["statut"] = statut
    if exercice is not None:
        sql += " AND m.exercice = :exercice"
        params["exercice"] = exercice
    if contribuable_id is not None:
        sql += " AND m.contribuable_id = :cid"
        params["cid"] = contribuable_id
    sql += " ORDER BY m.cree_le DESC, m.id DESC"
    rows = session.execute(text(sql), params).mappings().all()
    from backend.plateforme.missions import (
        LIBELLES_ENGAGEMENT,
        normaliser_perimetre_lu,
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        type_eng = str(d.get("type_engagement") or "autre")
        perimetre = normaliser_perimetre_lu(d.get("perimetre_impots"))
        d["type_engagement"] = type_eng
        d["type_engagement_libelle"] = LIBELLES_ENGAGEMENT.get(type_eng, type_eng)
        d["perimetre_impots"] = perimetre
        d["revue_partielle"] = perimetre is not None
        out.append(d)
    return out


def lister_utilisateurs(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, email, role, actif FROM utilisateur ORDER BY email"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def modifier_role_utilisateur(
    session: Session,
    *,
    utilisateur_id: int,
    role: str,
    acteur_id: int,
) -> dict[str, Any]:
    if role not in ROLES_INVITABLES:
        raise ErreurAbonne(f"role invalide : {role}")
    if utilisateur_id == acteur_id and role != "admin":
        # Empêche de se retirer le dernier admin soi-même sans garde-fou simple
        n_admins = session.execute(
            text(
                "SELECT COUNT(*) FROM utilisateur "
                "WHERE role = 'admin' AND actif IS TRUE"
            )
        ).scalar_one()
        if int(n_admins) <= 1:
            raise ErreurAbonne(
                "impossible de retirer le role admin du dernier administrateur"
            )
    row = session.execute(
        text(
            "UPDATE utilisateur SET role = :r WHERE id = :id "
            "RETURNING id, email, role, actif"
        ),
        {"r": role, "id": utilisateur_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurAbonne("utilisateur introuvable")
    return dict(row)


def revoquer_invitation(session: Session, invitation_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            "UPDATE invitation SET statut = 'annulee' "
            "WHERE id = :id AND statut = 'en_attente' "
            "RETURNING id, email, role, statut, cree_le, expire_le, acceptee_le"
        ),
        {"id": invitation_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurAbonne(
            "invitation introuvable ou non revoquable (deja traitee)"
        )
    return dict(row)


def creer_invitation(
    session: Session,
    tenant_id: int,
    *,
    email: str,
    role: str,
    invitee_par: int | None,
    ttl_jours: int = 14,
) -> dict[str, Any]:
    if role not in ROLES_INVITABLES:
        raise ErreurAbonne(f"role invalide : {role}")
    email_n = email.strip().lower()
    if not email_n or "@" not in email_n:
        raise ErreurAbonne("email invalide")

    existe = session.execute(
        text("SELECT 1 FROM utilisateur WHERE email = :e"),
        {"e": email_n},
    ).scalar_one_or_none()
    if existe:
        raise ErreurAbonne("un utilisateur avec cet email existe deja")

    token, token_hash = generer_token()
    expire = datetime.now(UTC) + timedelta(days=ttl_jours)
    iid = session.execute(
        text(
            "INSERT INTO invitation "
            "(tenant_id, email, role, token_hash, invitee_par, expire_le) "
            "VALUES (:t, :e, :r, :h, :p, :x) RETURNING id"
        ),
        {
            "t": tenant_id,
            "e": email_n,
            "r": role,
            "h": token_hash,
            "p": invitee_par,
            "x": expire,
        },
    ).scalar_one()

    email_statut = "non_tente"
    email_mode = None
    email_outbox_id = None
    try:
        from backend.plateforme.email_outbox import envoyer_invitation

        envoi = envoyer_invitation(
            session,
            tenant_id=tenant_id,
            email=email_n,
            role=role,
            token=token,
        )
        email_statut = envoi.statut
        email_mode = envoi.mode
        email_outbox_id = envoi.outbox_id
    except Exception as e:  # noqa: BLE001 — ne bloque pas la création d'invitation
        email_statut = "echec"
        email_mode = "echec"
        # outbox best-effort déjà géré dans envoyer_invitation ; log seulement
        import logging

        logging.getLogger(__name__).warning(
            "envoi invitation non bloquant échoué : %s", e
        )

    return {
        "id": int(iid),
        "email": email_n,
        "role": role,
        "expire_le": expire.isoformat(),
        "token": token,
        "statut": "en_attente",
        "email_envoi": {
            "statut": email_statut,
            "mode": email_mode,
            "outbox_id": email_outbox_id,
            "note": (
                "En prod sans RESEND_API_KEY : statut echec (pas de faux envoi). "
                "En dev : simule_dev — jeton toujours affiché dans l'UI."
            ),
        },
    }


def lister_invitations(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, email, role, statut, cree_le, expire_le, acceptee_le "
            "FROM invitation ORDER BY cree_le DESC"
        )
    ).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        # ne jamais exposer token_hash
        out.append(d)
    return out


def accepter_invitation(
    session: Session,
    *,
    token: str,
    mot_de_passe: str,
) -> dict[str, Any]:
    if len(mot_de_passe) < 8:
        raise ErreurAbonne("mot de passe trop court (min 8)")
    token_hash = _hash_token(token)
    row = session.execute(
        text("SELECT * FROM auth_lookup_invitation(:h)"),
        {"h": token_hash},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurAbonne("invitation introuvable")
    if row["statut"] != "en_attente":
        raise ErreurAbonne(f"invitation deja {row['statut']}")
    expire = row["expire_le"]
    if expire is not None and expire < datetime.now(UTC):
        raise ErreurAbonne("invitation expiree")

    from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

    tenant_id = int(row["tenant_id"])
    email = str(row["email"])
    role = str(row["role"])
    hash_mdp = hasher_mot_de_passe(mot_de_passe)

    with contexte_tenant(session, tenant_id):
        uid = session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, :r, :h, TRUE) RETURNING id"
            ),
            {"t": tenant_id, "e": email, "r": role, "h": hash_mdp},
        ).scalar_one()
        session.execute(
            text(
                "UPDATE invitation SET statut = 'acceptee', acceptee_le = now() "
                "WHERE id = :id"
            ),
            {"id": int(row["id"])},
        )
    effacer_contexte_tenant(session)
    return {
        "utilisateur_id": int(uid),
        "tenant_id": tenant_id,
        "email": email,
        "role": role,
    }


def creer_lien_acces(
    session: Session,
    tenant_id: int,
    *,
    mission_id: int,
    email_contact: str | None,
    cree_par: int | None,
    ttl_jours: int = 30,
) -> dict[str, Any]:
    mid = session.execute(
        text("SELECT id FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).scalar_one_or_none()
    if mid is None:
        raise ErreurAbonne(f"mission {mission_id} introuvable")

    token, token_hash = generer_token()
    expire = datetime.now(UTC) + timedelta(days=ttl_jours)
    lid = session.execute(
        text(
            "INSERT INTO lien_acces_mission "
            "(tenant_id, mission_id, email_contact, token_hash, expire_le, cree_par) "
            "VALUES (:t, :m, :e, :h, :x, :p) RETURNING id"
        ),
        {
            "t": tenant_id,
            "m": mission_id,
            "e": (email_contact or "").strip().lower() or None,
            "h": token_hash,
            "x": expire,
            "p": cree_par,
        },
    ).scalar_one()
    return {
        "id": int(lid),
        "mission_id": mission_id,
        "token": token,
        "expire_le": expire.isoformat(),
        "statut": "actif",
    }


def resoudre_lien_client(session: Session, token: str) -> dict[str, Any]:
    token_hash = _hash_token(token)
    row = session.execute(
        text("SELECT * FROM client_lookup_lien(:h)"),
        {"h": token_hash},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurAbonne("lien introuvable")
    if row["statut"] != "actif":
        raise ErreurAbonne(f"lien {row['statut']}")
    expire = row["expire_le"]
    if expire is not None and expire < datetime.now(UTC):
        raise ErreurAbonne("lien expire")
    return dict(row)
