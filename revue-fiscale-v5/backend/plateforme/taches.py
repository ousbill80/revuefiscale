"""Tâches de mission — machine à états (plan dérivé, hors LLM)."""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.moteur.calcul import STATUTS_CONCLUSION
from backend.moteur.journal import append_journal
from backend.plateforme.contexte import contexte_tenant

STATUTS_WORKFLOW: Final[frozenset[str]] = frozenset(
    {"a_faire", "en_cours", "bloquee"}
)
STATUTS_TACHE: Final[frozenset[str]] = frozenset(
    STATUTS_WORKFLOW | STATUTS_CONCLUSION
)
STATUTS_OUVERTS: Final[frozenset[str]] = frozenset(
    {
        "a_faire",
        "en_cours",
        "bloquee",
        "anomalie",
        "non_verifiable",
    }
)
STATUTS_TERMINAUX_OK: Final[frozenset[str]] = frozenset(
    {"conforme", "sous_seuil", "hors_perimetre"}
)
TYPES_EFFET_BLOCANTS: Final[frozenset[str]] = frozenset(
    {"remet_en_cause", "declenche"}
)


class ErreurTache(Exception):
    """Echec lecture / amendement tâche."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    bloquee = row.get("bloquee_par") or []
    if isinstance(bloquee, str):
        bloquee = []
    return {
        "id": int(row["id"]),
        "objectif_id": int(row["objectif_id"]),
        "mission_id": int(row["mission_id"]) if row.get("mission_id") is not None else None,
        "impot": str(row["impot"]) if row.get("impot") is not None else None,
        "regle_version_id": (
            int(row["regle_version_id"])
            if row.get("regle_version_id") is not None
            else None
        ),
        "regle_id": row.get("regle_id"),
        "statut": str(row.get("statut") or "a_faire"),
        "assignee_a": (
            int(row["assignee_a"])
            if row.get("assignee_a") is not None
            else None
        ),
        "bloquee_par": [int(x) for x in bloquee],
        "piece_attendue": row.get("piece_attendue"),
        "conclusion_id": (
            int(row["conclusion_id"])
            if row.get("conclusion_id") is not None
            else None
        ),
    }


def lister_taches_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    ouvertes_seulement: bool = False,
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        mid = session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if mid is None:
            raise ErreurTache(f"mission {mission_id} introuvable")
        rows = session.execute(
            text(
                "SELECT t.id, t.objectif_id, t.regle_version_id, t.statut, "
                "t.assignee_a, t.bloquee_par, t.piece_attendue, t.conclusion_id, "
                "o.mission_id, o.impot, rv.regle_id "
                "FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "LEFT JOIN regle_version rv ON rv.id = t.regle_version_id "
                "WHERE o.mission_id = :m "
                "ORDER BY o.impot ASC, rv.regle_id ASC NULLS LAST, t.id ASC"
            ),
            {"m": mission_id},
        ).mappings().all()
        out = [_serialiser(dict(r)) for r in rows]
        if ouvertes_seulement:
            out = [t for t in out if t["statut"] in STATUTS_OUVERTS]
        return out


def upsert_tache(
    session: Session,
    tenant_id: int,
    objectif_id: int,
    regle_version_id: int,
    *,
    statut: str = "a_faire",
    conclusion_id: int | None = None,
    piece_attendue: str | None = None,
) -> int:
    """Upsert (objectif, regle_version) — contexte tenant déjà posé."""
    st = str(statut).strip().lower()
    if st not in STATUTS_TACHE:
        raise ErreurTache(f"statut invalide {statut!r}")
    row = session.execute(
        text(
            "SELECT id, statut, conclusion_id FROM tache "
            "WHERE objectif_id = :o AND regle_version_id = :rv"
        ),
        {"o": objectif_id, "rv": regle_version_id},
    ).mappings().one_or_none()
    if row is None:
        tid = session.execute(
            text(
                "INSERT INTO tache "
                "(tenant_id, objectif_id, regle_version_id, statut, "
                "conclusion_id, piece_attendue) "
                "VALUES (:t, :o, :rv, :st, :cid, :pa) RETURNING id"
            ),
            {
                "t": tenant_id,
                "o": objectif_id,
                "rv": regle_version_id,
                "st": st,
                "cid": conclusion_id,
                "pa": piece_attendue,
            },
        ).scalar_one()
        return int(tid)

    tid = int(row["id"])
    actuel = str(row["statut"] or "a_faire")
    # Ne pas écraser un amendement humain (statuts résultat hors workflow).
    nouveau = (
        st
        if actuel in STATUTS_WORKFLOW or actuel == "anomalie"
        else actuel
    )
    session.execute(
        text(
            "UPDATE tache SET statut = :st, conclusion_id = COALESCE(:cid, conclusion_id), "
            "piece_attendue = COALESCE(:pa, piece_attendue), maj_le = now() "
            "WHERE id = :id"
        ),
        {
            "st": nouveau,
            "cid": conclusion_id,
            "pa": piece_attendue,
            "id": tid,
        },
    )
    return tid


def projeter_blocages_effets_croises(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> int:
    """Projette effet_croise → bloquee_par / statut bloquee (contexte posé).

    Retourne le nombre de tâches marquées bloquées.
    """
    taches = session.execute(
        text(
            "SELECT t.id, t.regle_version_id, t.statut, rv.regle_id "
            "FROM tache t "
            "JOIN objectif o ON o.id = t.objectif_id "
            "JOIN regle_version rv ON rv.id = t.regle_version_id "
            "WHERE o.mission_id = :m AND t.tenant_id = :t"
        ),
        {"m": mission_id, "t": tenant_id},
    ).mappings().all()
    if not taches:
        return 0

    par_regle: dict[str, dict[str, Any]] = {}
    par_rv: dict[int, dict[str, Any]] = {}
    for t in taches:
        d = dict(t)
        par_regle[str(d["regle_id"])] = d
        par_rv[int(d["regle_version_id"])] = d

    rv_ids = list(par_rv.keys())
    if not rv_ids:
        return 0

    effets = session.execute(
        text(
            "SELECT source_id, cible_regle, type FROM effet_croise "
            "WHERE source_id = ANY(:ids) AND type = ANY(:types)"
        ),
        {"ids": rv_ids, "types": list(TYPES_EFFET_BLOCANTS)},
    ).mappings().all()

    bloquants_par_cible: dict[int, set[int]] = {}
    for e in effets:
        source = par_rv.get(int(e["source_id"]))
        cible = par_regle.get(str(e["cible_regle"]))
        if source is None or cible is None:
            continue
        src_statut = str(source["statut"] or "a_faire")
        # Source encore ouverte → bloque la cible
        if src_statut in STATUTS_TERMINAUX_OK:
            continue
        if src_statut == "hors_perimetre":
            continue
        cid = int(cible["id"])
        bloquants_par_cible.setdefault(cid, set()).add(int(source["id"]))

    nb = 0
    for tid, deps in bloquants_par_cible.items():
        session.execute(
            text(
                "UPDATE tache SET bloquee_par = :bp, "
                "statut = CASE "
                "  WHEN statut IN ('a_faire', 'en_cours', 'bloquee') THEN 'bloquee' "
                "  ELSE statut END, "
                "maj_le = now() "
                "WHERE id = :id"
            ),
            {"bp": sorted(deps), "id": tid},
        )
        nb += 1

    # Nettoyer bloquee_par des tâches sans dépendance restante
    for t in taches:
        tid = int(t["id"])
        if tid in bloquants_par_cible:
            continue
        if t.get("bloquee_par"):
            session.execute(
                text(
                    "UPDATE tache SET bloquee_par = '{}', "
                    "statut = CASE WHEN statut = 'bloquee' THEN 'a_faire' "
                    "ELSE statut END, maj_le = now() WHERE id = :id"
                ),
                {"id": tid},
            )
    return nb


def patcher_tache(
    session: Session,
    tenant_id: int,
    mission_id: int,
    tache_id: int,
    *,
    acteur: str,
    statut: object | None = ...,
    piece_attendue: object | None = ...,
    assignee_a: object | None = ...,
) -> dict[str, Any]:
    """Amendement humain — synchro miroir conclusion.statut si liée."""
    champs = {
        "statut": statut is not ...,
        "piece_attendue": piece_attendue is not ...,
        "assignee_a": assignee_a is not ...,
    }
    if not any(champs.values()):
        raise ErreurTache(
            "aucun champ fourni (statut, piece_attendue ou assignee_a)"
        )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT t.id, t.objectif_id, t.regle_version_id, t.statut, "
                "t.assignee_a, t.bloquee_par, t.piece_attendue, t.conclusion_id, "
                "o.mission_id, o.impot, rv.regle_id "
                "FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "LEFT JOIN regle_version rv ON rv.id = t.regle_version_id "
                "WHERE t.id = :tid AND o.mission_id = :mid"
            ),
            {"tid": tache_id, "mid": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurTache(
                f"tache {tache_id} introuvable pour mission {mission_id}"
            )
        ancien = dict(row)

        nouveau_statut = str(ancien.get("statut") or "a_faire")
        if champs["statut"]:
            if statut is None:
                raise ErreurTache("statut ne peut pas être null")
            st = str(statut).strip().lower()
            if st not in STATUTS_TACHE:
                raise ErreurTache(
                    f"statut invalide {statut!r} — attendu : "
                    + ", ".join(sorted(STATUTS_TACHE))
                )
            nouveau_statut = st

        nouvelle_piece = ancien.get("piece_attendue")
        if champs["piece_attendue"]:
            nouvelle_piece = (
                None
                if piece_attendue is None
                else str(piece_attendue).strip() or None
            )

        nouvel_assignee = ancien.get("assignee_a")
        if champs["assignee_a"]:
            if assignee_a is None:
                nouvel_assignee = None
            else:
                uid = int(assignee_a)
                u = session.execute(
                    text(
                        "SELECT id FROM utilisateur "
                        "WHERE id = :u AND tenant_id = :t"
                    ),
                    {"u": uid, "t": tenant_id},
                ).scalar_one_or_none()
                if u is None:
                    raise ErreurTache(
                        f"utilisateur {uid} introuvable dans ce cabinet"
                    )
                nouvel_assignee = uid

        session.execute(
            text(
                "UPDATE tache SET statut = :st, piece_attendue = :pa, "
                "assignee_a = :aa, maj_le = now() WHERE id = :id"
            ),
            {
                "st": nouveau_statut,
                "pa": nouvelle_piece,
                "aa": nouvel_assignee,
                "id": tache_id,
            },
        )

        # Miroir conclusion si statut résultat
        cid = ancien.get("conclusion_id")
        if (
            cid is not None
            and champs["statut"]
            and nouveau_statut in STATUTS_CONCLUSION
        ):
            session.execute(
                text(
                    "UPDATE conclusion SET statut = :st, amendee_par = :a, "
                    "valide_par = CASE WHEN statut = :st THEN valide_par END, "
                    "valide_le = CASE WHEN statut = :st THEN valide_le END "
                    "WHERE id = :cid"
                ),
                {"st": nouveau_statut, "a": acteur, "cid": int(cid)},
            )

        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action="amendement_tache",
            charge_utile={
                "tache_id": tache_id,
                "regle_id": ancien.get("regle_id"),
                "statut_precedent": str(ancien.get("statut") or "a_faire"),
                "statut": nouveau_statut,
                "assignee_a": nouvel_assignee,
                "piece_attendue": nouvelle_piece,
            },
        )
        session.flush()

        rows = session.execute(
            text(
                "SELECT t.id, t.objectif_id, t.regle_version_id, t.statut, "
                "t.assignee_a, t.bloquee_par, t.piece_attendue, t.conclusion_id, "
                "o.mission_id, o.impot, rv.regle_id "
                "FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "LEFT JOIN regle_version rv ON rv.id = t.regle_version_id "
                "WHERE t.id = :tid"
            ),
            {"tid": tache_id},
        ).mappings().one()
        return _serialiser(dict(rows))


def creer_points_ouverts_depuis_anomalies(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> int:
    """DEPRECATED (R4) — ne plus appeler à la clôture.

    Conservée pour compatibilité import ; retourne toujours 0.
    La source N+1 est ``creer_risques_depuis_anomalies``.
    """
    del session, tenant_id, mission_id
    return 0
