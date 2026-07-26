"""Objectifs fiscaux de mission (impôt + exercices) — source du périmètre.

Distinct de ``mission_objectif`` (libellés libres lettre, hors moteur).
"""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

MOTIF_HORS_DEFAUT: Final = "Hors périmètre déclaré (lettre de mission)"
_STATUT_CADRAGE: Final = "cadrage"


class ErreurObjectifFiscal(Exception):
    """Echec CRUD objectifs fiscaux."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    exercices = row.get("exercices") or []
    if isinstance(exercices, str):
        exercices = [exercices]
    return {
        "id": int(row["id"]),
        "mission_id": int(row["mission_id"]),
        "impot": str(row["impot"]).upper(),
        "exercices": [int(x) for x in exercices],
        "dans_perimetre": bool(row["dans_perimetre"]),
        "motif_exclusion": row.get("motif_exclusion"),
    }


def lister_objectifs_fiscaux_en_contexte(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, mission_id, impot, exercices, dans_perimetre, "
            "motif_exclusion FROM objectif WHERE mission_id = :m "
            "ORDER BY impot ASC, id ASC"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [_serialiser(dict(r)) for r in rows]


def lister_objectifs_fiscaux(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        mid = session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if mid is None:
            raise ErreurObjectifFiscal(f"mission {mission_id} introuvable")
        return lister_objectifs_fiscaux_en_contexte(session, mission_id)


def perimetre_depuis_objectifs(
    objectifs: list[dict[str, Any]],
) -> list[str] | None:
    """NULL = tous (aucune ligne ou toutes dans_perimetre) ; sinon codes in."""
    from backend.plateforme.missions import CODES_IMPOT

    if not objectifs:
        return None
    inclus = [
        str(o["impot"]).upper()
        for o in objectifs
        if o.get("dans_perimetre")
    ]
    if not inclus:
        raise ErreurObjectifFiscal(
            "au moins un objectif doit être dans le périmètre "
            "(ou liste vide = tous via perimetre null)"
        )
    # Si tous les codes pivot sont inclus → équivalent « tous »
    if set(inclus) >= set(CODES_IMPOT):
        return None
    return inclus


def _exiger_cadrage(session: Session, mission_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT id, statut, exercice FROM mission WHERE id = :m"
        ),
        {"m": mission_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurObjectifFiscal(f"mission {mission_id} introuvable")
    statut = str(row["statut"] or _STATUT_CADRAGE).lower()
    if statut != _STATUT_CADRAGE:
        raise ErreurObjectifFiscal(
            f"cadrage figé (statut={statut}) — objectifs fiscaux non modifiables"
        )
    return dict(row)


def synchroniser_depuis_perimetre(
    session: Session,
    tenant_id: int,
    mission_id: int,
    perimetre: list[str] | None,
    *,
    exercice: int,
    verifier_cadrage: bool = True,
) -> list[dict[str, Any]]:
    """Matérialise une ligne ``objectif`` par code pivot (revue partielle).

    ``perimetre is None`` → supprime les lignes (comportement « tous »).
    """
    from backend.plateforme.missions import CODES_IMPOT, valider_perimetre_impots

    perimetre_ok = valider_perimetre_impots(perimetre)

    with contexte_tenant(session, tenant_id):
        if verifier_cadrage:
            _exiger_cadrage(session, mission_id)
        else:
            mid = session.execute(
                text("SELECT id FROM mission WHERE id = :m"),
                {"m": mission_id},
            ).scalar_one_or_none()
            if mid is None:
                raise ErreurObjectifFiscal(f"mission {mission_id} introuvable")

        session.execute(
            text("DELETE FROM objectif WHERE mission_id = :m"),
            {"m": mission_id},
        )
        if perimetre_ok is None:
            session.flush()
            return []

        inclus = set(perimetre_ok)
        for code in CODES_IMPOT:
            dans = code in inclus
            session.execute(
                text(
                    "INSERT INTO objectif "
                    "(tenant_id, mission_id, impot, exercices, "
                    "dans_perimetre, motif_exclusion) "
                    "VALUES (:t, :m, :imp, :ex, :dans, :mot)"
                ),
                {
                    "t": tenant_id,
                    "m": mission_id,
                    "imp": code,
                    "ex": [int(exercice)],
                    "dans": dans,
                    "mot": None if dans else MOTIF_HORS_DEFAUT,
                },
            )
        session.flush()
        return lister_objectifs_fiscaux_en_contexte(session, mission_id)


def remplacer_objectifs_fiscaux(
    session: Session,
    tenant_id: int,
    mission_id: int,
    objectifs: object | None,
    *,
    verifier_cadrage: bool = True,
) -> tuple[list[dict[str, Any]], list[str] | None]:
    """Remplace les objectifs fiscaux et retourne (lignes, perimetre dérivé)."""
    from backend.plateforme.missions import CODES_IMPOT, CODES_IMPOT_SET

    if objectifs is None:
        objectifs = []
    if not isinstance(objectifs, (list, tuple)):
        raise ErreurObjectifFiscal("objectifs_fiscaux doit être une liste")

    normalises: list[dict[str, Any]] = []
    vus: set[str] = set()
    for i, brut in enumerate(objectifs):
        if not isinstance(brut, dict):
            raise ErreurObjectifFiscal(
                f"objectifs_fiscaux[{i}] invalide — attendu objet"
            )
        code = str(brut.get("impot") or "").strip().upper()
        if code not in CODES_IMPOT_SET:
            raise ErreurObjectifFiscal(
                f"code impot invalide {brut.get('impot')!r} — attendu : "
                + ", ".join(CODES_IMPOT)
            )
        if code in vus:
            raise ErreurObjectifFiscal(f"impôt en double : {code}")
        vus.add(code)
        exercices_brut = brut.get("exercices")
        if exercices_brut is None:
            raise ErreurObjectifFiscal(
                f"objectifs_fiscaux[{i}] : exercices obligatoires"
            )
        if not isinstance(exercices_brut, (list, tuple)) or len(exercices_brut) < 1:
            raise ErreurObjectifFiscal(
                f"objectifs_fiscaux[{i}] : exercices doit être une liste non vide"
            )
        exercices = [int(x) for x in exercices_brut]
        dans = bool(brut.get("dans_perimetre", True))
        motif = brut.get("motif_exclusion")
        if motif is not None:
            motif = str(motif).strip() or None
        if not dans and not motif:
            motif = MOTIF_HORS_DEFAUT
        if dans:
            motif = None
        normalises.append(
            {
                "impot": code,
                "exercices": exercices,
                "dans_perimetre": dans,
                "motif_exclusion": motif,
            }
        )

    with contexte_tenant(session, tenant_id):
        if verifier_cadrage:
            _exiger_cadrage(session, mission_id)
        else:
            mid = session.execute(
                text("SELECT id FROM mission WHERE id = :m"),
                {"m": mission_id},
            ).scalar_one_or_none()
            if mid is None:
                raise ErreurObjectifFiscal(f"mission {mission_id} introuvable")

        session.execute(
            text("DELETE FROM objectif WHERE mission_id = :m"),
            {"m": mission_id},
        )
        for o in normalises:
            session.execute(
                text(
                    "INSERT INTO objectif "
                    "(tenant_id, mission_id, impot, exercices, "
                    "dans_perimetre, motif_exclusion) "
                    "VALUES (:t, :m, :imp, :ex, :dans, :mot)"
                ),
                {
                    "t": tenant_id,
                    "m": mission_id,
                    "imp": o["impot"],
                    "ex": o["exercices"],
                    "dans": o["dans_perimetre"],
                    "mot": o["motif_exclusion"],
                },
            )
        session.flush()
        rows = lister_objectifs_fiscaux_en_contexte(session, mission_id)

    return rows, perimetre_depuis_objectifs(rows)


def assurer_objectif_pour_impot(
    session: Session,
    tenant_id: int,
    mission_id: int,
    impot: str,
    exercice: int,
    *,
    dans_perimetre: bool = True,
) -> int:
    """Upsert minimal pour matérialisation de tâches (contexte tenant posé)."""
    code = str(impot).strip().upper()
    row = session.execute(
        text(
            "SELECT id FROM objectif "
            "WHERE mission_id = :m AND impot = :imp"
        ),
        {"m": mission_id, "imp": code},
    ).mappings().one_or_none()
    if row is not None:
        return int(row["id"])
    oid = session.execute(
        text(
            "INSERT INTO objectif "
            "(tenant_id, mission_id, impot, exercices, dans_perimetre, "
            "motif_exclusion) "
            "VALUES (:t, :m, :imp, :ex, :dans, :mot) RETURNING id"
        ),
        {
            "t": tenant_id,
            "m": mission_id,
            "imp": code,
            "ex": [int(exercice)],
            "dans": dans_perimetre,
            "mot": None if dans_perimetre else MOTIF_HORS_DEFAUT,
        },
    ).scalar_one()
    return int(oid)
