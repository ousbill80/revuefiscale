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
from typing import Any, Callable, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.controle_cloture import evaluer_cloture
from backend.plateforme.demande_renseignements import (
    generer_demande_renseignements,
)
from backend.plateforme.lettre_mission import generer_lettre_mission
from backend.plateforme.rapport_risques import exporter_rapport_risques_pdf
from backend.plateforme.suivi_renseignements import (
    lister_items,
    synthese_depuis_items,
)
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
