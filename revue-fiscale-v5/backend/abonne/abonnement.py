"""Profil cabinet + demandes de palier (self-service abonné)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.abonne.service import ErreurAbonne
from backend.billing.config_editeur import lire_grille_paliers
from backend.plateforme.paliers import (
    PALIERS_VALIDES,
    TARIFS_AVERTISSEMENT,
)
from backend.plateforme.quotas import lire_quota_periode

# Sentinel : champ absent du PATCH (ne pas écraser).
_UNSET = object()


def _strip_opt(val: str | None, *, max_len: int) -> str | None:
    if val is None:
        return None
    s = val.strip()
    if not s:
        return None
    if len(s) > max_len:
        raise ErreurAbonne(f"valeur trop longue (max {max_len})")
    return s


def _capital_opt(val: object | None) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    try:
        d = Decimal(str(val).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as e:
        raise ErreurAbonne("capital_social invalide") from e
    if d < 0:
        raise ErreurAbonne("capital_social négatif interdit")
    return d


def _tenant_identite_dict(row: Any) -> dict[str, Any]:
    cap = row.get("capital_social")
    if isinstance(cap, Decimal):
        capital_out: float | None = float(cap)
    elif cap is None:
        capital_out = None
    else:
        capital_out = float(cap)
    return {
        "id": int(row["id"]),
        "denomination": row["denomination"],
        "type": row["type"],
        "palier": row["palier"],
        "statut": row["statut"],
        "cree_le": row["cree_le"],
        "ncc": row.get("ncc"),
        "rccm": row.get("rccm"),
        "dfe": row.get("dfe"),
        "forme_juridique": row.get("forme_juridique"),
        "siege_social": row.get("siege_social"),
        "commune": row.get("commune"),
        "centre_impots": row.get("centre_impots"),
        "capital_social": capital_out,
    }


def lire_compte(session: Session, *, tenant_id: int, utilisateur_id: int) -> dict[str, Any]:
    """Dénomination + identité légale tenant + contact utilisateur — pas de mutation palier/quota."""
    tenant = session.execute(
        text(
            "SELECT id, denomination, type, palier, statut, cree_le, "
            "ncc, rccm, dfe, forme_juridique, siege_social, commune, "
            "centre_impots, capital_social "
            "FROM tenant WHERE id = :t"
        ),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if tenant is None:
        raise ErreurAbonne("tenant introuvable")

    user = session.execute(
        text(
            "SELECT id, email, role, telephone, actif "
            "FROM utilisateur WHERE id = :u AND tenant_id = :t"
        ),
        {"u": utilisateur_id, "t": tenant_id},
    ).mappings().one_or_none()
    if user is None:
        raise ErreurAbonne("utilisateur introuvable")

    return {
        "tenant": _tenant_identite_dict(tenant),
        "utilisateur": {
            "id": int(user["id"]),
            "email": user["email"],
            "role": user["role"],
            "telephone": user["telephone"],
            "actif": bool(user["actif"]),
        },
    }


def patcher_compte(
    session: Session,
    *,
    tenant_id: int,
    utilisateur_id: int,
    denomination: str | None = None,
    telephone: str | None = None,
    ncc: object = _UNSET,
    rccm: object = _UNSET,
    dfe: object = _UNSET,
    forme_juridique: object = _UNSET,
    siege_social: object = _UNSET,
    commune: object = _UNSET,
    centre_impots: object = _UNSET,
    capital_social: object = _UNSET,
) -> dict[str, Any]:
    """Met à jour dénomination / identité légale / téléphone — jamais palier/quota.

    Les champs identité absents (sentinel) ne sont pas touchés.
    Chaîne vide → NULL (effacement volontaire).
    """
    sets: list[str] = []
    params: dict[str, Any] = {"t": tenant_id}

    if denomination is not None:
        nom = denomination.strip()
        if not nom:
            raise ErreurAbonne("denomination vide")
        if len(nom) > 200:
            raise ErreurAbonne("denomination trop longue")
        sets.append("denomination = :denomination")
        params["denomination"] = nom

    limites = {
        "ncc": 64,
        "rccm": 80,
        "dfe": 80,
        "forme_juridique": 40,
        "siege_social": 500,
        "commune": 120,
        "centre_impots": 200,
    }
    textes = {
        "ncc": ncc,
        "rccm": rccm,
        "dfe": dfe,
        "forme_juridique": forme_juridique,
        "siege_social": siege_social,
        "commune": commune,
        "centre_impots": centre_impots,
    }
    for cle, val in textes.items():
        if val is _UNSET:
            continue
        if val is not None and not isinstance(val, str):
            raise ErreurAbonne(f"{cle} invalide")
        sets.append(f"{cle} = :{cle}")
        params[cle] = _strip_opt(val, max_len=limites[cle])

    if capital_social is not _UNSET:
        sets.append("capital_social = :capital_social")
        params["capital_social"] = _capital_opt(capital_social)

    if sets:
        session.execute(
            text(f"UPDATE tenant SET {', '.join(sets)} WHERE id = :t"),
            params,
        )

    if telephone is not None:
        tel = telephone.strip()
        if len(tel) > 40:
            raise ErreurAbonne("telephone trop long")
        session.execute(
            text(
                "UPDATE utilisateur SET telephone = :tel "
                "WHERE id = :u AND tenant_id = :t"
            ),
            {
                "tel": tel or None,
                "u": utilisateur_id,
                "t": tenant_id,
            },
        )
        if tel:
            from backend.plateforme.onboarding import marquer_etape

            try:
                marquer_etape(session, tenant_id, "telephone_renseigne")
            except Exception:
                # Onboarding optionnel si table absente
                pass

    return lire_compte(session, tenant_id=tenant_id, utilisateur_id=utilisateur_id)


def resume_abonnement(session: Session, tenant_id: int) -> dict[str, Any]:
    """Palier courant + grille lecture seule + badge tarifs_a_confirmer."""
    tenant = session.execute(
        text("SELECT id, denomination, palier, statut FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if tenant is None:
        raise ErreurAbonne("tenant introuvable")

    grille = lire_grille_paliers(session)
    quota = lire_quota_periode(session, tenant_id)
    effectif = grille.get("effectif") or {}
    prix = effectif.get("prix_mensuel_xof") or {}
    missions = effectif.get("missions_par_palier") or {}
    paliers_lecture = [
        {
            "code": code,
            "missions_incluses": missions.get(code),
            "prix_mensuel_xof": prix.get(code),
            "courant": code == str(tenant["palier"]),
        }
        for code in sorted(PALIERS_VALIDES)
    ]

    demandes_ouvertes = session.execute(
        text(
            "SELECT id, palier_actuel, palier_cible, motif, statut, cree_le "
            "FROM demande_palier "
            "WHERE tenant_id = :t AND statut = 'ouvert' "
            "ORDER BY id DESC"
        ),
        {"t": tenant_id},
    ).mappings().all()

    return {
        "tenant_id": int(tenant["id"]),
        "denomination": tenant["denomination"],
        "palier": tenant["palier"],
        "statut": tenant["statut"],
        "quota": quota.vers_dict() if quota else None,
        "paliers": paliers_lecture,
        "tarifs_a_confirmer": bool(grille.get("tarifs_a_confirmer", True)),
        "avertissement": grille.get("avertissement") or TARIFS_AVERTISSEMENT,
        "demandes_palier_ouvertes": [dict(r) for r in demandes_ouvertes],
    }


def creer_demande_palier(
    session: Session,
    *,
    tenant_id: int,
    cree_par: int,
    palier_cible: str,
    motif: str | None = None,
) -> dict[str, Any]:
    if palier_cible not in PALIERS_VALIDES:
        raise ErreurAbonne(f"palier_cible invalide : {palier_cible}")

    actuel = session.execute(
        text("SELECT palier FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()
    if actuel is None:
        raise ErreurAbonne("tenant introuvable")
    actuel_s = str(actuel)
    if palier_cible == actuel_s:
        raise ErreurAbonne("palier_cible identique au palier actuel")

    ouverte = session.execute(
        text(
            "SELECT id FROM demande_palier "
            "WHERE tenant_id = :t AND statut = 'ouvert' LIMIT 1"
        ),
        {"t": tenant_id},
    ).scalar_one_or_none()
    if ouverte is not None:
        raise ErreurAbonne(
            f"demande de palier déjà ouverte (id={int(ouverte)})"
        )

    try:
        rid = session.execute(
            text(
                "INSERT INTO demande_palier "
                "(tenant_id, palier_actuel, palier_cible, motif, statut, cree_par) "
                "VALUES (:t, :pa, :pc, :m, 'ouvert', :u) RETURNING id"
            ),
            {
                "t": tenant_id,
                "pa": actuel_s,
                "pc": palier_cible,
                "m": (motif or "").strip() or None,
                "u": cree_par,
            },
        ).scalar_one()
    except IntegrityError as e:
        raise ErreurAbonne(
            "demande de palier déjà ouverte (concurrence)"
        ) from e

    # Garde-fou : le palier tenant ne change pas ici.
    apres = session.execute(
        text("SELECT palier FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one()
    if str(apres) != actuel_s:
        raise ErreurAbonne("refus : la demande ne doit pas muter le palier")

    return {
        "id": int(rid),
        "palier_actuel": actuel_s,
        "palier_cible": palier_cible,
        "statut": "ouvert",
        "motif": (motif or "").strip() or None,
        "message": (
            "Demande enregistrée. Un collaborateur 2AàZ validera le changement "
            "via Admin billing (patcher_tenant)."
        ),
    }
