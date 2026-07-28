"""Reconduction d'une mission sur l'exercice suivant (N+1).

POURQUOI : la revue fiscale d'un client est un cycle annuel — une fois
la mission de l'exercice N clôturée, le cabinet reconduit le dossier sur
N+1 : même contribuable, profil repris (régime, forme juridique…),
honoraires et taux horaire repris À TITRE INDICATIF (modifiables
ensuite). La continuité du dossier est déjà assurée par ailleurs
(risques reportés par ``origine_mission_id``, comparaison N/N-1,
mémoire client) ; ce module ne crée QUE la nouvelle mission.

DOCTRINE : déterministe, l'humain décide — la reconduction n'a lieu que
sur clic explicite du fiscaliste ; aucune reconduction automatique,
aucun LLM. Fonctions pures testables sans base + une fonction RLS via
``contexte_tenant``. Règles : mission source au statut « cloturee »
UNIQUEMENT ; aucune mission (quel que soit son statut) déjà existante
pour ce contribuable sur l'exercice N+1.
"""
from __future__ import annotations

import json
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.missions import STATUT_CLOTUREE

# Clés du profil mission reprises telles quelles (backend/profil/service.py).
CLES_PROFIL_REPRISES: Final[tuple[str, ...]] = (
    "regime",
    "forme_juridique",
    "secteur",
    "type_entite",
    "cross_border",
    "etiquette_profil",
)

# Note consultative — TOUJOURS présente dans la réponse : les paramètres
# financiers repris ne préjugent pas des honoraires du nouvel exercice.
NOTE_RECONDUCTION: Final = (
    "honoraires repris à titre indicatif — à revoir avec le client"
)


class ErreurReconduction(Exception):
    """Échec de reconduction — 400 côté route par défaut."""


class ErreurReconductionIntrouvable(ErreurReconduction):
    """Mission source hors périmètre du tenant — 404 côté route."""


class ErreurReconductionConflit(ErreurReconduction):
    """Statut non clôturé ou mission N+1 déjà existante — 409 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def construire_profil_reconduction(
    profil_source: dict[str, Any] | None,
) -> dict[str, Any]:
    """PUR — profil de la nouvelle mission depuis celui de la source.

    Copie les clés connues du profil réel (:data:`CLES_PROFIL_REPRISES`)
    en ignorant les clés inconnues et les valeurs vides. Le régime et la
    forme juridique sont requis : sans eux la mission N+1 ne pourrait
    pas être créée (``valider_profil``).
    """
    if not isinstance(profil_source, dict):
        raise ErreurReconduction(
            "profil de la mission source illisible — reconduction impossible"
        )
    profil: dict[str, Any] = {}
    for cle in CLES_PROFIL_REPRISES:
        valeur = profil_source.get(cle)
        if valeur not in (None, ""):
            profil[cle] = valeur
    manquants = [
        c for c in ("regime", "forme_juridique") if c not in profil
    ]
    if manquants:
        raise ErreurReconduction(
            "profil de la mission source incomplet "
            f"(clés manquantes : {', '.join(manquants)}) — "
            "reconduction impossible"
        )
    return profil


def valider_reconduction(
    *,
    statut_source: str,
    exercice_source: int,
    mission_existante_id: int | None = None,
    denomination: str = "",
) -> int:
    """PUR — valide la reconduction et retourne l'exercice cible (N+1).

    - Source non clôturée → :class:`ErreurReconductionConflit` (la
      reconduction n'a de sens qu'une fois l'exercice N achevé et le
      dossier clôturé) ;
    - Mission déjà existante pour ce contribuable sur N+1 (quel que soit
      son statut) → :class:`ErreurReconductionConflit`, message explicite
      avec l'identifiant existant.
    """
    statut = str(statut_source or "").strip().lower()
    exercice_cible = int(exercice_source) + 1
    if statut != STATUT_CLOTUREE:
        raise ErreurReconductionConflit(
            f"Reconduction refusée : la mission source est au statut "
            f"« {statut or 'inconnu'} » — seule une mission clôturée "
            "peut être reconduite sur l'exercice suivant."
        )
    if mission_existante_id is not None:
        qui = f" pour « {denomination} »" if denomination else ""
        raise ErreurReconductionConflit(
            f"Reconduction refusée : une mission existe déjà{qui} sur "
            f"l'exercice {exercice_cible} (mission "
            f"#{int(mission_existante_id)}). Ouvrez-la depuis l'onglet "
            "Missions."
        )
    return exercice_cible


# ── Écriture (RLS) — sur clic explicite du fiscaliste ────────────────


def reconduire_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    acteur: str,
) -> dict[str, Any]:
    """Reconduit la mission clôturée ``mission_id`` sur l'exercice N+1.

    Vérifie sous RLS : mission hors tenant →
    :class:`ErreurReconductionIntrouvable` (404) ; source non clôturée
    ou mission N+1 déjà existante → :class:`ErreurReconductionConflit`
    (409). Crée la nouvelle mission via ``creer_mission`` (même
    contribuable, exercice N+1, profil repris, type d'engagement
    conservé), puis reprend honoraires et taux horaire de la source
    s'ils sont renseignés (indicatif — modifiables ensuite). Journalise
    ``reconduction_mission`` sur la mission SOURCE et
    ``creation_mission`` sur la NOUVELLE (``creer_mission`` ne
    journalise pas lui-même — c'est la responsabilité de l'appelant,
    comme pour la route de création).
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        source = session.execute(
            text(
                "SELECT m.id, m.statut, m.contribuable_id, m.exercice, "
                "m.profil, m.type_engagement, m.honoraires, m.taux_horaire, "
                "c.denomination "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if source is None:
            raise ErreurReconductionIntrouvable(
                f"mission {mission_id} introuvable"
            )

        exercice_source = int(source["exercice"])
        existante = session.execute(
            text(
                "SELECT id FROM mission "
                "WHERE contribuable_id = :c AND exercice = :e "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"c": source["contribuable_id"], "e": exercice_source + 1},
        ).scalar_one_or_none()

    exercice_cible = valider_reconduction(
        statut_source=str(source["statut"] or ""),
        exercice_source=exercice_source,
        mission_existante_id=(
            int(existante) if existante is not None else None
        ),
        denomination=str(source["denomination"] or ""),
    )

    profil_source = source["profil"]
    if isinstance(profil_source, str):
        try:
            profil_source = json.loads(profil_source)
        except json.JSONDecodeError:
            profil_source = None
    profil = construire_profil_reconduction(profil_source)

    nouvelle_mission_id = creer_mission(
        session,
        tenant_id,
        contribuable_id=int(source["contribuable_id"]),
        exercice=exercice_cible,
        profil=profil,
        type_engagement=str(source["type_engagement"] or "autre"),
    )

    # Reprise indicative des paramètres financiers de la source.
    if source["honoraires"] is not None or source["taux_horaire"] is not None:
        with contexte_tenant(session, tenant_id):
            session.execute(
                text(
                    "UPDATE mission SET honoraires = :h, taux_horaire = :t "
                    "WHERE id = :m"
                ),
                {
                    "h": source["honoraires"],
                    "t": source["taux_horaire"],
                    "m": nouvelle_mission_id,
                },
            )

    with contexte_tenant(session, tenant_id):
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=nouvelle_mission_id,
            acteur=acteur,
            action="creation_mission",
            charge_utile={
                "exercice": exercice_cible,
                "contribuable_id": int(source["contribuable_id"]),
                "origine": "reconduction",
                "mission_source_id": mission_id,
            },
        )
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action="reconduction_mission",
            charge_utile={
                "nouvelle_mission_id": nouvelle_mission_id,
                "exercice": exercice_cible,
            },
        )

    return {
        "mission_id": mission_id,
        "nouvelle_mission_id": nouvelle_mission_id,
        "exercice": exercice_cible,
        "note": NOTE_RECONDUCTION,
    }
