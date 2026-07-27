"""Contrôle qualité de pré-clôture de mission — déterministe, consultatif.

Avant de clôturer une mission, l'associé passe une revue qualité (esprit
NEP / ISQM) : points instruits, risques traités ou acceptés, livrables
produits. Ce module évalue une liste de points figée — aucun LLM, aucune
écriture, lecture seule sous RLS via ``contexte_tenant``. Le résultat est
consultatif : il ne bloque jamais la clôture, l'humain décide.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# Statuts de risque considérés comme non traités (ni résolu, ni accepté,
# ni prescrit) — mêmes valeurs que STATUTS_NON_CLOS de risques.py.
_STATUTS_RISQUE_OUVERTS: Final[tuple[str, ...]] = ("ouvert", "en_traitement")
# Statuts de tâche « en cours de traitement » (workflow non terminé).
_STATUTS_TACHE_EN_COURS: Final[tuple[str, ...]] = (
    "a_faire",
    "en_cours",
    "bloquee",
)

STATUT_OK: Final[str] = "ok"
STATUT_ATTENTION: Final[str] = "attention"
STATUT_BLOQUANT: Final[str] = "bloquant"


class ErreurControleCloture(Exception):
    """Échec du contrôle de pré-clôture (mission introuvable…)."""


def _point(
    code: str, libelle: str, statut: str, detail: str
) -> dict[str, str]:
    return {
        "code": code,
        "libelle": libelle,
        "statut": statut,
        "detail": detail,
    }


def _pluriel(n: int, mot: str) -> str:
    return f"{n} {mot}{'s' if n > 1 else ''}"


def _derniere_execution_id(session: Session, mission_id: int) -> int | None:
    return session.execute(
        text(
            "SELECT id FROM execution WHERE mission_id = :m "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()


def _point_conclusions_instruites(
    session: Session, mission_id: int, exec_id: int | None
) -> dict[str, str]:
    """Anomalies sans suite (risque ou décision « 4 yeux ») + suivi ouvert."""
    libelle = "Conclusions instruites"
    if exec_id is None:
        return _point(
            "conclusions_instruites",
            libelle,
            STATUT_ATTENTION,
            "Aucune exécution : les conclusions n'ont pas été produites.",
        )
    # Anomalie « sans suite » : ni risque issu de la conclusion, ni
    # décision humaine (validation 4 yeux) sur la conclusion.
    anomalies_sans_suite = int(
        session.execute(
            text(
                "SELECT count(*) FROM conclusion c "
                "WHERE c.execution_id = :e AND c.statut = 'anomalie' "
                "AND c.valide_par IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM risque r "
                "  WHERE r.origine_conclusion_id = c.id)"
            ),
            {"e": exec_id},
        ).scalar_one()
    )
    # Suivi de traitement : tâches encore à faire / en cours / bloquées.
    taches_en_cours = int(
        session.execute(
            text(
                "SELECT count(*) FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "WHERE o.mission_id = :m AND t.statut = ANY(:st)"
            ),
            {"m": mission_id, "st": list(_STATUTS_TACHE_EN_COURS)},
        ).scalar_one()
    )
    morceaux: list[str] = []
    if anomalies_sans_suite:
        morceaux.append(
            _pluriel(anomalies_sans_suite, "conclusion")
            + " en anomalie sans risque créé ni validation"
        )
    if taches_en_cours:
        morceaux.append(
            _pluriel(taches_en_cours, "point")
            + " de contrôle encore à faire ou en cours"
        )
    if morceaux:
        return _point(
            "conclusions_instruites",
            libelle,
            STATUT_ATTENTION,
            " ; ".join(morceaux) + ".",
        )
    return _point(
        "conclusions_instruites",
        libelle,
        STATUT_OK,
        "Toutes les anomalies sont suivies (risque ou décision) et le "
        "plan de contrôle est soldé.",
    )


def _point_risques_traites(
    session: Session, contribuable_id: int
) -> dict[str, str]:
    """Risques ouverts (ni résolu ni accepté) — bloquant si montant > 0."""
    libelle = "Risques traités ou acceptés"
    rows = session.execute(
        text(
            "SELECT count(*) AS nb, "
            "COALESCE(SUM(COALESCE(montant_estime, 0) "
            "  + COALESCE(penalites_estimees, 0)), 0) AS exposition, "
            "count(*) FILTER (WHERE COALESCE(montant_estime, 0) > 0) "
            "  AS nb_chiffres "
            "FROM risque WHERE contribuable_id = :c "
            "AND statut = ANY(:ouverts)"
        ),
        {"c": contribuable_id, "ouverts": list(_STATUTS_RISQUE_OUVERTS)},
    ).mappings().one()
    nb = int(rows["nb"])
    if nb == 0:
        return _point(
            "risques_traites",
            libelle,
            STATUT_OK,
            "Aucun risque ouvert : tous résolus, acceptés ou prescrits.",
        )
    exposition = Decimal(str(rows["exposition"]))
    nb_chiffres = int(rows["nb_chiffres"])
    s = "s" if nb > 1 else ""
    detail = f"{nb} risque{s} ouvert{s} (ni résolu{s} ni accepté{s})"
    if nb_chiffres > 0:
        return _point(
            "risques_traites",
            libelle,
            STATUT_BLOQUANT,
            detail
            + f", exposition estimée {exposition} FCFA — à résoudre ou "
            "accepter avant clôture.",
        )
    return _point(
        "risques_traites",
        libelle,
        STATUT_ATTENTION,
        detail + ", sans montant estimé — à statuer avant clôture.",
    )


def _point_note_synthese(
    session: Session, mission_id: int
) -> dict[str, str]:
    libelle = "Note de synthèse produite"
    nb = int(
        session.execute(
            text(
                "SELECT count(*) FROM note_synthese_mission "
                "WHERE mission_id = :m AND statut = 'disponible'"
            ),
            {"m": mission_id},
        ).scalar_one()
    )
    if nb > 0:
        return _point(
            "note_synthese_presente",
            libelle,
            STATUT_OK,
            f"{_pluriel(nb, 'version')} de note de synthèse disponible"
            f"{'s' if nb > 1 else ''}.",
        )
    return _point(
        "note_synthese_presente",
        libelle,
        STATUT_ATTENTION,
        "Aucune note de synthèse disponible — générez-la pour l'associé "
        "signataire.",
    )


def _point_reponses_client(
    session: Session, exec_id: int | None
) -> dict[str, str]:
    libelle = "Réponses client obtenues"
    nb = 0
    if exec_id is not None:
        nb = int(
            session.execute(
                text(
                    "SELECT count(*) FROM conclusion "
                    "WHERE execution_id = :e AND statut = 'non_verifiable'"
                ),
                {"e": exec_id},
            ).scalar_one()
        )
    if nb == 0:
        return _point(
            "reponses_client",
            libelle,
            STATUT_OK,
            "Aucune conclusion non vérifiable en attente de réponse client.",
        )
    return _point(
        "reponses_client",
        libelle,
        STATUT_ATTENTION,
        f"{_pluriel(nb, 'conclusion')} non vérifiable"
        f"{'s' if nb > 1 else ''} — utilisez la demande de renseignements "
        "pour obtenir les pièces du client.",
    )


def _point_pieces_justificatives(
    session: Session, contribuable_id: int
) -> dict[str, str]:
    """Risques résolus sans preuve de résolution déposée → attention."""
    libelle = "Preuves de résolution présentes"
    table = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'preuve_resolution_risque'"
        )
    ).scalar_one()
    if int(table) == 0:
        return _point(
            "pieces_justificatives",
            libelle,
            STATUT_OK,
            "Registre des preuves de résolution non disponible — contrôle "
            "sans objet.",
        )
    sans_preuve = int(
        session.execute(
            text(
                "SELECT count(*) FROM risque r "
                "WHERE r.contribuable_id = :c AND r.statut = 'resolu' "
                "AND NOT EXISTS (SELECT 1 FROM preuve_resolution_risque p "
                "  WHERE p.risque_id = r.id)"
            ),
            {"c": contribuable_id},
        ).scalar_one()
    )
    if sans_preuve == 0:
        return _point(
            "pieces_justificatives",
            libelle,
            STATUT_OK,
            "Chaque risque résolu dispose d'un justificatif déposé.",
        )
    s = "s" if sans_preuve > 1 else ""
    return _point(
        "pieces_justificatives",
        libelle,
        STATUT_ATTENTION,
        f"{sans_preuve} risque{s} résolu{s} sans preuve de résolution "
        "déposée au registre.",
    )


def _point_visas_supervision(
    session: Session, mission_id: int
) -> dict[str, str]:
    """Visas de supervision de la phase restitution — consultatif.

    OK si les trois rangs (préparateur, réviseur, associé) ont visé la
    phase restitution ; attention sinon, en listant les rôles manquants.
    Jamais bloquant : la supervision reste un jugement humain.
    """
    from backend.plateforme.visas_mission import ORDRE_ROLES

    libelle = "Visas de supervision"
    presents = {
        str(r)
        for r in session.execute(
            text(
                "SELECT role FROM visa_mission "
                "WHERE mission_id = :m AND phase = 'restitution'"
            ),
            {"m": mission_id},
        ).scalars()
    }
    manquants = [r for r in ORDRE_ROLES if r not in presents]
    if not manquants:
        return _point(
            "visas_supervision",
            libelle,
            STATUT_OK,
            "Phase restitution visée aux trois rangs : préparateur, "
            "réviseur et associé.",
        )
    return _point(
        "visas_supervision",
        libelle,
        STATUT_ATTENTION,
        "Phase restitution incomplètement visée — rôle"
        f"{'s' if len(manquants) > 1 else ''} manquant"
        f"{'s' if len(manquants) > 1 else ''} : "
        + ", ".join(manquants)
        + ".",
    )


def _point_programme_travail(etat: dict[str, Any]) -> dict[str, str]:
    """Avancement du programme de travail — consultatif, jamais bloquant."""
    libelle = "Programme de travail exécuté"
    synthese = etat["synthese"]
    faites = int(synthese["faites"])
    total = int(synthese["total"])
    if total > 0 and faites == total:
        return _point(
            "programme_travail",
            libelle,
            STATUT_OK,
            f"Les {total} diligences du programme de travail sont faites "
            f"({synthese['avancement_pct']} %).",
        )
    restantes = [
        d["code"]
        for phase in etat["phases"]
        for d in phase["diligences"]
        if not d["fait"]
    ]
    apercu = ", ".join(restantes[:6]) + ("…" if len(restantes) > 6 else "")
    return _point(
        "programme_travail",
        libelle,
        STATUT_ATTENTION,
        f"{faites}/{total} diligences faites "
        f"({synthese['avancement_pct']} %) — restantes : {apercu}.",
    )


def evaluer_cloture(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Revue qualité de pré-clôture — déterministe, lecture seule.

    Retourne ``{points, synthese, cloture_recommandee}``. 404 côté API si
    la mission est hors tenant (``ErreurControleCloture`` « introuvable »).
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, contribuable_id, statut FROM mission "
                "WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurControleCloture(f"mission {mission_id} introuvable")
        contribuable_id = int(mission["contribuable_id"])
        exec_id = _derniere_execution_id(session, mission_id)

        points = [
            _point_conclusions_instruites(session, mission_id, exec_id),
            _point_risques_traites(session, contribuable_id),
            _point_note_synthese(session, mission_id),
            _point_reponses_client(session, exec_id),
            _point_pieces_justificatives(session, contribuable_id),
            _point_visas_supervision(session, mission_id),
        ]

    # etat_programme gère son propre contexte_tenant — appel hors du with.
    from backend.plateforme.programme_travail import etat_programme

    points.append(
        _point_programme_travail(
            etat_programme(session, tenant_id, mission_id)
        )
    )

    synthese = {
        STATUT_OK: sum(1 for p in points if p["statut"] == STATUT_OK),
        STATUT_ATTENTION: sum(
            1 for p in points if p["statut"] == STATUT_ATTENTION
        ),
        STATUT_BLOQUANT: sum(
            1 for p in points if p["statut"] == STATUT_BLOQUANT
        ),
    }
    return {
        "mission_id": int(mission["id"]),
        "statut_mission": str(mission["statut"]),
        "points": points,
        "synthese": synthese,
        "cloture_recommandee": synthese[STATUT_BLOQUANT] == 0,
    }
