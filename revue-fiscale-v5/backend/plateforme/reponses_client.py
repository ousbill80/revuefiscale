"""Saisie des réponses client à la demande de renseignements.

POURQUOI : quand le client répond à la circularisation, le cabinet doit
TRACER la réponse (contenu, pièces reçues, qui l'a saisie, quand) AVANT
de relancer une exécution du moteur. Sans cette trace, marquer un item
« recu » dans le suivi ne dit rien de CE QUI a été reçu, et rien ne relie
la réponse aux conclusions ``non_verifiable`` de la dernière exécution.

Ce module (déterministe, aucun appel LLM) :

- enregistre/écrase la réponse d'un item (UPSERT — une réponse par item
  et par mission), en validant que l'item appartient bien à la liste
  courante du suivi (:func:`suivi_renseignements.lister_items`) ;
- marque automatiquement l'item de suivi « recu » (réutilise
  :func:`suivi_renseignements.maj_item`) — une réponse saisie EST une
  réponse reçue ;
- restitue les réponses avec, pour les items ``piece:{regle_id}``, le
  statut actuel de la règle dans la dernière exécution
  (``statut_derniere_execution``) : l'auditeur voit d'un coup d'œil si la
  réponse reçue a déjà été prise en compte (statut devenu ``conforme``…)
  ou si la règle reste ``non_verifiable`` en attente de relance.

Aucun taux ni seuil fiscal ici — pur workflow cabinet, RLS stricte.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.suivi_renseignements import (
    ErreurSuiviIntrouvable,
    lister_items,
    maj_item,
)

PREFIXE_PIECE = "piece:"


class ErreurReponseClient(Exception):
    """Echec de saisie d'une réponse client (item invalide…) — 422."""


class ErreurReponseIntrouvable(ErreurReponseClient):
    """Mission hors périmètre du tenant — 404 côté route."""


def _regle_id_depuis_cle(cle_item: str) -> str | None:
    """« piece:OBL-36-ETII » → « OBL-36-ETII » ; None si item analytique."""
    if not cle_item.startswith(PREFIXE_PIECE):
        return None
    return cle_item[len(PREFIXE_PIECE):] or None


def enregistrer_reponse(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_item: str,
    contenu: str,
    pieces_recues: str | None,
    saisie_par: str,
) -> dict[str, Any]:
    """UPSERT de la réponse client d'un item + item de suivi passé « recu ».

    La mission doit exister sous RLS (sinon
    :class:`ErreurReponseIntrouvable` → 404) et ``cle_item`` appartenir à
    la liste courante des items du suivi (sinon
    :class:`ErreurReponseClient` → 422 : on ne trace pas une réponse à
    une question jamais posée). Retourne la réponse enregistrée.
    """
    cle_item = str(cle_item or "").strip()
    contenu = str(contenu or "").strip()
    if not contenu:
        raise ErreurReponseClient("contenu de réponse vide")

    try:
        items = lister_items(session, tenant_id, mission_id)
    except ErreurSuiviIntrouvable as e:
        raise ErreurReponseIntrouvable(str(e)) from e
    if cle_item not in {i["cle_item"] for i in items}:
        raise ErreurReponseClient(
            f"item « {cle_item} » inconnu pour la mission {mission_id}"
        )

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "INSERT INTO reponse_client "
                "(tenant_id, mission_id, cle_item, contenu, pieces_recues, "
                "saisie_par) "
                "VALUES (:t, :m, :c, :ct, :p, :s) "
                "ON CONFLICT (tenant_id, mission_id, cle_item) DO UPDATE SET "
                "contenu = EXCLUDED.contenu, "
                "pieces_recues = EXCLUDED.pieces_recues, "
                "saisie_par = EXCLUDED.saisie_par, "
                "saisie_le = now() "
                "RETURNING cle_item, contenu, pieces_recues, saisie_par, "
                "saisie_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_item,
                "ct": contenu,
                "p": (str(pieces_recues or "").strip() or None),
                "s": str(saisie_par or "").strip(),
            },
        ).mappings().one()

    # Une réponse saisie EST une réponse reçue : le suivi bascule « recu »
    # (même UPSERT que le PATCH manuel — la note existante est remplacée
    # volontairement par rien pour ne pas dupliquer le contenu tracé ici).
    maj_item(session, tenant_id, mission_id, cle_item, statut="recu")

    return {
        "cle_item": str(row["cle_item"]),
        "contenu": str(row["contenu"]),
        "pieces_recues": row["pieces_recues"],
        "saisie_par": str(row["saisie_par"]),
        "saisie_le": row["saisie_le"].isoformat(),
    }


def _statuts_derniere_execution(
    session: Session, mission_id: int
) -> dict[str, str]:
    """{regle_id: statut} des conclusions de la DERNIÈRE exécution.

    Contexte tenant déjà posé par l'appelant. Mêmes tables que
    ``demande_renseignements`` (execution la plus récente puis conclusion
    JOIN regle_version). Vide si la mission n'a jamais été exécutée.
    """
    exec_id = session.execute(
        text(
            "SELECT id FROM execution WHERE mission_id = :m "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()
    if exec_id is None:
        return {}
    rows = session.execute(
        text(
            "SELECT rv.regle_id, c.statut FROM conclusion c "
            "JOIN regle_version rv ON rv.id = c.regle_version_id "
            "WHERE c.execution_id = :e"
        ),
        {"e": int(exec_id)},
    ).mappings().all()
    return {str(r["regle_id"]): str(r["statut"]) for r in rows}


def lister_reponses(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    """Réponses client de la mission triées par ``cle_item``.

    Chaque réponse porte ``regle_id`` (déduit de ``piece:{regle_id}``,
    None pour les items analytiques) et ``statut_derniere_execution`` :
    statut actuel de la règle dans la dernière exécution si retrouvable
    (nullable) — c'est LE signal « réponse reçue mais règle toujours
    non vérifiable → relancer une exécution ». 404 si mission hors tenant.
    """
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurReponseIntrouvable(
                f"mission {mission_id} introuvable"
            )
        rows = session.execute(
            text(
                "SELECT cle_item, contenu, pieces_recues, saisie_par, "
                "saisie_le FROM reponse_client "
                "WHERE mission_id = :m ORDER BY cle_item"
            ),
            {"m": mission_id},
        ).mappings().all()
        statuts = _statuts_derniere_execution(session, mission_id)

    reponses: list[dict[str, Any]] = []
    for r in rows:
        cle = str(r["cle_item"])
        regle_id = _regle_id_depuis_cle(cle)
        reponses.append(
            {
                "cle_item": cle,
                "contenu": str(r["contenu"]),
                "pieces_recues": r["pieces_recues"],
                "saisie_par": str(r["saisie_par"]),
                "saisie_le": r["saisie_le"].isoformat(),
                "regle_id": regle_id,
                "statut_derniere_execution": (
                    statuts.get(regle_id) if regle_id else None
                ),
            }
        )
    return reponses
