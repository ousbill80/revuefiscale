"""Orchestration de la restitution d une mission."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.restitution.passage import Passage, construire_passage
from backend.restitution.rapport import rendre_rapport_markdown
from backend.restitution.risques import ScoreRisque, scorer_risques


class ErreurRestitution(Exception):
    """Echec de production de la restitution."""


@dataclass(frozen=True)
class Restitution:
    mission_id: int
    execution_id: int | None
    passage: Passage
    score_risque: ScoreRisque
    conclusions: tuple[dict[str, Any], ...]
    rapport_markdown: str
    version_referentiel_id: int | None = None
    version_referentiel_libelle: str | None = None
    a_confirmer_regles: tuple[dict[str, Any], ...] = ()
    a_confirmer_total: int = 0
    identification: dict[str, Any] | None = None


def _charger_meta(session: Session, mission_id: int) -> dict[str, Any]:
    from backend.plateforme.missions import (
        LIBELLES_ENGAGEMENT,
        normaliser_perimetre_lu,
    )

    row = session.execute(
        text(
            "SELECT m.id AS mission_id, m.exercice, m.profil, m.statut, "
            "m.version_referentiel_id, v.libelle AS version_referentiel_libelle, "
            "m.type_engagement, m.perimetre_impots, m.exclusions_declarees, "
            "m.seuil_signification, m.contribuable_id, "
            "c.denomination AS contribuable_denomination, "
            "c.ncc AS contribuable_ncc, "
            "c.rccm AS contribuable_rccm, "
            "c.dfe AS contribuable_dfe, "
            "c.forme AS contribuable_forme, "
            "c.forme_juridique AS contribuable_forme_juridique, "
            "c.regime_fiscal AS contribuable_regime_fiscal, "
            "c.siege_social AS contribuable_siege, "
            "c.commune AS contribuable_commune, "
            "c.centre_impots AS contribuable_centre_impots "
            "FROM mission m "
            "JOIN contribuable c ON c.id = m.contribuable_id "
            "LEFT JOIN version_referentiel v ON v.id = m.version_referentiel_id "
            "WHERE m.id = :m"
        ),
        {"m": mission_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurRestitution(f"mission {mission_id} introuvable")
    meta = dict(row)
    type_eng = str(meta.get("type_engagement") or "autre")
    meta["type_engagement"] = type_eng
    meta["type_engagement_libelle"] = LIBELLES_ENGAGEMENT.get(type_eng, type_eng)
    meta["perimetre_impots"] = normaliser_perimetre_lu(meta.get("perimetre_impots"))
    meta["revue_partielle"] = meta["perimetre_impots"] is not None
    seuil = meta.get("seuil_signification")
    meta["seuil_signification"] = str(seuil) if seuil is not None else None

    from backend.plateforme.objectifs import lister_objectifs_en_contexte
    from backend.plateforme.objectifs_fiscaux import (
        lister_objectifs_fiscaux_en_contexte,
    )

    meta["objectifs"] = lister_objectifs_en_contexte(session, mission_id)
    meta["objectifs_fiscaux"] = lister_objectifs_fiscaux_en_contexte(
        session, mission_id
    )
    return meta


def _derniere_execution(session: Session, mission_id: int) -> int | None:
    return session.execute(
        text(
            "SELECT id FROM execution WHERE mission_id = :m "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()


def _charger_conclusions(
    session: Session, execution_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT c.id, rv.regle_id, c.montant, c.sens, c.niveau_risque, "
            "c.commentaire, c.statut, c.piece_mission_id, c.amendee_par, "
            "c.valide_par, c.valide_le "
            "FROM conclusion c "
            "JOIN regle_version rv ON rv.id = c.regle_version_id "
            "WHERE c.execution_id = :e "
            "ORDER BY rv.regle_id"
        ),
        {"e": execution_id},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        montant = r["montant"]
        out.append(
            {
                "id": int(r["id"]),
                "regle_id": str(r["regle_id"]),
                "montant": Decimal(montant) if montant is not None else None,
                "sens": r["sens"],
                "niveau_risque": str(r["niveau_risque"]),
                "commentaire": r["commentaire"],
                "statut": str(r["statut"] or "anomalie"),
                "piece_mission_id": (
                    int(r["piece_mission_id"])
                    if r.get("piece_mission_id") is not None
                    else None
                ),
                "amendee_par": r.get("amendee_par"),
                "valide_par": r.get("valide_par"),
                "valide_le": (
                    r["valide_le"].isoformat()
                    if r.get("valide_le") is not None
                    else None
                ),
            }
        )
    return out


def _a_confirmer_regles_touchees(
    session: Session,
    *,
    version_id: int | None,
    regle_ids: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Mentions ``a_confirmer`` des règles touchées (version épinglée).

    Lecture seule depuis ``regle_version`` — ne valide / ne purge rien.
    """
    if version_id is None or not regle_ids:
        return [], 0
    rows = session.execute(
        text(
            "SELECT regle_id, a_confirmer FROM regle_version "
            "WHERE version_referentiel_id = :v AND regle_id IN :ids "
            "ORDER BY regle_id"
        ).bindparams(bindparam("ids", expanding=True)),
        {"v": version_id, "ids": list(regle_ids)},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    total = 0
    for r in rows:
        ment = list(r["a_confirmer"] or [])
        ment_txt = [str(x) for x in ment if str(x).strip()]
        if not ment_txt:
            continue
        total += len(ment_txt)
        out.append(
            {
                "regle_id": str(r["regle_id"]),
                "nb": len(ment_txt),
                "mentions": ment_txt,
            }
        )
    return out, total


def _serialiser_entree_audit(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise une ligne journal pour l'API (horodatage ISO, hash tronqué)."""
    horodatage = row.get("horodatage")
    if hasattr(horodatage, "isoformat"):
        horodatage = horodatage.isoformat()
    charge = row.get("charge_utile")
    if charge is None:
        charge = {}
    elif not isinstance(charge, dict):
        charge = {"brut": charge}
    hash_plein = str(row.get("hash") or "")
    hash_prec = row.get("hash_prec")
    return {
        "id": int(row["id"]) if row.get("id") is not None else None,
        "horodatage": horodatage,
        "acteur": str(row.get("acteur") or ""),
        "action": str(row.get("action") or ""),
        "charge_utile": charge,
        "hash": hash_plein,
        "hash_court": hash_plein[:12] if hash_plein else None,
        "hash_prec": str(hash_prec) if hash_prec else None,
    }


def _extrait_audit(
    session: Session, mission_id: int, *, limite: int = 20
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, horodatage, acteur, action, charge_utile, hash_prec, hash "
            "FROM journal_audit WHERE mission_id = :m "
            "ORDER BY id DESC LIMIT :n"
        ),
        {"m": mission_id, "n": limite},
    ).mappings().all()
    return [_serialiser_entree_audit(dict(r)) for r in rows]


def _synthese_audit(entrees: list[dict[str, Any]]) -> dict[str, Any]:
    """Comptages par action — lecture seule, aucun calcul fiscal."""
    par_action: dict[str, int] = {}
    for e in entrees:
        act = str(e.get("action") or "inconnu")
        par_action[act] = par_action.get(act, 0) + 1
    return {
        "total": len(entrees),
        "par_action": dict(sorted(par_action.items())),
        "ecriture_seule": True,
        "chaine_hash": True,
        "note": (
            "Journal en écriture seule, chaîné par hash. "
            "Traçabilité des événements dossier — pas une source de droit."
        ),
    }


def produire_restitution(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> Restitution:
    """Charge la derniere execution et produit passage + rapport markdown."""
    with contexte_tenant(session, tenant_id):
        meta = _charger_meta(session, mission_id)
        exec_id = _derniere_execution(session, mission_id)
        conclusions: list[dict[str, Any]] = []
        if exec_id is not None:
            conclusions = _charger_conclusions(session, int(exec_id))

        from backend.plateforme.taches import lister_taches_mission

        # Liste hors contexte_tenant de lister (elle pose le sien) — appeler après.
        passage = construire_passage(conclusions)
        score = scorer_risques(conclusions)
        audit = _extrait_audit(session, mission_id)
        vid = meta.get("version_referentiel_id")
        regle_ids = sorted({str(c["regle_id"]) for c in conclusions if c.get("regle_id")})
        ac_liste, ac_total = _a_confirmer_regles_touchees(
            session,
            version_id=int(vid) if vid is not None else None,
            regle_ids=regle_ids,
        )
        meta_rapport = dict(meta)
        meta_rapport["a_confirmer_total"] = ac_total
        meta_rapport["a_confirmer_regles"] = ac_liste
        markdown = rendre_rapport_markdown(
            meta=meta_rapport,
            passage=passage,
            conclusions=conclusions,
            score=score,
            extrait_audit=audit,
        )

    taches = lister_taches_mission(
        session, tenant_id, mission_id, ouvertes_seulement=False
    )
    relances = [
        t
        for t in taches
        if t.get("statut") == "bloquee" and t.get("piece_attendue")
    ]

    return Restitution(
        mission_id=mission_id,
        execution_id=int(exec_id) if exec_id is not None else None,
        passage=passage,
        score_risque=score,
        conclusions=tuple(conclusions),
        rapport_markdown=markdown,
        version_referentiel_id=int(vid) if vid is not None else None,
        version_referentiel_libelle=(
            str(meta["version_referentiel_libelle"])
            if meta.get("version_referentiel_libelle")
            else None
        ),
        a_confirmer_regles=tuple(ac_liste),
        a_confirmer_total=ac_total,
        identification={
            "contribuable_id": (
                int(meta["contribuable_id"])
                if meta.get("contribuable_id") is not None
                else None
            ),
            "contribuable_denomination": meta.get("contribuable_denomination"),
            "contribuable_ncc": meta.get("contribuable_ncc"),
            "contribuable_rccm": meta.get("contribuable_rccm"),
            "contribuable_dfe": meta.get("contribuable_dfe"),
            "contribuable_forme": meta.get("contribuable_forme"),
            "contribuable_forme_juridique": meta.get(
                "contribuable_forme_juridique"
            ),
            "contribuable_regime_fiscal": meta.get("contribuable_regime_fiscal"),
            "contribuable_siege": meta.get("contribuable_siege"),
            "contribuable_commune": meta.get("contribuable_commune"),
            "contribuable_centre_impots": meta.get(
                "contribuable_centre_impots"
            ),
            "exercice": meta.get("exercice"),
            "statut": meta.get("statut"),
            "profil": meta.get("profil") or {},
            "type_engagement": meta.get("type_engagement"),
            "type_engagement_libelle": meta.get("type_engagement_libelle"),
            "perimetre_impots": meta.get("perimetre_impots"),
            "revue_partielle": bool(meta.get("revue_partielle")),
            "exclusions_declarees": meta.get("exclusions_declarees"),
            "seuil_signification": meta.get("seuil_signification"),
            "objectifs": meta.get("objectifs") or [],
            "objectifs_fiscaux": meta.get("objectifs_fiscaux") or [],
            "taches": taches,
            "relances_client": relances,
        },
    )


def lire_audit(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Lecture seule du journal d audit d une mission (RLS via contexte)."""
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurRestitution(f"mission {mission_id} introuvable")
        return _extrait_audit(session, mission_id, limite=limite)


def produire_audit(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    limite: int = 50,
) -> dict[str, Any]:
    """Payload API audit : entrées + synthèse (pas de montants inventés)."""
    entrees = lire_audit(session, tenant_id, mission_id, limite=limite)
    return {
        "mission_id": mission_id,
        "limite": limite,
        "entrees": entrees,
        "synthese": _synthese_audit(entrees),
    }


def restitution_vers_dict(r: Restitution) -> dict[str, Any]:
    """Serialisation API."""
    return {
        "mission_id": r.mission_id,
        "execution_id": r.execution_id,
        "version_referentiel_id": r.version_referentiel_id,
        "version_referentiel_libelle": r.version_referentiel_libelle,
        "a_confirmer_total": r.a_confirmer_total,
        "a_confirmer_regles": list(r.a_confirmer_regles),
        "avertissement_a_confirmer": (
            "Paramètres issus du référentiel encore marqués a_confirmer — "
            "transparence éditoriale, pas un stop d'exécution. "
            "Ne constituent pas du droit positif certifié."
            if r.a_confirmer_total > 0
            else None
        ),
        "passage": {
            "lignes": [asdict(ligne) for ligne in r.passage.lignes],
            "total_reintegration": r.passage.total_reintegration,
            "total_deduction": r.passage.total_deduction,
            "solde_net": r.passage.solde_net,
        },
        "score_risque": {
            "score": r.score_risque.score,
            "comptages": r.score_risque.comptages,
            "avertissement": r.score_risque.avertissement,
        },
        "conclusions": list(r.conclusions),
        "rapport_markdown": r.rapport_markdown,
        "identification": r.identification or {},
    }
