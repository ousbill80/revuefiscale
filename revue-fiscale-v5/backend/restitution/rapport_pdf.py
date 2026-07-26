"""Export PDF du rapport de mission."""
from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from backend.restitution.passage import Passage
from backend.restitution.rapport import (
    lignes_comptes_source,
    section_fiabilite_source,
    section_note_synthese,
    section_perimetre,
    section_revue_analytique,
)
from backend.restitution.risques import ScoreRisque


def _fmt(montant: Decimal) -> str:
    return f"{montant:,.2f}".replace(",", " ").replace(".", ",")


def _winansi(texte: str) -> str:
    """Helvetica encode en WinAnsi — remplace les glyphes hors Latin-1."""
    return texte.encode("latin-1", "replace").decode("latin-1")


def rendre_rapport_pdf(
    *,
    meta: Mapping[str, Any],
    passage: Passage,
    conclusions: Sequence[Mapping[str, object]],
    score: ScoreRisque,
    extrait_audit: Sequence[Mapping[str, Any]],
    controles_fec: Mapping[str, Any] | None = None,
    revue_analytique: Mapping[str, Any] | None = None,
    note_synthese: Mapping[str, Any] | None = None,
) -> bytes:
    """Produit un PDF simple a partir des donnees deja calculees."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    largeur, hauteur = A4
    y = hauteur - 2 * cm

    def ligne(texte: str, *, gras: bool = False, delta: float = 14) -> None:
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = hauteur - 2 * cm
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 11 if gras else 10)
        c.drawString(2 * cm, y, texte[:110])
        y -= delta

    ligne("Rapport de mission — revue fiscale", gras=True, delta=18)
    ligne(f"Mission : {meta.get('mission_id')}")
    ligne(f"Contribuable : {meta.get('contribuable_denomination') or '—'}")
    ligne(f"NCC : {meta.get('contribuable_ncc') or '—'}")
    ligne(f"Exercice : {meta.get('exercice')}")
    ligne(f"Version referentiel : {meta.get('version_referentiel_id')}")
    y -= 6

    def bloc_markdown(lignes_md: Sequence[str]) -> None:
        for brut in lignes_md:
            texte = brut.strip()
            if not texte:
                continue
            if texte.startswith("## "):
                ligne(_winansi(texte[3:].strip()), gras=True)
            else:
                ligne(
                    _winansi(
                        texte.replace("**", "").replace("`", "").replace("_", "")
                    )
                )

    def bloc_markdown_multiligne(lignes_md: Sequence[str], *, max_car: int = 105) -> None:
        """Comme ``bloc_markdown`` mais replie les lignes longues (pas de troncature)."""
        for brut in lignes_md:
            texte = brut.strip()
            if not texte:
                continue
            if texte.startswith("## "):
                ligne(_winansi(texte[3:].strip()), gras=True)
                continue
            plat = texte.replace("**", "").replace("`", "").replace("_", "")
            mots = plat.split(" ")
            courante = ""
            for mot in mots:
                if courante and len(courante) + 1 + len(mot) > max_car:
                    ligne(_winansi(courante))
                    courante = "  " + mot
                else:
                    courante = f"{courante} {mot}" if courante else mot
            if courante:
                ligne(_winansi(courante))

    # Note de synthèse IA en tête de rapport (dernière version disponible,
    # lue en base — jamais générée à l'export). Vide → aucune section.
    lignes_note = section_note_synthese(note_synthese)
    if lignes_note:
        bloc_markdown_multiligne(lignes_note)
        y -= 6
    bloc_markdown(section_perimetre(meta))
    y -= 6
    # En tête de synthèse (même ordre que l'écran) : fiabilité puis revue N/N-1.
    bloc_markdown(section_fiabilite_source(controles_fec))
    y -= 6
    bloc_markdown(section_revue_analytique(revue_analytique))
    y -= 6
    ligne("Passage comptable / fiscal", gras=True)
    for p in passage.lignes:
        ligne(
            f"{p.regle_id} | {p.sens} | {_fmt(p.montant)} | {p.niveau_risque}"
        )
    # Comptes à l'origine de chaque conclusion/anomalie (piste d'audit).
    for concl in conclusions:
        puces = lignes_comptes_source(concl)
        if not puces:
            continue
        ligne(
            _winansi(
                f"Comptes à l'origine — {concl.get('regle_id')} "
                f"(statut {concl.get('statut') or 'anomalie'}) :"
            )
        )
        for puce in puces:
            ligne(_winansi("  " + puce[2:]))
    ligne(
        f"Solde net : {_fmt(passage.solde_net)} — "
        f"score risque (heuristique) : {score.score}"
    )
    y -= 6
    ligne("Journal d audit (extrait)", gras=True)
    for entree in extrait_audit[:15]:
        ligne(
            f"{entree.get('horodatage')} | {entree.get('acteur')} | {entree.get('action')}"
        )
    y -= 6
    ligne("Montants issus du referentiel YAML (a confirmer possibles).", delta=12)
    c.save()
    return buf.getvalue()
