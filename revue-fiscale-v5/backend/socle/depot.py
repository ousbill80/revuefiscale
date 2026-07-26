"""Acces base du socle — tables cloisonnees, filtre par RLS uniquement."""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.socle.modeles import LigneBalance


def mission_existe(session: Session, mission_id: int) -> bool:
    """Vrai si la mission est visible dans le contexte tenant courant."""
    return (
        session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        is not None
    )


def exercice_mission(session: Session, mission_id: int) -> int | None:
    """Exercice (année) de la mission — None si mission invisible."""
    valeur = session.execute(
        text("SELECT exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).scalar_one_or_none()
    return int(valeur) if valeur is not None else None


def inserer_controles_fec(
    session: Session,
    tenant_id: int,
    mission_id: int,
    exercice: int,
    controles: list[dict],
) -> int:
    """Trace les contrôles de vraisemblance FEC d'un import. Retourne l'id."""
    return int(
        session.execute(
            text(
                "INSERT INTO controle_source_fec "
                "(tenant_id, mission_id, exercice, controles) "
                "VALUES (:t, :m, :e, CAST(:c AS jsonb)) RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "e": exercice,
                "c": json.dumps(controles, ensure_ascii=False),
            },
        ).scalar_one()
    )


def derniers_controles_fec(session: Session, mission_id: int) -> dict | None:
    """Dernier jeu de contrôles FEC d'une mission (le plus récent)."""
    row = session.execute(
        text(
            "SELECT id, exercice, controles, cree_le "
            "FROM controle_source_fec WHERE mission_id = :m "
            "ORDER BY cree_le DESC, id DESC LIMIT 1"
        ),
        {"m": mission_id},
    ).mappings().first()
    return dict(row) if row else None


def remplacer_soldes(
    session: Session,
    tenant_id: int,
    mission_id: int,
    lignes: list[LigneBalance],
) -> None:
    """Remplace integralement les soldes d une mission."""
    session.execute(
        text("DELETE FROM solde_compte WHERE mission_id = :m"),
        {"m": mission_id},
    )
    for ligne in lignes:
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, :c, :l, :d, :cr)"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": ligne.compte,
                "l": ligne.libelle,
                "d": ligne.debit,
                "cr": ligne.credit,
            },
        )


def inserer_rapport(
    session: Session,
    tenant_id: int,
    mission_id: int,
    statut: str,
    anomalies: list[str],
) -> int:
    """Insere un rapport de fiabilisation horodate. Retourne son id."""
    return int(
        session.execute(
            text(
                "INSERT INTO rapport_fiabilisation "
                "(tenant_id, mission_id, statut, anomalies) "
                "VALUES (:t, :m, :s, CAST(:a AS jsonb)) RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "s": statut,
                "a": json.dumps(anomalies, ensure_ascii=False),
            },
        ).scalar_one()
    )


def compter_soldes(session: Session, mission_id: int) -> int:
    return int(
        session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mission_id},
        ).scalar_one()
    )


def lire_soldes_bruts(
    session: Session, mission_id: int
) -> list[tuple[str, Decimal, Decimal]]:
    rows = session.execute(
        text(
            "SELECT compte, debit, credit FROM solde_compte "
            "WHERE mission_id = :m ORDER BY compte"
        ),
        {"m": mission_id},
    ).all()
    return [(str(c), Decimal(d), Decimal(cr)) for c, d, cr in rows]


def lister_pieces(session: Session, mission_id: int) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT id, mission_id, type_piece, role, nom_fichier, "
            "chemin_stockage, taille_octets, content_type, cree_le "
            "FROM piece_mission WHERE mission_id = :m "
            "ORDER BY CASE role WHEN 'source_active' THEN 0 ELSE 1 END, cree_le"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def piece_par_id(session: Session, piece_id: int) -> dict | None:
    row = session.execute(
        text(
            "SELECT id, mission_id, type_piece, role, nom_fichier, "
            "chemin_stockage, taille_octets, content_type, cree_le "
            "FROM piece_mission WHERE id = :id"
        ),
        {"id": piece_id},
    ).mappings().first()
    return dict(row) if row else None


def source_active_existante(session: Session, mission_id: int) -> dict | None:
    row = session.execute(
        text(
            "SELECT id, type_piece, nom_fichier FROM piece_mission "
            "WHERE mission_id = :m AND role = 'source_active'"
        ),
        {"m": mission_id},
    ).mappings().first()
    return dict(row) if row else None


def degrad_sources_actives_en_annexes(session: Session, mission_id: int) -> int:
    """Passe toute source_active en annexe (avant désignation d'une nouvelle)."""
    res = session.execute(
        text(
            "UPDATE piece_mission SET role = 'annexe' "
            "WHERE mission_id = :m AND role = 'source_active'"
        ),
        {"m": mission_id},
    )
    return int(res.rowcount or 0)


def inserer_piece(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    type_piece: str,
    role: str,
    nom_fichier: str,
    chemin_stockage: str,
    taille_octets: int | None,
    content_type: str | None,
) -> dict:
    row = session.execute(
        text(
            "INSERT INTO piece_mission "
            "(tenant_id, mission_id, type_piece, role, nom_fichier, "
            "chemin_stockage, taille_octets, content_type) "
            "VALUES (:t, :m, :tp, :r, :n, :c, :z, :ct) "
            "RETURNING id, mission_id, type_piece, role, nom_fichier, "
            "chemin_stockage, taille_octets, content_type, cree_le"
        ),
        {
            "t": tenant_id,
            "m": mission_id,
            "tp": type_piece,
            "r": role,
            "n": nom_fichier,
            "c": chemin_stockage,
            "z": taille_octets,
            "ct": content_type,
        },
    ).mappings().one()
    return dict(row)


def supprimer_piece(session: Session, piece_id: int) -> dict | None:
    row = session.execute(
        text(
            "DELETE FROM piece_mission WHERE id = :id "
            "RETURNING id, mission_id, type_piece, role, nom_fichier, chemin_stockage"
        ),
        {"id": piece_id},
    ).mappings().first()
    return dict(row) if row else None
