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
from backend.restitution.rapport import section_perimetre
from backend.restitution.risques import ScoreRisque


def _fmt(montant: Decimal) -> str:
    return f"{montant:,.2f}".replace(",", " ").replace(".", ",")


def rendre_rapport_pdf(
    *,
    meta: Mapping[str, Any],
    passage: Passage,
    conclusions: Sequence[Mapping[str, object]],
    score: ScoreRisque,
    extrait_audit: Sequence[Mapping[str, Any]],
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
    for brut in section_perimetre(meta):
        texte = brut.strip()
        if not texte:
            continue
        if texte.startswith("## "):
            ligne(texte[3:].strip(), gras=True)
        else:
            ligne(texte.replace("**", "").replace("`", "").replace("_", ""))
    y -= 6
    ligne("Passage comptable / fiscal", gras=True)
    for p in passage.lignes:
        ligne(
            f"{p.regle_id} | {p.sens} | {_fmt(p.montant)} | {p.niveau_risque}"
        )
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
    _ = conclusions  # deja resumes dans le passage
    c.save()
    return buf.getvalue()
