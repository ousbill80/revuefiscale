"""Orchestration d une execution de mission."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.moteur.calcul import (
    ConclusionCalculee,
    calculer_regle,
    statut_brouillon_conclusion,
)
from backend.moteur.journal import append_journal
from backend.moteur.selection import selectionner_regles
from backend.plateforme.contexte import contexte_tenant
from backend.referentiel.depot import lire_regles_version
from backend.referentiel.expressions import Contexte
from backend.socle.agregats import (
    calculer_agregats,
    comptes_par_agregat,
    solde_naturel,
)


class ErreurMoteur(Exception):
    """Echec d execution du moteur."""


def _charger_soldes(
    session: Session, mission_id: int
) -> tuple[dict[str, Decimal], dict[str, dict[str, Any]]]:
    """Retourne (soldes naturels, infos comptes) depuis solde_compte.

    ``infos`` porte libelle / debit / credit par compte — sert uniquement a la
    piste d audit des conclusions (comptes a l origine), jamais au calcul.
    """
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).mappings().all()
    if not rows:
        raise ErreurMoteur(f"aucun solde pour la mission {mission_id}")
    soldes: dict[str, Decimal] = {}
    infos: dict[str, dict[str, Any]] = {}
    for r in rows:
        compte = str(r["compte"])
        debit = Decimal(r["debit"])
        credit = Decimal(r["credit"])
        soldes[compte] = solde_naturel(compte, debit, credit)
        infos[compte] = {
            "libelle": r["libelle"],
            "debit": debit,
            "credit": credit,
        }
    return soldes, infos


def comptes_source_conclusion(
    comptes_utilises: tuple[str, ...] | list[str],
    soldes: dict[str, Decimal],
    infos: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Piste d audit sérialisable : {compte, libelle, solde, sens} par compte.

    - ``solde`` : solde naturel (chaîne, déterministe) du compte.
    - ``sens`` : sens comptable brut du solde (debiteur / crediteur / nul),
      dérivé de debit - credit — jamais un jugement fiscal.
    """
    out: list[dict[str, Any]] = []
    for compte in sorted({str(c) for c in comptes_utilises}):
        if compte not in soldes:
            continue
        info = infos.get(compte, {})
        debit = Decimal(str(info.get("debit", 0)))
        credit = Decimal(str(info.get("credit", 0)))
        brut = debit - credit
        if brut > 0:
            sens = "debiteur"
        elif brut < 0:
            sens = "crediteur"
        else:
            sens = "nul"
        out.append(
            {
                "compte": compte,
                "libelle": info.get("libelle"),
                "solde": str(soldes[compte]),
                "sens": sens,
            }
        )
    return out


def executer_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    acteur: str,
    reponses: dict[str, Any] | None = None,
) -> list[ConclusionCalculee]:
    """Execute le moteur sur la version epinglee de la mission.

    Charge soldes → agregats → selection → calcul → execution + conclusions +
    matérialisation déterministe des tâches (plan dérivé, hors LLM).
    """
    reponses = reponses or {}

    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, version_referentiel_id, profil, statut, "
                "perimetre_impots, seuil_signification, exercice "
                "FROM mission WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurMoteur(f"mission {mission_id} introuvable")
        version_id = mission["version_referentiel_id"]
        if version_id is None:
            raise ErreurMoteur(
                f"mission {mission_id} sans version_referentiel_id (epinglage manquant)"
            )

        from backend.plateforme.missions import (
            ErreurMission,
            marquer_en_cours_si_cadrage,
            normaliser_perimetre_lu,
        )
        from backend.plateforme.objectifs_fiscaux import assurer_objectif_pour_impot
        from backend.plateforme.taches import (
            projeter_blocages_effets_croises,
            upsert_tache,
        )

        try:
            statut_auto = marquer_en_cours_si_cadrage(session, mission_id)
        except ErreurMission as e:
            raise ErreurMoteur(str(e)) from e

        if statut_auto.get("change"):
            append_journal(
                session,
                tenant_id=tenant_id,
                mission_id=mission_id,
                acteur=acteur,
                action="changement_statut",
                charge_utile={
                    "statut_precedent": "cadrage",
                    "statut": "en_cours",
                    "declencheur": "execution_moteur",
                },
            )

        soldes, infos_comptes = _charger_soldes(session, mission_id)
        agregats = calculer_agregats(soldes)
        ctx = Contexte(
            soldes=soldes,
            agregats=agregats,
            reponses=reponses,
            comptes_par_agregat=comptes_par_agregat(soldes),
        )

        profil_brut = mission["profil"]
        profil: dict[str, object] | None = None
        if isinstance(profil_brut, dict):
            profil = dict(profil_brut)
        elif isinstance(profil_brut, str):
            try:
                parsed = json.loads(profil_brut)
                if isinstance(parsed, dict):
                    profil = parsed
            except json.JSONDecodeError:
                profil = None

        perimetre = normaliser_perimetre_lu(mission.get("perimetre_impots"))
        seuil_brut = mission.get("seuil_signification")
        seuil: Decimal | None = (
            Decimal(str(seuil_brut)) if seuil_brut is not None else None
        )
        exercice = int(mission["exercice"]) if mission.get("exercice") is not None else 0

        regles = lire_regles_version(session, int(version_id))
        candidates = selectionner_regles(
            regles, soldes, profil=profil, perimetre_impots=perimetre
        )

        conclusions: list[ConclusionCalculee] = []
        for regle in candidates:
            conclusions.append(calculer_regle(regle, ctx))

        exec_id = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, :a) RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id, "a": acteur},
        ).scalar_one()

        nb_inserees = 0
        nb_taches = 0
        for regle, c in zip(candidates, conclusions, strict=True):
            objectif_id = assurer_objectif_pour_impot(
                session,
                tenant_id,
                mission_id,
                regle.impot,
                exercice,
                dans_perimetre=True,
            )
            piece_attendue = None
            statut = statut_brouillon_conclusion(c, seuil)
            if statut is None:
                upsert_tache(
                    session,
                    tenant_id,
                    objectif_id,
                    c.regle_version_id,
                    statut="a_faire",
                )
                nb_taches += 1
                continue

            if statut == "non_verifiable":
                piece_attendue = "Pièce ou réponse manquante pour conclure"

            cid = session.execute(
                text(
                    "INSERT INTO conclusion "
                    "(tenant_id, execution_id, regle_version_id, montant, sens, "
                    "niveau_risque, reponses, commentaire, statut, comptes_source) "
                    "VALUES (:t, :e, :rv, :mt, :sens, :nr, CAST(:rep AS jsonb), "
                    ":com, :st, CAST(:cs AS jsonb)) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "e": exec_id,
                    "rv": c.regle_version_id,
                    "mt": c.montant,
                    "sens": c.sens,
                    "nr": c.niveau_risque,
                    "rep": json.dumps(reponses, ensure_ascii=False, default=str),
                    "com": c.detail,
                    "st": statut,
                    "cs": json.dumps(
                        comptes_source_conclusion(
                            c.comptes_utilises, soldes, infos_comptes
                        ),
                        ensure_ascii=False,
                    ),
                },
            ).scalar_one()
            upsert_tache(
                session,
                tenant_id,
                objectif_id,
                c.regle_version_id,
                statut=statut,
                conclusion_id=int(cid),
                piece_attendue=piece_attendue,
            )
            nb_inserees += 1
            nb_taches += 1

        nb_bloquees = projeter_blocages_effets_croises(
            session, tenant_id, mission_id
        )

        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action="execution_moteur",
            charge_utile={
                "execution_id": int(exec_id),
                "version_referentiel_id": int(version_id),
                "nb_conclusions": nb_inserees,
                "nb_taches": nb_taches,
                "nb_taches_bloquees": nb_bloquees,
                "perimetre_impots": perimetre,
                "revue_partielle": perimetre is not None,
                "seuil_signification": str(seuil) if seuil is not None else None,
            },
        )
        session.flush()

    return conclusions
