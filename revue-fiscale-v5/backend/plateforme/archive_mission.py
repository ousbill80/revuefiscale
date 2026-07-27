"""Dossier de travail de mission — archive ZIP probante (piste d'audit).

À la clôture d'une mission de revue fiscale, le cabinet constitue un
dossier de travail archivable regroupant tous les livrables déjà connus
de l'application : lettre de mission, rapports de restitution (Word et
PDF), rapport des risques du contribuable, demande de renseignements,
suivi de circularisation et contrôle qualité de pré-clôture.

Assemblage DÉTERMINISTE (aucun appel LLM, lecture seule sous RLS via
``contexte_tenant``) : chaque pièce est produite par la MÊME fonction de
génération que son endpoint dédié (imports directs — jamais d'appel HTTP
interne). Une pièce qui échoue est OMISE et la raison est notée dans le
sommaire ``00_sommaire.txt`` : l'archive n'échoue jamais entièrement
pour une pièce manquante.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.comparatif_executions import comparer_executions
from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.controle_cloture import evaluer_cloture
from backend.plateforme.courrier_envoi_rapport import generer_courrier_envoi
from backend.plateforme.demande_renseignements import (
    generer_demande_renseignements,
)
from backend.plateforme.echeancier_fiscal import echeancier_mission
from backend.plateforme.lettre_affirmation import generer_lettre_affirmation
from backend.plateforme.lettre_mission import generer_lettre_mission
from backend.plateforme.prescription_risques import (
    analyse_mission as analyse_prescription_risques,
)
from backend.plateforme.programme_travail import etat_programme
from backend.plateforme.provision_risques import calculer_provision
from backend.plateforme.rapport_risques import exporter_rapport_risques_pdf
from backend.plateforme.rentabilite_mission import rentabilite_mission
from backend.plateforme.reponses_client import lister_reponses
from backend.plateforme.suivi_renseignements import (
    lister_items,
    synthese_depuis_items,
)
from backend.plateforme.temps_mission import recap_temps
from backend.plateforme.visas_mission import ORDRE_ROLES, etat_visas
from backend.restitution.rapport_docx import rendre_rapport_docx
from backend.restitution.rapport_pdf import rendre_rapport_pdf
from backend.restitution.routes import (
    _enrichissements_export,
    _meta_export_complet,
    dernier_commentaire_analytique_disponible,
    derniere_note_synthese_disponible,
    risques_ouverts_chiffres,
)
from backend.restitution.service import lire_audit, produire_restitution

# En-tête du CSV de suivi — délimiteur « ; » (usage cabinet / Excel FR).
ENTETE_SUIVI_CSV: Final = ("cle_item", "libelle", "statut", "date_relance", "note")

_LIBELLES_STATUT_POINT: Final[dict[str, str]] = {
    "ok": "OK",
    "attention": "ATTENTION",
    "bloquant": "BLOQUANT",
}


class ErreurArchiveMission(Exception):
    """Echec de constitution du dossier de travail."""


class ErreurArchiveIntrouvable(ErreurArchiveMission):
    """Mission hors périmètre du tenant — 404 côté route."""


def nom_fichier_dossier(
    denomination: object | None, exercice: object | None
) -> str:
    """dossier_travail_{NOM}_{exercice}.zip — nom ASCII sûr (en-tête HTTP)."""
    brut = str(denomination or "client")
    sans_accents = (
        unicodedata.normalize("NFKD", brut).encode("ascii", "ignore").decode("ascii")
    )
    nom = re.sub(r"[^A-Za-z0-9]+", "_", sans_accents).strip("_").upper() or "CLIENT"
    exo = str(exercice or "exercice").strip() or "exercice"
    exo = re.sub(r"[^A-Za-z0-9]+", "_", exo) or "exercice"
    return f"dossier_travail_{nom}_{exo}.zip"


def _meta_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Mission + contribuable (RLS) + cabinet — 404 si hors tenant."""
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.id, m.exercice, m.statut, m.contribuable_id, "
                "c.denomination AS contribuable_denomination, c.ncc "
                "FROM mission m JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurArchiveIntrouvable(f"mission {mission_id} introuvable")
    cabinet = session.execute(
        text("SELECT denomination FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()
    meta = dict(row)
    meta["cabinet_denomination"] = cabinet
    return meta


# ── Constructeurs de pièces (une fonction = une pièce, indépendante) ──


def _piece_lettre_mission(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    contenu, _nom = generer_lettre_mission(session, tenant_id, mission_id)
    return contenu


def _donnees_rapport_restitution(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Mêmes collectes que les endpoints /restitution/rapport.docx|.pdf."""
    r = produire_restitution(session, tenant_id, mission_id)
    return {
        "meta": _meta_export_complet(session, tenant_id, mission_id, r),
        "passage": r.passage,
        "conclusions": r.conclusions,
        "score": r.score_risque,
        "extrait_audit": lire_audit(session, tenant_id, mission_id, limite=20),
        "enrichissements": _enrichissements_export(session, tenant_id, mission_id),
        "note_synthese": derniere_note_synthese_disponible(
            session, tenant_id, mission_id
        ),
        "commentaire_analytique": dernier_commentaire_analytique_disponible(
            session, tenant_id, mission_id
        ),
        "risques_chiffres": risques_ouverts_chiffres(
            session, tenant_id, mission_id
        ),
    }


def _rendre_restitution(
    session: Session,
    tenant_id: int,
    mission_id: int,
    rendu: Callable[..., bytes],
) -> bytes:
    d = _donnees_rapport_restitution(session, tenant_id, mission_id)
    controles_fec, revue_analytique = d["enrichissements"]
    return rendu(
        meta=d["meta"],
        passage=d["passage"],
        conclusions=d["conclusions"],
        score=d["score"],
        extrait_audit=d["extrait_audit"],
        controles_fec=controles_fec,
        revue_analytique=revue_analytique,
        note_synthese=d["note_synthese"],
        commentaire_analytique=d["commentaire_analytique"],
        risques_chiffres=d["risques_chiffres"],
    )


def _piece_rapport_restitution_docx(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    return _rendre_restitution(session, tenant_id, mission_id, rendre_rapport_docx)


def _piece_rapport_restitution_pdf(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    return _rendre_restitution(session, tenant_id, mission_id, rendre_rapport_pdf)


def _piece_rapport_risques_pdf(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    _nom, contenu = exporter_rapport_risques_pdf(
        session, tenant_id, int(meta["contribuable_id"])
    )
    return contenu


def _piece_demande_renseignements(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    contenu, _nom, stats = generer_demande_renseignements(
        session, tenant_id, mission_id
    )
    if sum(int(v) for v in stats.values()) == 0:
        raise ErreurArchiveMission(
            "aucun item à demander (ni question analytique, ni pièce attendue)"
        )
    return contenu


def _piece_suivi_circularisation(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    items = lister_items(session, tenant_id, mission_id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_SUIVI_CSV)
    for it in items:
        w.writerow([str(it.get(c) or "") for c in ENTETE_SUIVI_CSV])
    s = synthese_depuis_items(items)
    w.writerow([])
    w.writerow(
        [
            "synthese",
            f"total={s['total']}",
            f"recu={s['recu']}",
            f"en_attente={s['en_attente']}",
            f"sans_objet={s['sans_objet']} a_relancer={s['a_relancer']}",
        ]
    )
    return buf.getvalue().encode("utf-8")


def _piece_controle_cloture(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    c = evaluer_cloture(session, tenant_id, mission_id)
    lignes = [
        "CONTRÔLE QUALITÉ DE PRÉ-CLÔTURE — consultatif, déterministe",
        f"Mission #{c['mission_id']} — statut : {c['statut_mission']}",
        "Clôture recommandée : "
        + ("oui" if c.get("cloture_recommandee") else "non"),
        "",
    ]
    for p in c.get("points", []):
        statut = _LIBELLES_STATUT_POINT.get(
            str(p.get("statut")), str(p.get("statut", "")).upper()
        )
        lignes.append(f"[{statut}] {p.get('libelle')}")
        lignes.append(f"    {p.get('detail')}")
    s = c.get("synthese", {})
    lignes += [
        "",
        f"Synthèse : {s.get('ok', 0)} ok, {s.get('attention', 0)} attention, "
        f"{s.get('bloquant', 0)} bloquant.",
    ]
    return "\n".join(lignes).encode("utf-8")


_LIBELLES_CATEGORIES_COMPARATIF: Final[tuple[tuple[str, str], ...]] = (
    ("ameliorations", "AMÉLIORATIONS"),
    ("degradations", "DÉGRADATIONS"),
    ("inchanges_a_risque", "INCHANGÉS À RISQUE"),
    ("nouveaux", "NOUVELLES RÈGLES"),
    ("disparus", "RÈGLES DISPARUES"),
)


def _piece_comparatif_executions(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    c = comparer_executions(session, tenant_id, mission_id)
    ea, eb = c["execution_a"], c["execution_b"]
    lignes = [
        "COMPARATIF DES DEUX DERNIÈRES EXÉCUTIONS — déterministe",
        f"Mission #{mission_id} — exécution #{ea['id']}"
        + (f" ({ea['date']})" if ea.get("date") else "")
        + f" → exécution #{eb['id']}"
        + (f" ({eb['date']})" if eb.get("date") else ""),
        "",
    ]
    for cle, libelle in _LIBELLES_CATEGORIES_COMPARATIF:
        items = c.get(cle, [])
        lignes.append(f"{libelle} ({len(items)})")
        for it in items:
            transition = f"{it.get('avant') or '—'} → {it.get('apres') or '—'}"
            montants = ""
            if it.get("montant_avant") is not None or it.get("montant_apres") is not None:
                montants = (
                    f" | montant : {it.get('montant_avant') or '—'}"
                    f" → {it.get('montant_apres') or '—'}"
                )
            lignes.append(f"  - {it['regle_id']} : {transition}{montants}")
        if not items:
            lignes.append("  (aucune)")
        lignes.append("")
    s = c.get("synthese", {})
    lignes.append(
        "Synthèse : "
        f"{s.get('ameliorations', 0)} amélioration(s), "
        f"{s.get('degradations', 0)} dégradation(s), "
        f"{s.get('inchanges_a_risque', 0)} inchangé(s) à risque, "
        f"{s.get('nouveaux', 0)} nouvelle(s), {s.get('disparus', 0)} disparue(s)."
    )
    lignes.append(
        "Delta montant des anomalies : "
        f"{s.get('delta_montant_anomalies', '0')} FCFA."
    )
    return "\n".join(lignes).encode("utf-8")


def _piece_provision_risques(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    p = calculer_provision(session, tenant_id, int(meta["contribuable_id"]))
    if not p["lignes"] and not p["passifs_eventuels"]:
        raise ErreurArchiveMission(
            "aucun risque ouvert à provisionner ni passif éventuel"
        )
    lignes = [
        "PROVISION POUR RISQUES FISCAUX — proposition indicative (SYSCOHADA)",
        f"Client : {meta.get('contribuable_denomination') or '[non renseigné]'}",
        "",
        f"RISQUES PROVISIONNABLES ({len(p['lignes'])})",
    ]
    for li in p["lignes"]:
        lignes.append(
            f"  - #{li['risque_id']} {li['titre']} ({li['impot']}, "
            f"exercice {li['exercice']}) : droit simple {li['base_droit_simple']}"
            f" + pénalités/intérêts {li['penalites_interets']}"
            f" = {li['montant_provisionnable']} FCFA"
        )
    if not p["lignes"]:
        lignes.append("  (aucun)")
    lignes += ["", f"Total provision proposée : {p['total_provision']} FCFA", ""]
    lignes.append(f"PASSIFS ÉVENTUELS ({len(p['passifs_eventuels'])})")
    for pe in p["passifs_eventuels"]:
        lignes.append(
            f"  - #{pe['risque_id']} {pe['titre']} : {pe['montant_estime']} FCFA"
        )
    if not p["passifs_eventuels"]:
        lignes.append("  (aucun)")
    e = p["ecriture_proposee"]
    lignes += ["", f"ÉCRITURE PROPOSÉE — {e['libelle']}"]
    for le in e["lignes"]:
        lignes.append(
            f"  {le['sens'].upper():6} {le['compte']} {le['intitule']} : "
            f"{le['montant']} FCFA"
        )
    lignes += [""] + [f"* {h}" for h in p.get("hypotheses", [])]
    return "\n".join(lignes).encode("utf-8")


# En-tête du CSV des temps — délimiteur « ; » (usage cabinet / Excel FR).
ENTETE_TEMPS_CSV: Final = ("date_jour", "collaborateur", "phase", "heures", "note")


def _piece_temps_mission(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Feuille de temps CSV — valorisation OMISE (pas de taux à l'archive)."""
    r = recap_temps(session, tenant_id, mission_id)
    if not r["entrees"]:
        raise ErreurArchiveMission("aucun temps saisi sur la mission")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_TEMPS_CSV)
    for e in r["entrees"]:
        w.writerow([str(e.get(c) or "") for c in ENTETE_TEMPS_CSV])
    w.writerow([])
    w.writerow(["synthese", f"total_heures={r['total_heures']}"])
    for phase, heures in r["par_phase"].items():
        w.writerow(["par_phase", phase, heures])
    for collab, heures in r["par_collaborateur"].items():
        w.writerow(["par_collaborateur", collab, heures])
    return buf.getvalue().encode("utf-8")


def _piece_visas_supervision(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    v = etat_visas(session, tenant_id, mission_id)
    s = v.get("synthese", {})
    if not int(s.get("total_visas", 0)):
        raise ErreurArchiveMission("aucun visa posé sur la mission")
    lignes = [
        "REGISTRE DES VISAS DE SUPERVISION — par phase de mission",
        f"Mission #{mission_id} — ordre hiérarchique : "
        + " < ".join(ORDRE_ROLES),
        "",
    ]
    for p in v.get("phases", []):
        visas = p.get("visas", [])
        etat = "complète" if p.get("complet") else "incomplète"
        lignes.append(f"PHASE {str(p.get('phase', '')).upper()} — {etat}")
        for visa in visas:
            ligne = (
                f"  [VISÉ] {visa['role']} : {visa['vise_par']} "
                f"le {visa['vise_le']}"
            )
            if visa.get("commentaire"):
                ligne += f" — {visa['commentaire']}"
            lignes.append(ligne)
        presents = {visa["role"] for visa in visas}
        for role in ORDRE_ROLES:
            if role not in presents:
                lignes.append(f"  [MANQUANT] {role}")
        lignes.append("")
    lignes.append(
        "Synthèse : "
        f"{s.get('phases_completes', 0)} phase(s) complète(s), "
        f"{s.get('total_visas', 0)} visa(s) posé(s)."
    )
    return "\n".join(lignes).encode("utf-8")


def _piece_reponses_client(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    reponses = lister_reponses(session, tenant_id, mission_id)
    if not reponses:
        raise ErreurArchiveMission("aucune réponse client saisie")
    lignes = [
        "RÉPONSES CLIENT SAISIES — traçabilité avant re-contrôle",
        f"Mission #{mission_id} — {len(reponses)} réponse(s)",
        "",
    ]
    for r in reponses:
        lignes.append(f"ITEM {r['cle_item']}")
        lignes.append(f"  Contenu : {r['contenu']}")
        lignes.append(
            f"  Pièces reçues : {r.get('pieces_recues') or '(aucune)'}"
        )
        lignes.append(f"  Saisie par : {r['saisie_par']} le {r['saisie_le']}")
        if r.get("statut_derniere_execution"):
            lignes.append(
                f"  Statut de la règle {r.get('regle_id')} en dernière "
                f"exécution : {r['statut_derniere_execution']}"
            )
        lignes.append("")
    return "\n".join(lignes).encode("utf-8")


def _piece_programme_travail(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    etat = etat_programme(session, tenant_id, mission_id)
    s = etat["synthese"]
    lignes = [
        "PROGRAMME DE TRAVAIL — avancement des diligences par phase",
        f"Mission #{mission_id} — {s['faites']}/{s['total']} diligences "
        f"faites ({s['avancement_pct']} %)",
        "",
    ]
    for p in etat["phases"]:
        lignes.append(
            f"PHASE {str(p['phase']).upper()} — {p['faites']}/{p['total']} "
            f"({p['avancement_pct']} %)"
        )
        for d in p["diligences"]:
            if d["fait"]:
                lignes.append(
                    f"  [FAIT par {d['fait_par']} le {d['fait_le']}] "
                    f"{d['code']} — {d['libelle']}"
                )
            else:
                lignes.append(f"  [À FAIRE] {d['code']} — {d['libelle']}")
        lignes.append("")
    lignes.append(
        f"Synthèse : {s['faites']}/{s['total']} diligences faites "
        f"({s['avancement_pct']} %)."
    )
    return "\n".join(lignes).encode("utf-8")


def _piece_echeancier_fiscal(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Échéancier fiscal de l'exercice revu — toujours produit (les dates
    se calculent quel que soit l'état de la mission)."""
    e = echeancier_mission(session, tenant_id, mission_id)
    lignes = [
        "ÉCHÉANCIER FISCAL DE L'EXERCICE REVU — indicatif (pratique CGI CI)",
        f"Mission #{e['mission_id']} — exercice {e['exercice']} — "
        f"régime : {e['regime']}"
        + (" — relève de la DGE" if e.get("dge") else ""),
        "",
    ]
    par_impot: dict[str, list[dict[str, Any]]] = {}
    for item in e["echeances"]:
        par_impot.setdefault(str(item["impot"]), []).append(item)
    for impot, items in par_impot.items():
        lignes.append(f"{impot.upper()} ({len(items)} échéance(s))")
        for it in items:
            lignes.append(
                f"  - {it['date_limite']} : {it['obligation']} "
                f"[{it['periode']}] ({it['base_legale']})"
            )
        lignes.append("")
    s = e["synthese"]
    lignes.append(
        f"Synthèse : {s['total']} échéance(s) — "
        + ", ".join(f"{i} : {n}" for i, n in s["par_impot"].items())
        + "."
    )
    lignes.append(
        "Dates indicatives (hypothèses documentées) — vérifier le "
        "calendrier officiel DGI de l'exercice."
    )
    return "\n".join(lignes).encode("utf-8")


def _piece_courrier_envoi(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Courrier d'envoi du rapport — toujours produit (même sans exécution :
    la lettre mentionne alors « constats en cours d'instruction »)."""
    return generer_courrier_envoi(session, tenant_id, mission_id)


def _piece_lettre_affirmation(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Lettre d'affirmation de la direction — toujours produite (les
    compteurs de risques/anomalies valent 0 sans exécution ni risque)."""
    contenu, _nom = generer_lettre_affirmation(session, tenant_id, mission_id)
    return contenu


def _piece_rentabilite(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Rentabilité de la mission — honoraires, temps valorisé, marge.

    Réutilise :func:`rentabilite_mission` (Decimal, jamais de float) et le
    récap des temps. Sans aucun paramètre convenu (ni honoraires, ni taux
    horaire), la pièce est OMISE : rien à valoriser."""
    r = rentabilite_mission(session, tenant_id, mission_id)
    if r["honoraires"] is None and r["taux_horaire"] is None:
        raise ErreurArchiveMission(
            "paramètres de rentabilité non renseignés "
            "(honoraires ou taux horaire)"
        )
    recap = recap_temps(session, tenant_id, mission_id)
    taux = None if r["taux_horaire"] is None else Decimal(r["taux_horaire"])

    def _heures_valorisees(heures: str) -> str:
        if taux is None:
            return f"{heures} h (non valorisé — taux horaire non renseigné)"
        montant = format((Decimal(heures) * taux).normalize(), "f")
        return f"{heures} h = {montant} FCFA"

    lignes = [
        "RENTABILITÉ DE LA MISSION — honoraires, temps valorisé, marge",
        f"Mission #{mission_id} — client : "
        f"{meta.get('contribuable_denomination') or '[non renseigné]'}",
        "",
        "Honoraires convenus : "
        + (
            f"{r['honoraires']} FCFA"
            if r["honoraires"] is not None
            else "[non convenus]"
        ),
        "Taux horaire        : "
        + (
            f"{r['taux_horaire']} FCFA/h"
            if r["taux_horaire"] is not None
            else "[non renseigné]"
        ),
        f"Heures saisies      : {r['total_heures']} h",
        "",
        f"TEMPS PAR PHASE ({len(recap['par_phase'])})",
    ]
    for phase, heures in recap["par_phase"].items():
        lignes.append(f"  - {phase} : {_heures_valorisees(heures)}")
    if not recap["par_phase"]:
        lignes.append("  (aucun temps saisi)")
    lignes += ["", f"TEMPS PAR COLLABORATEUR ({len(recap['par_collaborateur'])})"]
    for collab, heures in recap["par_collaborateur"].items():
        lignes.append(f"  - {collab} : {_heures_valorisees(heures)}")
    if not recap["par_collaborateur"]:
        lignes.append("  (aucun temps saisi)")
    lignes += [
        "",
        "Coût total estimé : "
        + (
            f"{r['cout_estime']} FCFA"
            if r["cout_estime"] is not None
            else "[non calculable — taux horaire non renseigné]"
        ),
        "Marge estimée     : "
        + (
            f"{r['marge_estimee']} FCFA"
            if r["marge_estimee"] is not None
            else "[non calculable — honoraires ou taux horaire manquant]"
        ),
        "Taux de marge     : "
        + (
            f"{r['taux_marge_pct']} %"
            if r["taux_marge_pct"] is not None
            else "[non calculable]"
        ),
    ]
    return "\n".join(lignes).encode("utf-8")


_LIBELLES_CATEGORIES_PRESCRIPTION: Final[tuple[tuple[str, str], ...]] = (
    ("prescrits_a_basculer", "RISQUES PRESCRITS À BASCULER"),
    ("proches_prescription", "RISQUES PROCHES DE LA PRESCRIPTION (12 MOIS)"),
    ("non_prescrits", "RISQUES NON PRESCRITS (EXERCICES REPRENABLES)"),
)


def _piece_prescription_risques(
    session: Session, tenant_id: int, mission_id: int, meta: dict[str, Any]
) -> bytes:
    """Analyse de prescription des risques — toujours produite (les listes
    sont simplement vides sans risque non clos). ``analyse_mission`` ouvre
    son propre ``contexte_tenant`` : appel HORS de tout autre contexte."""
    a = analyse_prescription_risques(session, tenant_id, mission_id)
    lignes = [
        "PRESCRIPTION DES RISQUES — analyse consultative (pratique LPF CI)",
        f"Mission #{a['mission_id']} — client : "
        f"{meta.get('contribuable_denomination') or '[non renseigné]'} — "
        f"analyse au {a['date_analyse']}",
        "Exercices encore reprenables (droit commun) : "
        + ", ".join(str(e) for e in a["exercices_reprenables"]),
        "",
    ]
    for cle, libelle in _LIBELLES_CATEGORIES_PRESCRIPTION:
        items = a["analyse"].get(cle, [])
        lignes.append(f"{libelle} ({len(items)})")
        for it in items:
            montant = (
                f"{it['montant']} FCFA"
                if it.get("montant") is not None
                else "montant non chiffré"
            )
            lignes.append(
                f"  - #{it['risque_id']} {it['libelle']} ({it['impot']}, "
                f"exercice {it['exercice_origine']}) : {montant} — "
                f"prescription le {it['date_prescription']}"
            )
        if not items:
            lignes.append("  (aucun)")
        lignes.append("")
    lignes.append(
        "Exposition prescrite (à sortir du chiffrage) : "
        f"{a['analyse']['exposition_prescrite']} FCFA"
    )
    lignes += ["", f"* {a['hypothese']}"]
    return "\n".join(lignes).encode("utf-8")


# Ordre du dossier : (nom de fichier dans le ZIP, description, constructeur).
_PIECES: Final[
    tuple[tuple[str, str, Callable[[Session, int, int, dict[str, Any]], bytes]], ...]
] = (
    (
        "01_lettre_mission.docx",
        "Lettre de mission (cadrage, à signer)",
        _piece_lettre_mission,
    ),
    (
        "02_rapport_restitution.docx",
        "Rapport de restitution (Word)",
        _piece_rapport_restitution_docx,
    ),
    (
        "03_rapport_restitution.pdf",
        "Rapport de restitution (PDF)",
        _piece_rapport_restitution_pdf,
    ),
    (
        "04_rapport_risques.pdf",
        "Rapport des risques fiscaux du contribuable",
        _piece_rapport_risques_pdf,
    ),
    (
        "05_demande_renseignements.docx",
        "Demande de renseignements et de documents",
        _piece_demande_renseignements,
    ),
    (
        "06_suivi_circularisation.csv",
        "Suivi de circularisation (items et statuts)",
        _piece_suivi_circularisation,
    ),
    (
        "07_controle_cloture.txt",
        "Contrôle qualité de pré-clôture",
        _piece_controle_cloture,
    ),
    (
        "08_comparatif_executions.txt",
        "Comparatif des deux dernières exécutions",
        _piece_comparatif_executions,
    ),
    (
        "09_provision_risques.txt",
        "Provision pour risques fiscaux proposée (indicatif)",
        _piece_provision_risques,
    ),
    (
        "10_temps_mission.csv",
        "Feuille de temps de la mission (par phase et collaborateur)",
        _piece_temps_mission,
    ),
    (
        "11_visas_supervision.txt",
        "Registre des visas de supervision par phase",
        _piece_visas_supervision,
    ),
    (
        "12_reponses_client.txt",
        "Réponses client saisies (traçabilité avant re-contrôle)",
        _piece_reponses_client,
    ),
    (
        "13_programme_travail.txt",
        "Programme de travail et avancement des diligences",
        _piece_programme_travail,
    ),
    (
        "14_courrier_envoi_rapport.docx",
        "Courrier d'envoi du rapport au client",
        _piece_courrier_envoi,
    ),
    (
        "15_echeancier_fiscal.txt",
        "Échéancier fiscal de l'exercice revu",
        _piece_echeancier_fiscal,
    ),
    (
        "16_rentabilite_mission.txt",
        "Rentabilité de la mission (honoraires, temps valorisé, marge)",
        _piece_rentabilite,
    ),
    (
        "17_lettre_affirmation.docx",
        "Lettre d'affirmation de la direction (à faire signer)",
        _piece_lettre_affirmation,
    ),
    (
        "18_prescription_risques.txt",
        "Analyse de prescription des risques (délai de reprise)",
        _piece_prescription_risques,
    ),
)


def _sommaire(
    meta: dict[str, Any],
    incluses: list[tuple[str, str]],
    omises: list[tuple[str, str]],
) -> bytes:
    genere_le = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    lignes = [
        "DOSSIER DE TRAVAIL — MISSION DE REVUE FISCALE",
        "=" * 46,
        f"Cabinet   : {meta.get('cabinet_denomination') or '[non renseigné]'}",
        f"Client    : {meta.get('contribuable_denomination') or '[non renseigné]'}"
        + (f" (NCC : {meta['ncc']})" if meta.get("ncc") else ""),
        f"Mission   : #{meta.get('id')} — statut : {meta.get('statut')}",
        f"Exercice  : {meta.get('exercice')}",
        f"Généré le : {genere_le}",
        "",
        f"PIÈCES INCLUSES ({len(incluses)})",
    ]
    for nom, description in incluses:
        lignes.append(f"  - {nom} : {description}")
    if not incluses:
        lignes.append("  (aucune)")
    lignes += ["", f"PIÈCES OMISES ({len(omises)})"]
    for nom, raison in omises:
        lignes.append(f"  - {nom} : OMISE — {raison}")
    if not omises:
        lignes.append("  (aucune)")
    lignes += [
        "",
        "Dossier constitué automatiquement (assemblage déterministe) pour",
        "archivage probant — chaque pièce est produite par le même module",
        "que son téléchargement individuel dans l'application.",
    ]
    return "\n".join(lignes).encode("utf-8")


def construire_dossier(
    session: Session, tenant_id: int, mission_id: int
) -> tuple[bytes, str, dict[str, Any]]:
    """ZIP + nom de fichier + stats {pieces_incluses, pieces_omises}.

    Chaque pièce est tentée indépendamment (try/except) : un échec est
    consigné dans le sommaire, jamais propagé. Seule une mission hors
    tenant (RLS) lève :class:`ErreurArchiveIntrouvable` (→ 404).
    """
    meta = _meta_mission(session, tenant_id, mission_id)
    incluses: list[tuple[str, str]] = []
    omises: list[tuple[str, str]] = []
    contenus: list[tuple[str, bytes]] = []
    for nom, description, construire in _PIECES:
        try:
            contenus.append((nom, construire(session, tenant_id, mission_id, meta)))
            incluses.append((nom, description))
        except Exception as e:  # une pièce ne doit jamais faire échouer l'archive
            omises.append((nom, str(e) or e.__class__.__name__))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("00_sommaire.txt", _sommaire(meta, incluses, omises))
        for nom, contenu in contenus:
            z.writestr(nom, contenu)
    nom_zip = nom_fichier_dossier(
        meta.get("contribuable_denomination"), meta.get("exercice")
    )
    stats = {
        "pieces_incluses": [n for n, _ in incluses],
        "pieces_omises": [n for n, _ in omises],
    }
    return buf.getvalue(), nom_zip, stats


def construire_archive(
    session: Session, tenant_id: int, mission_id: int
) -> bytes:
    """Bytes du ZIP du dossier de travail — point d'entrée simple."""
    contenu, _nom, _stats = construire_dossier(session, tenant_id, mission_id)
    return contenu
