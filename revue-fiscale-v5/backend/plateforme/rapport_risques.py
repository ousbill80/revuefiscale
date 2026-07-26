"""Rapport PDF « Synthèse des risques fiscaux » d'un contribuable.

Livrable consolidé tous exercices, présentable en comité : exposition
totale ouverte vs traitée, répartition par impôt et par statut, top
risques, historique de résolution (preuves), recommandations. Lecture
seule — aucune écriture en base.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import (
    STATUTS_NON_CLOS,
    lister_risques,
    score_risque_contribuable,
)

TOP_RISQUES_MAX: Final[int] = 10

_LIBELLES_STATUT: Final[dict[str, str]] = {
    "ouvert": "Ouvert",
    "en_traitement": "En traitement",
    "resolu": "Résolu",
    "accepte": "Accepté (client)",
    "prescrit": "Prescrit",
}
_LIBELLES_PROBABILITE: Final[dict[str, str]] = {
    "probable": "Probable",
    "possible": "Possible",
    "faible": "Faible",
}
_LIBELLES_VERDICT: Final[dict[str, str]] = {
    "probante": "Preuve probante",
    "insuffisante": "Preuve insuffisante",
    "sans_rapport": "Preuve sans rapport",
    "indisponible": "Analyse indisponible",
}
_ORDRE_STATUTS: Final[tuple[str, ...]] = (
    "ouvert",
    "en_traitement",
    "resolu",
    "accepte",
    "prescrit",
)


class ErreurRapportRisques(Exception):
    """Échec de construction du rapport de risques."""


def formater_montant_fcfa(valeur: Any) -> str:
    """« 1 500 000 FCFA » — pure, testable."""
    if valeur is None or valeur == "":
        return "non chiffré"
    montant = Decimal(str(valeur))
    return f"{montant:,.0f} FCFA".replace(",", " ")


def formater_date_fr(valeur: Any) -> str:
    """jj/mm/aaaa — accepte iso, date, datetime ; vide sinon."""
    if valeur is None or valeur == "":
        return ""
    if isinstance(valeur, datetime):
        return valeur.strftime("%d/%m/%Y")
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    try:
        return datetime.fromisoformat(str(valeur)).strftime("%d/%m/%Y")
    except ValueError:
        try:
            return date.fromisoformat(str(valeur)[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return str(valeur)


def _exposition(risque: dict[str, Any]) -> Decimal:
    total = Decimal("0")
    for cle in ("montant_estime", "penalites_estimees"):
        v = risque.get(cle)
        if v is not None and v != "":
            total += Decimal(str(v))
    return total


def _penalites_interets_chiffres(risque: dict[str, Any]) -> Decimal:
    """Intérêts + pénalité d'assiette du chiffrage indicatif (0 si absent)."""
    chiffrage = risque.get("chiffrage_penalites")
    if not chiffrage:
        return Decimal("0")
    return Decimal(str(chiffrage["interet_retard"])) + Decimal(
        str(chiffrage["penalite_assiette"])
    )


def construire_donnees_rapport(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Données consolidées du rapport — RLS tenant, lecture seule."""
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "SELECT id, denomination, ncc FROM contribuable "
                "WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
    if contrib is None:
        raise ErreurRapportRisques(
            f"contribuable {contribuable_id} introuvable"
        )

    risques = lister_risques(
        session, tenant_id, contribuable_id=contribuable_id
    )

    # Dernière preuve par risque résolu (verdict IA + décision + date).
    preuves_par_risque: dict[int, dict[str, Any]] = {}
    ids_resolus = [r["id"] for r in risques if r["statut"] == "resolu"]
    if ids_resolus:
        with contexte_tenant(session, tenant_id):
            rows = session.execute(
                text(
                    "SELECT DISTINCT ON (risque_id) risque_id, "
                    "nom_fichier, verdict_ia, decision, motif_forcage, "
                    "cree_le "
                    "FROM preuve_resolution_risque "
                    "WHERE risque_id = ANY(:ids) "
                    "ORDER BY risque_id, cree_le DESC, id DESC"
                ),
                {"ids": ids_resolus},
            ).mappings().all()
        for p in rows:
            preuves_par_risque[int(p["risque_id"])] = dict(p)

    exposition_ouverte = Decimal("0")
    exposition_traitee = Decimal("0")
    penalites_interets_ouverts = Decimal("0")
    penalites_interets_traites = Decimal("0")
    par_impot: dict[str, dict[str, Any]] = {}
    par_statut: dict[str, dict[str, Any]] = {}
    for r in risques:
        expo = _exposition(r)
        statut = str(r["statut"])
        pen_int = _penalites_interets_chiffres(r)
        if statut in STATUTS_NON_CLOS:
            exposition_ouverte += expo
            penalites_interets_ouverts += pen_int
        else:
            exposition_traitee += expo
            penalites_interets_traites += pen_int

        imp = par_impot.setdefault(
            str(r["impot"]),
            {"impot": str(r["impot"]), "nombre": 0,
             "exposition": Decimal("0"), "ouverts": 0},
        )
        imp["nombre"] += 1
        imp["exposition"] += expo
        if statut in STATUTS_NON_CLOS:
            imp["ouverts"] += 1

        st = par_statut.setdefault(
            statut,
            {
                "statut": statut,
                "libelle": _LIBELLES_STATUT.get(statut, statut),
                "nombre": 0,
                "exposition": Decimal("0"),
            },
        )
        st["nombre"] += 1
        st["exposition"] += expo

    top_risques = sorted(
        (r for r in risques if str(r["statut"]) in STATUTS_NON_CLOS),
        key=_exposition,
        reverse=True,
    )[:TOP_RISQUES_MAX]

    historique: list[dict[str, Any]] = []
    for r in risques:
        if r["statut"] != "resolu":
            continue
        preuve = preuves_par_risque.get(int(r["id"]))
        historique.append(
            {
                "risque": r,
                "date_resolution": formater_date_fr(
                    (preuve or {}).get("cree_le") or r.get("maj_le")
                ),
                "preuve_fichier": (preuve or {}).get("nom_fichier"),
                "verdict": _LIBELLES_VERDICT.get(
                    str((preuve or {}).get("verdict_ia") or ""), None
                ),
                "decision": (preuve or {}).get("decision"),
                "motif_forcage": (preuve or {}).get("motif_forcage"),
            }
        )

    score = score_risque_contribuable(session, tenant_id, contribuable_id)

    return {
        "contribuable": {
            "id": int(contrib["id"]),
            "denomination": str(contrib["denomination"]),
            "ncc": contrib.get("ncc"),
        },
        "edite_le": formater_date_fr(date.today()),
        "nombre_risques": len(risques),
        "exposition_ouverte": exposition_ouverte,
        "exposition_traitee": exposition_traitee,
        "exposition_totale": exposition_ouverte + exposition_traitee,
        # Chiffrage indicatif pénalités + intérêts de retard (déterministe,
        # backend/plateforme/penalites.py) — à valider par l'associé.
        "chiffrage_indicatif": {
            "penalites_interets_ouverts": penalites_interets_ouverts,
            "penalites_interets_traites": penalites_interets_traites,
            "penalites_interets_totaux": (
                penalites_interets_ouverts + penalites_interets_traites
            ),
            "exposition_ouverte_avec_penalites": (
                exposition_ouverte + penalites_interets_ouverts
            ),
            "exposition_totale_avec_penalites": (
                exposition_ouverte
                + exposition_traitee
                + penalites_interets_ouverts
                + penalites_interets_traites
            ),
        },
        "par_impot": sorted(
            par_impot.values(),
            key=lambda x: x["exposition"],
            reverse=True,
        ),
        "par_statut": [
            par_statut[s] for s in _ORDRE_STATUTS if s in par_statut
        ],
        "top_risques": top_risques,
        "historique_resolution": historique,
        "score": score,
        "recommandations": list(score.get("alertes") or []),
    }


def rendre_rapport_risques_pdf(donnees: dict[str, Any]) -> bytes:
    """PDF simple (reportlab canvas) — même style que rapport_pdf.py."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, hauteur = A4
    y = hauteur - 2 * cm

    def ligne(texte: str, *, gras: bool = False, delta: float = 14) -> None:
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = hauteur - 2 * cm
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 11 if gras else 10)
        c.drawString(2 * cm, y, texte[:110])
        y -= delta

    contrib = donnees["contribuable"]
    ligne("Synthèse des risques fiscaux", gras=True, delta=18)
    ligne(f"Contribuable : {contrib['denomination']}")
    ligne(f"NCC : {contrib.get('ncc') or '—'}")
    ligne(f"Édité le : {donnees['edite_le']} — tous exercices confondus")
    y -= 6

    ligne("Exposition consolidée", gras=True)
    ligne(
        "Exposition ouverte (risques non clos) : "
        + formater_montant_fcfa(donnees["exposition_ouverte"])
    )
    ligne(
        "Exposition traitée (résolus / acceptés / prescrits) : "
        + formater_montant_fcfa(donnees["exposition_traitee"])
    )
    ligne(
        "Exposition totale : "
        + formater_montant_fcfa(donnees["exposition_totale"])
    )
    chiffrage = donnees.get("chiffrage_indicatif") or {}
    if chiffrage:
        ligne(
            "Pénalités et intérêts de retard estimés (indicatif) : "
            + formater_montant_fcfa(chiffrage["penalites_interets_totaux"])
        )
        ligne(
            "Exposition totale pénalités incluses (indicatif) : "
            + formater_montant_fcfa(
                chiffrage["exposition_totale_avec_penalites"]
            )
        )
        ligne(
            "Chiffrage indicatif (intérêt 0,5 %/mois plafonné à 50 %, "
            "assiette 25 %) — à valider par l'associé.",
            delta=16,
        )
    score = donnees.get("score") or {}
    ligne(
        f"Score de risque : {score.get('score')} / 100 — "
        f"{score.get('libelle_niveau') or ''}"
    )
    y -= 6

    ligne("Répartition par impôt", gras=True)
    if not donnees["par_impot"]:
        ligne("Aucun risque enregistré.")
    for imp in donnees["par_impot"]:
        ligne(
            f"{imp['impot']} : {imp['nombre']} risque(s), "
            f"dont {imp['ouverts']} ouvert(s) — "
            + formater_montant_fcfa(imp["exposition"])
        )
    y -= 6

    ligne("Répartition par statut", gras=True)
    if not donnees["par_statut"]:
        ligne("Aucun risque enregistré.")
    for st in donnees["par_statut"]:
        ligne(
            f"{st['libelle']} : {st['nombre']} risque(s) — "
            + formater_montant_fcfa(st["exposition"])
        )
    y -= 6

    ligne(f"Top risques ouverts (max {TOP_RISQUES_MAX})", gras=True)
    if not donnees["top_risques"]:
        ligne("Aucun risque ouvert.")
    for r in donnees["top_risques"]:
        prob = _LIBELLES_PROBABILITE.get(r["probabilite"], r["probabilite"])
        ligne(
            f"[{r['impot']} {r['exercice_origine']}] {r['libelle']}"
        )
        ref = r.get("reference_legale")
        ligne(
            f"    {prob} — exposition "
            + formater_montant_fcfa(_exposition(r))
            + (f" — {ref}" if ref else ""),
            delta=16,
        )
        pen_int = _penalites_interets_chiffres(r)
        if pen_int > 0:
            total_avec = _exposition(r) + pen_int
            ligne(
                "    Pénalités + intérêts estimés (indicatif) : "
                + formater_montant_fcfa(pen_int)
                + " — total estimé "
                + formater_montant_fcfa(total_avec),
                delta=16,
            )
    y -= 6

    ligne("Historique de résolution (preuves)", gras=True)
    if not donnees["historique_resolution"]:
        ligne("Aucun risque résolu à ce jour.")
    for h in donnees["historique_resolution"]:
        r = h["risque"]
        ligne(
            f"[{r['impot']} {r['exercice_origine']}] {r['libelle']}"
        )
        detail = f"    Résolu le {h['date_resolution'] or '—'}"
        if h.get("preuve_fichier"):
            detail += f" — preuve « {h['preuve_fichier']} »"
        if h.get("verdict"):
            detail += f" — {h['verdict']}"
        if h.get("decision") == "forcee" and h.get("motif_forcage"):
            detail += f" (résolution forcée : {h['motif_forcage']})"
        ligne(detail, delta=16)
    y -= 6

    ligne("Recommandations", gras=True)
    if not donnees["recommandations"]:
        ligne("Aucune alerte — registre à jour.")
    for reco in donnees["recommandations"]:
        ligne(f"- {reco}")
    y -= 6
    ligne(
        "Montants estimés par le cabinet — verdicts de preuve IA "
        "consultatifs, la décision reste humaine.",
        delta=12,
    )

    c.save()
    return buf.getvalue()


def exporter_rapport_risques_pdf(
    session: Session, tenant_id: int, contribuable_id: int
) -> tuple[str, bytes]:
    """Retourne (nom_fichier, contenu PDF)."""
    donnees = construire_donnees_rapport(session, tenant_id, contribuable_id)
    slug = (
        re.sub(
            r"[^A-Za-z0-9]+", "_", donnees["contribuable"]["denomination"]
        ).strip("_")
        or "client"
    )
    nom = f"rapport_risques_{slug}_{date.today().isoformat()}.pdf"
    return nom, rendre_rapport_risques_pdf(donnees)
