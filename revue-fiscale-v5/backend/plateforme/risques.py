"""Registre des risques — appartient au contribuable (docs/25)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

STATUTS_RISQUE: Final[frozenset[str]] = frozenset(
    {"ouvert", "en_traitement", "resolu", "accepte", "prescrit"}
)
PROBABILITES: Final[frozenset[str]] = frozenset(
    {"probable", "possible", "faible"}
)
STATUTS_NON_CLOS: Final[frozenset[str]] = frozenset(
    {"ouvert", "en_traitement"}
)


class ErreurRisque(Exception):
    """Echec CRUD risque."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    montant = row.get("montant_estime")
    penalites = row.get("penalites_estimees")
    cree = row.get("cree_le")
    maj = row.get("maj_le")
    revue = row.get("derniere_revue")
    accepte_le = row.get("accepte_le")
    prescrit_le = row.get("prescrit_le")
    return {
        "id": int(row["id"]),
        "contribuable_id": int(row["contribuable_id"]),
        "origine_conclusion_id": (
            int(row["origine_conclusion_id"])
            if row.get("origine_conclusion_id") is not None
            else None
        ),
        "origine_mission_id": (
            int(row["origine_mission_id"])
            if row.get("origine_mission_id") is not None
            else None
        ),
        "origine_tache_id": (
            int(row["origine_tache_id"])
            if row.get("origine_tache_id") is not None
            else None
        ),
        "impot": str(row["impot"]).upper(),
        "reference_legale": row.get("reference_legale"),
        "libelle": str(row["libelle"]),
        "montant_estime": str(montant) if montant is not None else None,
        "penalites_estimees": str(penalites) if penalites is not None else None,
        "probabilite": str(row.get("probabilite") or "possible"),
        "statut": str(row.get("statut") or "ouvert"),
        "exercice_origine": int(row["exercice_origine"]),
        "derniere_revue": (
            revue.isoformat() if isinstance(revue, date) else revue
        ),
        "motif_acceptation": row.get("motif_acceptation"),
        "accepte_le": (
            accepte_le.isoformat()
            if hasattr(accepte_le, "isoformat")
            else accepte_le
        ),
        "accepte_par": row.get("accepte_par"),
        "prescrit_le": (
            prescrit_le.isoformat()
            if hasattr(prescrit_le, "isoformat")
            else prescrit_le
        ),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
        "maj_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
        "contribuable_denomination": row.get("contribuable_denomination"),
    }


_SELECT_RISQUE = (
    "SELECT r.id, r.contribuable_id, r.origine_conclusion_id, "
    "r.origine_mission_id, r.origine_tache_id, r.impot, r.reference_legale, "
    "r.libelle, r.montant_estime, r.penalites_estimees, r.probabilite, "
    "r.statut, r.exercice_origine, r.derniere_revue, r.motif_acceptation, "
    "r.accepte_le, r.accepte_par, r.prescrit_le, r.cree_le, r.maj_le, "
    "c.denomination AS contribuable_denomination "
    "FROM risque r "
    "JOIN contribuable c ON c.id = r.contribuable_id"
)


def _lire(session: Session, risque_id: int) -> dict[str, Any]:
    row = session.execute(
        text(_SELECT_RISQUE + " WHERE r.id = :id"),
        {"id": risque_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurRisque(f"risque {risque_id} introuvable")
    return _serialiser(dict(row))


def lister_risques(
    session: Session,
    tenant_id: int,
    *,
    contribuable_id: int | None = None,
    statut: str | None = None,
    impot: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    sql = _SELECT_RISQUE + " WHERE 1=1"
    if contribuable_id is not None:
        sql += " AND r.contribuable_id = :cid"
        params["cid"] = contribuable_id
    if statut is not None:
        st = statut.strip().lower()
        if st not in STATUTS_RISQUE:
            raise ErreurRisque(
                f"statut invalide {statut!r} — attendu : "
                + ", ".join(sorted(STATUTS_RISQUE))
            )
        sql += " AND r.statut = :st"
        params["st"] = st
    if impot is not None:
        sql += " AND r.impot = :imp"
        params["imp"] = str(impot).strip().upper()
    sql += " ORDER BY r.exercice_origine DESC, r.impot ASC, r.id DESC"

    with contexte_tenant(session, tenant_id):
        rows = session.execute(text(sql), params).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def lire_risque(
    session: Session, tenant_id: int, risque_id: int
) -> dict[str, Any]:
    with contexte_tenant(session, tenant_id):
        return _lire(session, risque_id)


def creer_risque(
    session: Session,
    tenant_id: int,
    *,
    contribuable_id: int,
    impot: str,
    libelle: str,
    exercice_origine: int,
    probabilite: str = "possible",
    reference_legale: str | None = None,
    montant_estime: Decimal | None = None,
    penalites_estimees: Decimal | None = None,
    origine_conclusion_id: int | None = None,
    origine_mission_id: int | None = None,
    origine_tache_id: int | None = None,
    statut: str = "ouvert",
) -> dict[str, Any]:
    lib = (libelle or "").strip()
    if not lib:
        raise ErreurRisque("libelle obligatoire")
    code = str(impot or "").strip().upper()
    if not code:
        raise ErreurRisque("impot obligatoire")
    prob = (probabilite or "possible").strip().lower()
    if prob not in PROBABILITES:
        raise ErreurRisque(
            f"probabilite invalide {probabilite!r} — attendu : "
            + ", ".join(sorted(PROBABILITES))
        )
    st = (statut or "ouvert").strip().lower()
    if st not in STATUTS_RISQUE:
        raise ErreurRisque(f"statut invalide {statut!r}")

    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text("SELECT id FROM contribuable WHERE id = :c"),
            {"c": contribuable_id},
        ).scalar_one_or_none()
        if contrib is None:
            raise ErreurRisque(f"contribuable {contribuable_id} introuvable")

        if origine_conclusion_id is not None:
            existe = session.execute(
                text(
                    "SELECT id FROM risque "
                    "WHERE origine_conclusion_id = :c LIMIT 1"
                ),
                {"c": origine_conclusion_id},
            ).scalar_one_or_none()
            if existe is not None:
                return _lire(session, int(existe))

        rid = session.execute(
            text(
                "INSERT INTO risque "
                "(tenant_id, contribuable_id, origine_conclusion_id, "
                "origine_mission_id, origine_tache_id, impot, reference_legale, "
                "libelle, montant_estime, penalites_estimees, probabilite, "
                "statut, exercice_origine) "
                "VALUES (:t, :c, :oc, :om, :ot, :imp, :ref, :lib, :mt, :pen, "
                ":prob, :st, :ex) RETURNING id"
            ),
            {
                "t": tenant_id,
                "c": contribuable_id,
                "oc": origine_conclusion_id,
                "om": origine_mission_id,
                "ot": origine_tache_id,
                "imp": code,
                "ref": (reference_legale or "").strip() or None,
                "lib": lib,
                "mt": montant_estime,
                "pen": penalites_estimees,
                "prob": prob,
                "st": st,
                "ex": int(exercice_origine),
            },
        ).scalar_one()
        session.flush()
        resultat = _lire(session, int(rid))

    from backend.plateforme.memoire_client import alimenter_memoire

    exposition = (
        f"exposition estimée {montant_estime:,.0f} FCFA".replace(",", " ")
        if montant_estime is not None
        else "exposition non chiffrée"
    )
    alimenter_memoire(
        session,
        tenant_id,
        contribuable_id,
        type_entree="alerte",
        contenu=(
            f"Risque créé : {lib} — exercice {int(exercice_origine)} — "
            f"{exposition}."
        ),
        source_type="risque",
        source_ref=f"risque:{resultat['id']}",
    )
    return resultat


def patcher_risque(
    session: Session,
    tenant_id: int,
    risque_id: int,
    *,
    acteur: str,
    statut: object | None = ...,
    probabilite: object | None = ...,
    motif_acceptation: object | None = ...,
    montant_estime: object | None = ...,
    penalites_estimees: object | None = ...,
    derniere_revue: object | None = ...,
    libelle: object | None = ...,
    avec_preuve: bool = False,
) -> dict[str, Any]:
    champs = {
        "statut": statut is not ...,
        "probabilite": probabilite is not ...,
        "motif_acceptation": motif_acceptation is not ...,
        "montant_estime": montant_estime is not ...,
        "penalites_estimees": penalites_estimees is not ...,
        "derniere_revue": derniere_revue is not ...,
        "libelle": libelle is not ...,
    }
    if not any(champs.values()):
        raise ErreurRisque("aucun champ fourni")

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT id, contribuable_id, origine_conclusion_id, "
                "origine_mission_id, origine_tache_id, impot, reference_legale, "
                "libelle, montant_estime, penalites_estimees, probabilite, "
                "statut, exercice_origine, derniere_revue, motif_acceptation, "
                "accepte_le, accepte_par, prescrit_le, cree_le, maj_le "
                "FROM risque WHERE id = :id"
            ),
            {"id": risque_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurRisque(f"risque {risque_id} introuvable")
        ancien = dict(row)

        nouveau_statut = str(ancien.get("statut") or "ouvert")
        if champs["statut"]:
            if statut is None:
                raise ErreurRisque("statut ne peut pas être null")
            st = str(statut).strip().lower()
            if st not in STATUTS_RISQUE:
                raise ErreurRisque(
                    f"statut invalide {statut!r} — attendu : "
                    + ", ".join(sorted(STATUTS_RISQUE))
                )
            nouveau_statut = st

        motif = ancien.get("motif_acceptation")
        if champs["motif_acceptation"]:
            motif = (
                None
                if motif_acceptation is None
                else str(motif_acceptation).strip() or None
            )
        if nouveau_statut == "accepte" and not motif:
            raise ErreurRisque(
                "motif_acceptation obligatoire quand statut=accepte"
            )

        if (
            nouveau_statut == "resolu"
            and ancien.get("statut") != "resolu"
            and not avec_preuve
        ):
            from backend.plateforme.preuve_resolution import (
                MESSAGE_PREUVE_REQUISE,
                compter_preuves,
            )

            if compter_preuves(session, risque_id) == 0:
                raise ErreurRisque(MESSAGE_PREUVE_REQUISE)

        prob = str(ancien.get("probabilite") or "possible")
        if champs["probabilite"]:
            if probabilite is None:
                raise ErreurRisque("probabilite ne peut pas être null")
            prob = str(probabilite).strip().lower()
            if prob not in PROBABILITES:
                raise ErreurRisque(f"probabilite invalide {probabilite!r}")

        lib = str(ancien["libelle"])
        if champs["libelle"]:
            lib = str(libelle or "").strip()
            if not lib:
                raise ErreurRisque("libelle obligatoire")

        mt = ancien.get("montant_estime")
        if champs["montant_estime"]:
            mt = (
                None
                if montant_estime is None or montant_estime == ""
                else Decimal(str(montant_estime))
            )
        pen = ancien.get("penalites_estimees")
        if champs["penalites_estimees"]:
            pen = (
                None
                if penalites_estimees is None or penalites_estimees == ""
                else Decimal(str(penalites_estimees))
            )

        revue = ancien.get("derniere_revue")
        if champs["derniere_revue"]:
            if derniere_revue is None or derniere_revue == "":
                revue = None
            else:
                revue = date.fromisoformat(str(derniere_revue)[:10])

        accepte_le = ancien.get("accepte_le")
        accepte_par = ancien.get("accepte_par")
        prescrit_le = ancien.get("prescrit_le")
        if nouveau_statut == "accepte" and ancien.get("statut") != "accepte":
            accepte_le = datetime.utcnow()
            accepte_par = acteur
        if nouveau_statut == "prescrit" and ancien.get("statut") != "prescrit":
            prescrit_le = datetime.utcnow()

        session.execute(
            text(
                "UPDATE risque SET statut = :st, probabilite = :prob, "
                "motif_acceptation = :mot, montant_estime = :mt, "
                "penalites_estimees = :pen, derniere_revue = :rev, "
                "libelle = :lib, accepte_le = :al, accepte_par = :ap, "
                "prescrit_le = :pl, maj_le = now() WHERE id = :id"
            ),
            {
                "st": nouveau_statut,
                "prob": prob,
                "mot": motif,
                "mt": mt,
                "pen": pen,
                "rev": revue,
                "lib": lib,
                "al": accepte_le,
                "ap": accepte_par,
                "pl": prescrit_le,
                "id": risque_id,
            },
        )
        session.flush()
        return _lire(session, risque_id)


def resume_risques_contribuable(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Compteurs pour bandeau N+1 / fiche client."""
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT statut, count(*) AS n FROM risque "
                "WHERE contribuable_id = :c GROUP BY statut"
            ),
            {"c": contribuable_id},
        ).mappings().all()
        par_statut = {str(r["statut"]): int(r["n"]) for r in rows}
        retards = session.execute(
            text(
                "SELECT count(*) FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "WHERE r.contribuable_id = :c "
                "AND a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
                "AND a.statut IN ('acceptee', 'en_cours', 'preuve_deposee')"
            ),
            {"c": contribuable_id},
        ).scalar_one()
        refuses = session.execute(
            text(
                "SELECT count(*) FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "WHERE r.contribuable_id = :c AND a.statut = 'refusee'"
            ),
            {"c": contribuable_id},
        ).scalar_one()
        total = sum(par_statut.values())
        traites = (
            par_statut.get("resolu", 0)
            + par_statut.get("accepte", 0)
            + par_statut.get("prescrit", 0)
        )
        return {
            "contribuable_id": contribuable_id,
            "total": total,
            "ouverts": par_statut.get("ouvert", 0)
            + par_statut.get("en_traitement", 0),
            "en_traitement": par_statut.get("en_traitement", 0),
            "resolus": par_statut.get("resolu", 0),
            "acceptes_client": par_statut.get("accepte", 0),
            "prescrits": par_statut.get("prescrit", 0),
            "traites": traites,
            "actions_en_retard": int(retards or 0),
            "actions_refusees": int(refuses or 0),
            "par_statut": par_statut,
        }


_POIDS_PROBABILITE: Final[dict[str, int]] = {
    "probable": 12,
    "possible": 7,
    "faible": 3,
}
_LIBELLES_NIVEAU: Final[dict[str, str]] = {
    "aucun": "Aucun risque ouvert",
    "faible": "Risque faible",
    "modere": "Risque modéré",
    "eleve": "Risque élevé",
    "critique": "Risque critique",
}
# Fourchettes affichables — miroir exact des seuils de ``calculer_score_risque``.
# ``aucun`` : pas de plage (absence de risques non clos, pas un palier de score).
_PLAGES_NIVEAU: Final[dict[str, str | None]] = {
    "aucun": None,
    "faible": "0–19",
    "modere": "20–39",
    "eleve": "40–69",
    "critique": "70–100",
}
_JOURS_DORMANT: Final[int] = 90
_SCORE_MAX: Final[int] = 100


def _points_enjeu(cumul: Decimal) -> int:
    if cumul <= 0:
        return 0
    if cumul < Decimal("1000000"):
        return 5
    if cumul < Decimal("5000000"):
        return 10
    if cumul < Decimal("20000000"):
        return 15
    return 20


def _en_date(valeur: Any) -> date | None:
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def calculer_score_risque(donnees: dict[str, Any]) -> dict[str, Any]:
    """Score déterministe 0–100 du risque client (pure, testable).

    ``donnees`` : {
        "risques": [{statut, probabilite, montant_estime,
                     penalites_estimees, derniere_revue, cree_le,
                     exercice_origine, nb_actions}],
        "actions_en_retard": int,
        "actions_refusees": int,
        "aujourd_hui": date (optionnel, défaut date du jour),
    }
    """
    aujourd_hui = _en_date(donnees.get("aujourd_hui")) or date.today()
    risques = list(donnees.get("risques") or [])
    non_clos = [
        r for r in risques
        if str(r.get("statut") or "ouvert") in STATUTS_NON_CLOS
    ]

    # Exposition — poids par probabilité des risques non clos.
    pts_exposition = sum(
        _POIDS_PROBABILITE.get(
            str(r.get("probabilite") or "possible").lower(), 7
        )
        for r in non_clos
    )

    # Enjeu financier — cumul montant + pénalités des risques non clos.
    cumul = Decimal("0")
    for r in non_clos:
        for cle in ("montant_estime", "penalites_estimees"):
            v = r.get(cle)
            if v is not None and v != "":
                cumul += Decimal(str(v))
    pts_enjeu = _points_enjeu(cumul)

    # Suivi en retard — +8 pts / action en retard, plafonné à 24.
    retards = int(donnees.get("actions_en_retard") or 0)
    pts_retards = min(retards * 8, 24)

    # Risques dormants — sans revue depuis > 90 jours.
    dormants = 0
    for r in non_clos:
        ref = _en_date(r.get("derniere_revue")) or _en_date(r.get("cree_le"))
        if ref is None or (aujourd_hui - ref).days > _JOURS_DORMANT:
            dormants += 1
    pts_dormants = min(dormants * 5, 20)

    # Actions refusées — +4 pts chacune, plafonné à 12.
    refusees = int(donnees.get("actions_refusees") or 0)
    pts_refusees = min(refusees * 4, 12)

    score = min(
        pts_exposition + pts_enjeu + pts_retards + pts_dormants + pts_refusees,
        _SCORE_MAX,
    )

    if not non_clos:
        niveau = "aucun"
    elif score < 20:
        niveau = "faible"
    elif score < 40:
        niveau = "modere"
    elif score < 70:
        niveau = "eleve"
    else:
        niveau = "critique"

    facteurs = [
        {
            "code": "exposition",
            "libelle": "Exposition (risques non clos)",
            "points": pts_exposition,
            "detail": f"{len(non_clos)} risque(s) non clos",
        },
        {
            "code": "enjeu_financier",
            "libelle": "Enjeu financier",
            "points": pts_enjeu,
            "detail": f"{cumul:,.0f} FCFA en jeu".replace(",", " "),
        },
        {
            "code": "actions_retard",
            "libelle": "Suivi en retard",
            "points": pts_retards,
            "detail": f"{retards} action(s) en retard",
        },
        {
            "code": "dormants",
            "libelle": "Risques dormants (> 90 j sans revue)",
            "points": pts_dormants,
            "detail": f"{dormants} risque(s) dormant(s)",
        },
        {
            "code": "actions_refusees",
            "libelle": "Actions refusées par le client",
            "points": pts_refusees,
            "detail": f"{refusees} action(s) refusée(s)",
        },
    ]

    alertes: list[str] = []
    probables_sans_action = sum(
        1
        for r in non_clos
        if str(r.get("probabilite") or "").lower() == "probable"
        and int(r.get("nb_actions") or 0) == 0
    )
    if probables_sans_action:
        alertes.append(
            f"{probables_sans_action} risque(s) probable(s) sans action "
            "de suivi — proposer une action corrective"
        )
    if retards:
        alertes.append(
            f"{retards} action(s) en retard — relancer le client"
        )
    if dormants:
        alertes.append(
            f"{dormants} risque(s) sans revue depuis plus de "
            f"{_JOURS_DORMANT} jours — planifier une revue"
        )
    prescriptibles = sum(
        1
        for r in non_clos
        if int(r.get("exercice_origine") or aujourd_hui.year)
        <= aujourd_hui.year - 3
    )
    if prescriptibles:
        alertes.append(
            f"{prescriptibles} risque(s) d'exercices ≤ N-3 — vérifier "
            "la prescription (art. L171 s. LPF)"
        )
    if refusees:
        alertes.append(
            f"{refusees} action(s) refusée(s) — documenter l'acceptation "
            "du risque par le client"
        )

    return {
        "score": score,
        "niveau": niveau,
        "libelle_niveau": _LIBELLES_NIVEAU[niveau],
        "plage": _PLAGES_NIVEAU[niveau],
        "facteurs": facteurs,
        "alertes": alertes,
        "exposition_totale": str(cumul),
    }


def score_risque_contribuable(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Score de risque agrégé d'un contribuable (calcul déterministe)."""
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT r.statut, r.probabilite, r.montant_estime, "
                "r.penalites_estimees, r.derniere_revue, r.cree_le, "
                "r.exercice_origine, "
                "(SELECT count(*) FROM action_risque a "
                " WHERE a.risque_id = r.id) AS nb_actions "
                "FROM risque r WHERE r.contribuable_id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().all()
        retards = session.execute(
            text(
                "SELECT count(*) FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "WHERE r.contribuable_id = :c "
                "AND a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
                "AND a.statut IN ('acceptee', 'en_cours', 'preuve_deposee')"
            ),
            {"c": contribuable_id},
        ).scalar_one()
        refusees = session.execute(
            text(
                "SELECT count(*) FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "WHERE r.contribuable_id = :c AND a.statut = 'refusee'"
            ),
            {"c": contribuable_id},
        ).scalar_one()
    resultat = calculer_score_risque(
        {
            "risques": [dict(r) for r in rows],
            "actions_en_retard": int(retards or 0),
            "actions_refusees": int(refusees or 0),
        }
    )
    resultat["contribuable_id"] = contribuable_id
    return resultat


def creer_risques_depuis_anomalies(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> int:
    """À la clôture : un risque par tâche anomalie liée (idempotent)."""
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT t.id AS tache_id, t.conclusion_id, "
                "m.contribuable_id, m.exercice, "
                "c.montant, c.commentaire, "
                "rv.regle_id, rv.reference_article, "
                "reg.impot, reg.libelle AS regle_libelle "
                "FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "JOIN mission m ON m.id = o.mission_id "
                "JOIN conclusion c ON c.id = t.conclusion_id "
                "JOIN regle_version rv ON rv.id = t.regle_version_id "
                "JOIN regle reg ON reg.identifiant = rv.regle_id "
                "WHERE o.mission_id = :m AND t.statut = 'anomalie' "
                "AND t.conclusion_id IS NOT NULL"
            ),
            {"m": mission_id},
        ).mappings().all()

    nb = 0
    for r in rows:
        cid = int(r["conclusion_id"])
        avant = None
        with contexte_tenant(session, tenant_id):
            avant = session.execute(
                text(
                    "SELECT id FROM risque "
                    "WHERE origine_conclusion_id = :c LIMIT 1"
                ),
                {"c": cid},
            ).scalar_one_or_none()
        if avant is not None:
            continue
        libelle = (
            f"Anomalie — {r.get('regle_libelle') or r.get('regle_id')}"
        )
        if r.get("commentaire") and str(r["commentaire"]).strip():
            libelle = f"{libelle} — {str(r['commentaire']).strip()[:200]}"
        montant = r.get("montant")
        impot = str(r.get("impot") or "").strip()
        if not impot:
            continue
        creer_risque(
            session,
            tenant_id,
            contribuable_id=int(r["contribuable_id"]),
            impot=impot,
            libelle=libelle,
            exercice_origine=int(r["exercice"] or 0),
            probabilite="possible",
            reference_legale=(
                str(r["reference_article"]).strip()
                if r.get("reference_article")
                else None
            ),
            montant_estime=(
                Decimal(str(montant)) if montant is not None else None
            ),
            origine_conclusion_id=cid,
            origine_mission_id=mission_id,
            origine_tache_id=int(r["tache_id"]),
        )
        nb += 1
    return nb
