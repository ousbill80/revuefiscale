"""Config éditeur 2AàZ — paliers + mentions facture (saisie, pas invention)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import config
from backend.plateforme.email_outbox import statut_resend
from backend.plateforme.paliers import (
    MISSIONS_PAR_PALIER,
    PALIERS_VALIDES,
    PRIX_MENSUEL_XOF,
    TARIFS_AVERTISSEMENT,
)

CLE_PALIERS = "paliers"
CLE_MENTIONS = "mentions_facture"

CHAMPS_MENTIONS = (
    "raison_sociale",
    "siege",
    "rccm",
    "idu",
    "compte_bancaire",
    "regime_tva",
    "taux_tva",
)


def _get(session: Session, cle: str) -> dict[str, Any] | None:
    row = session.execute(
        text("SELECT valeur FROM config_editeur WHERE cle = :c"),
        {"c": cle},
    ).mappings().one_or_none()
    if row is None:
        return None
    val = row["valeur"]
    return dict(val) if isinstance(val, dict) else None


def _set(
    session: Session,
    cle: str,
    valeur: dict[str, Any],
    *,
    par: str | None,
) -> None:
    session.execute(
        text(
            "INSERT INTO config_editeur (cle, valeur, mis_a_jour_le, mis_a_jour_par) "
            "VALUES (:c, CAST(:v AS jsonb), now(), :p) "
            "ON CONFLICT (cle) DO UPDATE SET "
            "valeur = EXCLUDED.valeur, "
            "mis_a_jour_le = now(), "
            "mis_a_jour_par = EXCLUDED.mis_a_jour_par"
        ),
        {
            "c": cle,
            "v": __import__("json").dumps(valeur, ensure_ascii=False, default=str),
            "p": par,
        },
    )
    session.flush()


def _decimal_or_none(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"montant invalide : {raw!r}") from None


def lire_grille_paliers(session: Session) -> dict[str, Any]:
    """Saisie éditeur (peut être vide) + provisoire technique + effectif."""
    stocke = _get(session, CLE_PALIERS) or {}
    saisie_prix: dict[str, str | None] = {}
    saisie_missions: dict[str, int | None] = {}
    prix_raw = stocke.get("prix_mensuel_xof") or {}
    miss_raw = stocke.get("missions_par_palier") or {}
    if not isinstance(prix_raw, dict):
        prix_raw = {}
    if not isinstance(miss_raw, dict):
        miss_raw = {}

    effectif_prix: dict[str, str] = {}
    effectif_missions: dict[str, int] = {}
    n_saisis = 0
    for palier in sorted(PALIERS_VALIDES):
        p_saisi = _decimal_or_none(prix_raw.get(palier)) if prix_raw else None
        m_saisi = miss_raw.get(palier)
        if m_saisi is not None and m_saisi != "":
            try:
                m_saisi_i = int(m_saisi)
            except (TypeError, ValueError) as e:
                raise ValueError(f"missions invalides pour {palier}") from e
        else:
            m_saisi_i = None
        saisie_prix[palier] = str(p_saisi) if p_saisi is not None else None
        saisie_missions[palier] = m_saisi_i
        if p_saisi is not None:
            n_saisis += 1
            effectif_prix[palier] = str(p_saisi)
        else:
            effectif_prix[palier] = str(PRIX_MENSUEL_XOF[palier])
        if m_saisi_i is not None:
            effectif_missions[palier] = m_saisi_i
        else:
            effectif_missions[palier] = MISSIONS_PAR_PALIER[palier]

    # Tarifs À CONFIRMER tant qu'aucune saisie éditeur complète des 4 paliers.
    tarifs_a_confirmer = n_saisis < len(PALIERS_VALIDES)
    return {
        "responsabilite": "saisie éditeur — responsabilité 2AàZ",
        "tarifs_a_confirmer": tarifs_a_confirmer,
        "avertissement": (
            "Saisie éditeur — responsabilité 2AàZ. "
            + (
                TARIFS_AVERTISSEMENT
                if tarifs_a_confirmer
                else "Montants saisis par l'éditeur (écrasent le provisoire technique)."
            )
        ),
        "saisie_editeur": {
            "prix_mensuel_xof": saisie_prix,
            "missions_par_palier": saisie_missions,
            "completee": not tarifs_a_confirmer,
        },
        "provisoire_technique": {
            "prix_mensuel_xof": {k: str(v) for k, v in PRIX_MENSUEL_XOF.items()},
            "missions_par_palier": dict(MISSIONS_PAR_PALIER),
        },
        "effectif": {
            "prix_mensuel_xof": effectif_prix,
            "missions_par_palier": effectif_missions,
            "source": "saisie_editeur" if not tarifs_a_confirmer else "provisoire_technique",
        },
    }


def ecrire_grille_paliers(
    session: Session,
    *,
    prix_mensuel_xof: dict[str, Any] | None,
    missions_par_palier: dict[str, Any] | None,
    par: str | None,
) -> dict[str, Any]:
    prix_out: dict[str, str | None] = {}
    miss_out: dict[str, int | None] = {}
    prix_in = prix_mensuel_xof or {}
    miss_in = missions_par_palier or {}
    for palier in sorted(PALIERS_VALIDES):
        if palier not in PALIERS_VALIDES:
            continue
        p = _decimal_or_none(prix_in.get(palier)) if palier in prix_in else None
        # Champ absent du payload → conserver / laisser vide selon présence clé
        if palier in prix_in:
            prix_out[palier] = str(p) if p is not None else None
        else:
            prix_out[palier] = None
        if palier in miss_in:
            raw_m = miss_in.get(palier)
            if raw_m is None or raw_m == "":
                miss_out[palier] = None
            else:
                miss_out[palier] = int(raw_m)
                if miss_out[palier] < 0:
                    raise ValueError(f"missions négatives pour {palier}")
        else:
            miss_out[palier] = None
    _set(
        session,
        CLE_PALIERS,
        {
            "prix_mensuel_xof": prix_out,
            "missions_par_palier": miss_out,
        },
        par=par,
    )
    return lire_grille_paliers(session)


def lire_mentions_facture(session: Session) -> dict[str, Any]:
    """Fusion : saisie DB (si non vide) → sinon env → sinon À CONFIRMER."""
    env = config.mentions_legales_facture()
    stocke = _get(session, CLE_MENTIONS) or {}
    saisie: dict[str, str | None] = {}
    effectif: dict[str, str] = {}
    n_saisis = 0
    for champ in CHAMPS_MENTIONS:
        val = stocke.get(champ)
        if isinstance(val, str) and val.strip() and val.strip().upper() not in {
            "À CONFIRMER",
            "A CONFIRMER",
            "A_CONFIRMER",
        }:
            saisie[champ] = val.strip()
            effectif[champ] = val.strip()
            n_saisis += 1
        else:
            saisie[champ] = (val.strip() if isinstance(val, str) and val.strip() else None)
            effectif[champ] = env.get(champ) or "À CONFIRMER"
    return {
        "responsabilite": "saisie éditeur — responsabilité 2AàZ",
        "a_confirmer": n_saisis < len(CHAMPS_MENTIONS),
        "saisie_editeur": saisie,
        "depuis_env": env,
        "effectif": effectif,
        "note": (
            "Champs vides ou « À CONFIRMER » : pas d'invention. "
            "RCCM / IDU / régime TVA fournis par 2AàZ uniquement."
        ),
    }


def ecrire_mentions_facture(
    session: Session,
    mentions: dict[str, Any],
    *,
    par: str | None,
) -> dict[str, Any]:
    out: dict[str, str | None] = {}
    for champ in CHAMPS_MENTIONS:
        if champ not in mentions:
            out[champ] = None
            continue
        raw = mentions.get(champ)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            out[champ] = None
        else:
            out[champ] = str(raw).strip()
    _set(session, CLE_MENTIONS, out, par=par)
    return lire_mentions_facture(session)


def prix_effectif_xof(session: Session, palier: str) -> Decimal:
    grille = lire_grille_paliers(session)
    raw = grille["effectif"]["prix_mensuel_xof"].get(palier)
    if raw is None:
        raise ValueError(f"palier inconnu : {palier!r}")
    return Decimal(str(raw))


def missions_effectives(session: Session, palier: str) -> int:
    grille = lire_grille_paliers(session)
    val = grille["effectif"]["missions_par_palier"].get(palier)
    if val is None:
        raise ValueError(f"palier inconnu : {palier!r}")
    return int(val)


def resume_parametres_editeur(session: Session) -> dict[str, Any]:
    """Payload UI Paramètres billing — jamais la clé Resend en clair."""
    resend = statut_resend()
    # Ne jamais exposer la clé ; seulement booléen + from si configuré.
    return {
        "responsabilite": "saisie éditeur — responsabilité 2AàZ",
        "paliers": lire_grille_paliers(session),
        "mentions_facture": lire_mentions_facture(session),
        "resend": {
            "configure": bool(resend.get("resend_configure")),
            "from": resend.get("resend_from"),
            "mode_sans_cle": resend.get("mode_sans_cle"),
            "note": resend.get("note"),
            "doc_env": (
                "Définir RESEND_API_KEY et RESEND_FROM dans `.env` "
                "(voir `.env.example`). La clé n'est jamais renvoyée au frontend."
            ),
        },
    }


LIBELLES_MENTIONS: Final[dict[str, str]] = {
    "raison_sociale": "Raison sociale",
    "siege": "Siège social",
    "rccm": "RCCM",
    "idu": "IDU",
    "compte_bancaire": "Compte bancaire",
    "regime_tva": "Régime TVA",
    "taux_tva": "Taux TVA",
}


def _est_placeholder_a_confirmer(valeur: str | None) -> bool:
    if valeur is None or not str(valeur).strip():
        return True
    u = str(valeur).strip().upper().replace("À", "A")
    return u in {"A CONFIRMER", "A_CONFIRMER"} or "A CONFIRMER" in u


def resume_tarifs_mentions_lecture_seule(session: Session) -> dict[str, Any]:
    """Inventaire lecture seule : paliers / quotas / prix / mentions a_confirmer.

    Aucune écriture. Ne présente jamais le provisoire technique comme grille
    commerciale officielle 2AàZ.
    """
    grille = lire_grille_paliers(session)
    mentions = lire_mentions_facture(session)
    effectif = grille["effectif"]
    saisie_p = grille["saisie_editeur"]
    source_grille = effectif["source"]
    paliers_out: list[dict[str, Any]] = []
    for palier in sorted(PALIERS_VALIDES):
        prix_saisi = (saisie_p.get("prix_mensuel_xof") or {}).get(palier)
        miss_saisi = (saisie_p.get("missions_par_palier") or {}).get(palier)
        prix_effectif = effectif["prix_mensuel_xof"][palier]
        miss_effectif = effectif["missions_par_palier"][palier]
        prix_provisoire = prix_saisi is None
        miss_provisoire = miss_saisi is None
        paliers_out.append(
            {
                "palier": palier,
                "prix_mensuel_xof": prix_effectif,
                "missions_par_mois": miss_effectif,
                "prix_statut": (
                    "saisie_editeur" if not prix_provisoire else "provisoire_technique"
                ),
                "missions_statut": (
                    "saisie_editeur" if not miss_provisoire else "provisoire_technique"
                ),
                "a_confirmer": prix_provisoire or miss_provisoire,
                "label": (
                    "Saisie éditeur 2AàZ"
                    if not prix_provisoire and not miss_provisoire
                    else "Provisoire technique — à valider 2AàZ"
                ),
            }
        )

    env = mentions["depuis_env"]
    saisie_m = mentions["saisie_editeur"]
    effectif_m = mentions["effectif"]
    champs_out: list[dict[str, Any]] = []
    for champ in CHAMPS_MENTIONS:
        val_eff = effectif_m.get(champ) or "À CONFIRMER"
        val_saisie = saisie_m.get(champ)
        a_conf = _est_placeholder_a_confirmer(val_eff)
        if val_saisie and not _est_placeholder_a_confirmer(val_saisie):
            source = "saisie_editeur"
        elif env.get(champ) and not _est_placeholder_a_confirmer(env.get(champ)):
            source = "env"
        else:
            source = "defaut_a_confirmer"
        champs_out.append(
            {
                "cle": champ,
                "libelle": LIBELLES_MENTIONS.get(champ, champ),
                "valeur_effective": val_eff,
                "a_confirmer": a_conf,
                "source": source,
            }
        )

    n_paliers_ac = sum(1 for p in paliers_out if p["a_confirmer"])
    n_mentions_ac = sum(1 for c in champs_out if c["a_confirmer"])
    return {
        "lecture_seule": True,
        "edition": False,
        "responsabilite": "affichage honnête — validation commerciale / juridique 2AàZ",
        "avertissement": (
            "Panneau lecture seule. Les montants provisoires ne sont pas une offre "
            "commerciale certifiée. Mentions vides / « À CONFIRMER » : pas d'invention "
            "(RCCM, IDU, TVA…). Saisie officielle via Paramètres si 2AàZ fournit."
        ),
        "doc_bloqueurs": "docs/15-bloqueurs-humains.md",
        "tarifs": {
            "tarifs_a_confirmer": bool(grille["tarifs_a_confirmer"]),
            "source_effectif": source_grille,
            "avertissement": grille["avertissement"],
            "paliers": paliers_out,
            "resume": {
                "paliers_a_confirmer": n_paliers_ac,
                "paliers_total": len(paliers_out),
            },
        },
        "mentions_facture": {
            "a_confirmer": bool(mentions["a_confirmer"]),
            "note": mentions["note"],
            "champs": champs_out,
            "resume": {
                "champs_a_confirmer": n_mentions_ac,
                "champs_total": len(champs_out),
            },
        },
        "bloqueurs_ouverts": {
            "tarifs": bool(grille["tarifs_a_confirmer"]),
            "mentions_facture": bool(mentions["a_confirmer"]),
        },
    }
