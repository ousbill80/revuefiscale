"""Validation humaine des conclusions (statut + pièce dossier)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.moteur.calcul import STATUTS_CONCLUSION
from backend.moteur.journal import append_journal
from backend.plateforme.contexte import contexte_tenant


class ErreurConclusion(Exception):
    """Echec lecture / amendement conclusion."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    montant = row.get("montant")
    valide_le = row.get("valide_le")
    comptes_source = row.get("comptes_source")
    if not isinstance(comptes_source, list):
        comptes_source = []
    return {
        "id": int(row["id"]),
        "execution_id": int(row["execution_id"]),
        "mission_id": int(row["mission_id"]),
        "regle_id": str(row["regle_id"]),
        "regle_version_id": int(row["regle_version_id"]),
        "montant": str(montant) if montant is not None else None,
        "sens": row.get("sens"),
        "niveau_risque": str(row["niveau_risque"]),
        "commentaire": row.get("commentaire"),
        "statut": str(row.get("statut") or "anomalie"),
        "piece_mission_id": (
            int(row["piece_mission_id"])
            if row.get("piece_mission_id") is not None
            else None
        ),
        "amendee_par": row.get("amendee_par"),
        "valide_par": row.get("valide_par"),
        "valide_le": (
            valide_le.isoformat()
            if hasattr(valide_le, "isoformat")
            else valide_le
        ),
        "comptes_source": comptes_source,
    }


def lire_conclusion(
    session: Session,
    tenant_id: int,
    mission_id: int,
    conclusion_id: int,
) -> dict[str, Any]:
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT c.id, c.execution_id, c.regle_version_id, c.montant, c.sens, "
                "c.niveau_risque, c.commentaire, c.statut, c.piece_mission_id, "
                "c.amendee_par, c.valide_par, c.valide_le, c.comptes_source, "
                "e.mission_id, rv.regle_id "
                "FROM conclusion c "
                "JOIN execution e ON e.id = c.execution_id "
                "JOIN regle_version rv ON rv.id = c.regle_version_id "
                "WHERE c.id = :cid AND e.mission_id = :mid"
            ),
            {"cid": conclusion_id, "mid": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurConclusion(
                f"conclusion {conclusion_id} introuvable pour mission {mission_id}"
            )
        return _serialiser(dict(row))


def patcher_conclusion(
    session: Session,
    tenant_id: int,
    mission_id: int,
    conclusion_id: int,
    *,
    acteur: str,
    statut: object | None = ...,
    piece_mission_id: object | None = ...,
) -> dict[str, Any]:
    """Amendement humain — statut et/ou rattachement pièce (même mission)."""
    champs = {
        "statut": statut is not ...,
        "piece_mission_id": piece_mission_id is not ...,
    }
    if not any(champs.values()):
        raise ErreurConclusion("aucun champ fourni (statut ou piece_mission_id)")

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT c.id, c.execution_id, c.regle_version_id, c.montant, c.sens, "
                "c.niveau_risque, c.commentaire, c.statut, c.piece_mission_id, "
                "c.amendee_par, c.valide_par, c.valide_le, e.mission_id, rv.regle_id "
                "FROM conclusion c "
                "JOIN execution e ON e.id = c.execution_id "
                "JOIN regle_version rv ON rv.id = c.regle_version_id "
                "WHERE c.id = :cid AND e.mission_id = :mid"
            ),
            {"cid": conclusion_id, "mid": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurConclusion(
                f"conclusion {conclusion_id} introuvable pour mission {mission_id}"
            )

        ancien = dict(row)
        nouveau_statut = str(ancien.get("statut") or "anomalie")
        if champs["statut"]:
            if statut is None:
                raise ErreurConclusion("statut ne peut pas être null")
            st = str(statut).strip().lower()
            if st not in STATUTS_CONCLUSION:
                raise ErreurConclusion(
                    f"statut invalide {statut!r} — attendu : "
                    + ", ".join(sorted(STATUTS_CONCLUSION))
                )
            nouveau_statut = st

        nouvelle_piece = ancien.get("piece_mission_id")
        if champs["piece_mission_id"]:
            if piece_mission_id is None:
                nouvelle_piece = None
            else:
                pid = int(piece_mission_id)
                piece = session.execute(
                    text(
                        "SELECT id, mission_id, tenant_id FROM piece_mission "
                        "WHERE id = :p"
                    ),
                    {"p": pid},
                ).mappings().one_or_none()
                if piece is None:
                    raise ErreurConclusion(f"piece_mission {pid} introuvable")
                if int(piece["mission_id"]) != mission_id:
                    raise ErreurConclusion(
                        f"piece_mission {pid} n'appartient pas à la mission {mission_id}"
                    )
                if int(piece["tenant_id"]) != tenant_id:
                    raise ErreurConclusion(
                        f"piece_mission {pid} hors tenant"
                    )
                nouvelle_piece = pid

        statut_change = champs["statut"] and nouveau_statut != str(
            ancien.get("statut") or "anomalie"
        )
        if statut_change:
            # Ré-amendement : la validation « 4 yeux » tombe.
            sql = (
                "UPDATE conclusion SET statut = :st, piece_mission_id = :p, "
                "amendee_par = :a, valide_par = NULL, valide_le = NULL "
                "WHERE id = :cid"
            )
        else:
            sql = (
                "UPDATE conclusion SET statut = :st, piece_mission_id = :p, "
                "amendee_par = :a WHERE id = :cid"
            )
        session.execute(
            text(sql),
            {
                "st": nouveau_statut,
                "p": nouvelle_piece,
                "a": acteur,
                "cid": conclusion_id,
            },
        )
        # Miroir tâche liée (même statut résultat)
        if champs["statut"]:
            session.execute(
                text(
                    "UPDATE tache SET statut = :st, maj_le = now() "
                    "WHERE conclusion_id = :cid"
                ),
                {"st": nouveau_statut, "cid": conclusion_id},
            )
        session.flush()

        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action="amendement_conclusion",
            charge_utile={
                "conclusion_id": conclusion_id,
                "regle_id": str(ancien["regle_id"]),
                "statut_precedent": str(ancien.get("statut") or "anomalie"),
                "statut": nouveau_statut,
                "piece_mission_id_precedent": (
                    int(ancien["piece_mission_id"])
                    if ancien.get("piece_mission_id") is not None
                    else None
                ),
                "piece_mission_id": (
                    int(nouvelle_piece) if nouvelle_piece is not None else None
                ),
            },
        )

        return lire_conclusion(session, tenant_id, mission_id, conclusion_id)


def valider_conclusion(
    session: Session,
    tenant_id: int,
    mission_id: int,
    conclusion_id: int,
    validateur: str,
) -> dict[str, Any]:
    """Validation « 4 yeux » : second regard sur une conclusion évaluée."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT c.id, c.statut, c.amendee_par, c.valide_par, "
                "e.mission_id, rv.regle_id "
                "FROM conclusion c "
                "JOIN execution e ON e.id = c.execution_id "
                "JOIN regle_version rv ON rv.id = c.regle_version_id "
                "WHERE c.id = :cid AND e.mission_id = :mid"
            ),
            {"cid": conclusion_id, "mid": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurConclusion(
                f"conclusion {conclusion_id} introuvable pour mission {mission_id}"
            )
        if not row.get("amendee_par"):
            raise ErreurConclusion(
                f"conclusion {conclusion_id} non évaluée — statuez sur le "
                "contrôle (anomalie, conforme, sous seuil ou non vérifiable "
                "motivé) avant de la valider"
            )

        session.execute(
            text(
                "UPDATE conclusion SET valide_par = :v, valide_le = now() "
                "WHERE id = :cid"
            ),
            {"v": validateur, "cid": conclusion_id},
        )
        session.flush()

        charge: dict[str, Any] = {
            "conclusion_id": conclusion_id,
            "regle_id": str(row["regle_id"]),
            "statut": str(row.get("statut") or "anomalie"),
            "amendee_par": row.get("amendee_par"),
        }
        if validateur == row.get("amendee_par"):
            charge["avertissement"] = (
                "auto-validation : le validateur est aussi l'auteur de "
                "l'amendement — traçabilité seulement, aucun blocage"
            )
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=validateur,
            action="validation_conclusion",
            charge_utile=charge,
        )

        return lire_conclusion(session, tenant_id, mission_id, conclusion_id)
