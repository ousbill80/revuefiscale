"""Rendu markdown du rapport de mission (texte)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from backend.plateforme.missions import CODES_IMPOT, LIBELLES_ENGAGEMENT
from backend.restitution.passage import Passage
from backend.restitution.risques import ScoreRisque


def _fmt_montant(montant: Decimal) -> str:
    return f"{montant:,.2f}".replace(",", " ").replace(".", ",")


# Taxonomie pivot — exportée pour DOCX/PDF (même source que le markdown).
def section_perimetre(meta: Mapping[str, Any]) -> list[str]:
    """Section obligatoire « Périmètre déclaré » / « Non examiné »."""
    type_eng = str(meta.get("type_engagement") or "autre")
    libelle = (
        meta.get("type_engagement_libelle")
        or LIBELLES_ENGAGEMENT.get(type_eng)
        or type_eng
    )
    brut = meta.get("perimetre_impots")
    perimetre: list[str] | None = None
    if isinstance(brut, (list, tuple)) and len(brut) > 0:
        perimetre = [str(x).strip().upper() for x in brut if str(x).strip()]

    lignes: list[str] = [
        "## Périmètre déclaré",
        "",
        f"- **Type d'engagement** : {libelle} (`{type_eng}`)",
    ]
    if perimetre is None:
        lignes.append(
            "- **Impôts examinés** : tous (périmètre non restreint)"
        )
    else:
        lignes.append(
            "- **Impôts examinés** : " + ", ".join(f"`{c}`" for c in perimetre)
        )

    exclusions = meta.get("exclusions_declarees")
    if exclusions and str(exclusions).strip():
        lignes.append(f"- **Exclusions déclarées** : {str(exclusions).strip()}")

    objectifs = meta.get("objectifs")
    if isinstance(objectifs, (list, tuple)) and len(objectifs) > 0:
        lignes.append("- **Objectifs** :")
        for o in objectifs:
            lib = (
                str(o.get("libelle") or "").strip()
                if isinstance(o, dict)
                else str(o).strip()
            )
            if lib:
                lignes.append(f"  - {lib}")

    seuil = meta.get("seuil_signification")
    if seuil is not None and str(seuil).strip() != "":
        lignes.append(f"- **Seuil de signification** : {seuil} FCFA")

    lignes.extend(["", "## Non examiné", ""])
    fiscaux = meta.get("objectifs_fiscaux")
    exclus_fisc: list[tuple[str, str | None]] = []
    if isinstance(fiscaux, (list, tuple)) and len(fiscaux) > 0:
        for o in fiscaux:
            if not isinstance(o, dict):
                continue
            if o.get("dans_perimetre"):
                continue
            code = str(o.get("impot") or "").strip().upper()
            if not code:
                continue
            motif = o.get("motif_exclusion")
            exclus_fisc.append(
                (code, str(motif).strip() if motif else None)
            )
    if exclus_fisc:
        lignes.append(
            "Impôts hors périmètre déclaré (non examinés dans cette mission) :"
        )
        lignes.append("")
        for code, motif in exclus_fisc:
            if motif:
                lignes.append(f"- `{code}` — {motif}")
            else:
                lignes.append(f"- `{code}`")
    elif perimetre is None:
        lignes.append(
            "_Aucun — revue sur tous les impôts du référentiel (périmètre complet)._"
        )
    else:
        exclus = [c for c in CODES_IMPOT if c not in set(perimetre)]
        if exclus:
            lignes.append(
                "Impôts hors périmètre déclaré (non examinés dans cette mission) :"
            )
            lignes.append("")
            for code in exclus:
                lignes.append(f"- `{code}`")
        else:
            lignes.append(
                "_Tous les codes pivot sont inclus dans le périmètre déclaré._"
            )
    lignes.append("")
    return lignes


# Alias interne conservé
_section_perimetre = section_perimetre


def _fmt_date_jjmmaaaa(valeur: Any) -> str | None:
    """Date jj/mm/aaaa depuis un datetime/date ou une chaîne ISO."""
    if valeur is None:
        return None
    if hasattr(valeur, "strftime"):
        return valeur.strftime("%d/%m/%Y")
    brut = str(valeur).strip()
    if not brut:
        return None
    # Chaîne ISO « aaaa-mm-jj[Thh:mm:ss] » → jj/mm/aaaa.
    date_part = brut.split("T")[0].split(" ")[0]
    morceaux = date_part.split("-")
    if len(morceaux) == 3 and all(m.isdigit() for m in morceaux):
        return f"{morceaux[2]}/{morceaux[1]}/{morceaux[0]}"
    return brut


def section_fiabilite_source(
    controles_fec: Mapping[str, Any] | None,
) -> list[str]:
    """Section « Fiabilité de la source » — contrôles de vraisemblance FEC.

    Partagée DOCX/PDF (même source que le périmètre). Aucun recalcul :
    restitue le dernier jeu de contrôles persisté à l'import.
    """
    lignes: list[str] = ["## Fiabilité de la source", ""]
    controles = (
        controles_fec.get("controles") if isinstance(controles_fec, Mapping) else None
    )
    if not controles:
        lignes.append(
            "_Aucun contrôle de vraisemblance FEC enregistré pour cette "
            "mission (source non FEC ou non importée)._"
        )
        lignes.append("")
        return lignes

    exercice = controles_fec.get("exercice")
    date_txt = _fmt_date_jjmmaaaa(controles_fec.get("cree_le"))
    entete = "Contrôles de vraisemblance de la source FEC"
    if exercice is not None:
        entete += f" — exercice {exercice}"
    if date_txt:
        entete += f", importée le {date_txt}"
    lignes.append(entete + " (informationnels, jamais bloquants) :")
    lignes.append("")
    for c in controles:
        if not isinstance(c, Mapping):
            continue
        statut = str(c.get("statut") or "ok")
        badge = "ALERTE" if statut == "alerte" else "OK"
        libelle = str(c.get("libelle") or c.get("code") or "—")
        compteur = int(c.get("compteur") or 0)
        if compteur > 0:
            occ = f" — {compteur} occurrence{'s' if compteur > 1 else ''}"
        else:
            occ = ""
        lignes.append(f"- [{badge}] {libelle}{occ}")
    lignes.append("")
    return lignes


_LIBELLES_CLASSEMENT = {
    "apparition": "apparition",
    "disparition": "disparition",
    "variation_forte": "variation forte",
    "stable": "stable",
}

_MAX_LIGNES_REVUE = 20


def section_revue_analytique(
    revue: Mapping[str, Any] | None,
) -> list[str]:
    """Section « Revue analytique N / N-1 » — partagée DOCX/PDF.

    Reprend le payload de ``revue_analytique_mission`` : lignes principales
    (max 20, déjà triées par variation absolue décroissante) et totaux par
    classe SYSCOHADA. Mention sobre si aucun exercice antérieur comparable.
    """
    disponible = bool(isinstance(revue, Mapping) and revue.get("disponible"))
    exercice_n = revue.get("exercice_n") if isinstance(revue, Mapping) else None
    exercice_n1 = revue.get("exercice_n1") if isinstance(revue, Mapping) else None
    titre = "## Revue analytique"
    if exercice_n is not None and exercice_n1 is not None:
        titre += f" {exercice_n} / {exercice_n1}"
    else:
        titre += " N / N-1"
    lignes: list[str] = [titre, ""]
    if not disponible:
        lignes.append("_Aucun exercice antérieur comparable._")
        lignes.append("")
        return lignes

    def _mt(v: Any) -> str:
        if v is None:
            return "—"
        return _fmt_montant(Decimal(str(v)))

    contenu = [x for x in (revue.get("lignes") or []) if isinstance(x, Mapping)]
    lignes.append(
        f"Lignes principales ({min(len(contenu), _MAX_LIGNES_REVUE)} "
        f"sur {len(contenu)}, triées par variation absolue) :"
    )
    lignes.append("")
    for ligne in contenu[:_MAX_LIGNES_REVUE]:
        pct = ligne.get("variation_pct")
        pct_txt = (
            f"{str(pct).replace('.', ',')} %" if pct is not None else "—"
        )
        classement = _LIBELLES_CLASSEMENT.get(
            str(ligne.get("classement") or ""), str(ligne.get("classement") or "—")
        )
        lignes.append(
            f"- {ligne.get('compte')} · {ligne.get('libelle') or '—'} : "
            f"N {_mt(ligne.get('solde_n'))} FCFA / "
            f"N-1 {_mt(ligne.get('solde_n1'))} FCFA / "
            f"variation {_mt(ligne.get('variation'))} FCFA ({pct_txt}) — "
            f"{classement}"
        )
    lignes.append("")
    totaux = [
        t for t in (revue.get("totaux_par_classe") or []) if isinstance(t, Mapping)
    ]
    if totaux:
        lignes.append("Totaux par classe SYSCOHADA :")
        lignes.append("")
        for t in totaux:
            lignes.append(
                f"- Classe {t.get('classe')} : N {_mt(t.get('total_n'))} FCFA / "
                f"N-1 {_mt(t.get('total_n1'))} FCFA / "
                f"variation {_mt(t.get('variation'))} FCFA"
            )
        lignes.append("")
    return lignes


def lignes_comptes_source(
    conclusion: Mapping[str, Any],
) -> list[str]:
    """Puces « Comptes à l'origine » d'une conclusion (vide si aucun).

    Format : compte · libellé · solde FCFA · sens — piste d'audit brute,
    jamais un jugement fiscal.
    """
    comptes = conclusion.get("comptes_source")
    if not isinstance(comptes, (list, tuple)) or not comptes:
        return []
    out: list[str] = []
    for item in comptes:
        if not isinstance(item, Mapping):
            continue
        solde = item.get("solde")
        try:
            solde_txt = (
                _fmt_montant(Decimal(str(solde))) if solde not in (None, "") else "—"
            )
        except ArithmeticError:
            solde_txt = str(solde)
        out.append(
            f"- {item.get('compte')} · {item.get('libelle') or '—'} · "
            f"{solde_txt} FCFA · {item.get('sens') or '—'}"
        )
    return out


def rendre_rapport_markdown(
    *,
    meta: Mapping[str, Any],
    passage: Passage,
    conclusions: Sequence[Mapping[str, object]],
    score: ScoreRisque,
    extrait_audit: Sequence[Mapping[str, Any]],
) -> str:
    """Produit un rapport markdown a partir des donnees deja calculees.

    Aucun montant fiscal n est recalcule ici.
    """
    denomination = meta.get("contribuable_denomination") or "—"
    exercice = meta.get("exercice")
    mission_id = meta.get("mission_id")
    version_id = meta.get("version_referentiel_id")
    ncc = meta.get("contribuable_ncc") or "—"
    type_eng = str(meta.get("type_engagement") or "autre")
    libelle_eng = (
        meta.get("type_engagement_libelle")
        or LIBELLES_ENGAGEMENT.get(type_eng)
        or type_eng
    )

    lignes: list[str] = [
        "# Rapport de mission — revue fiscale",
        "",
        "## Identification",
        "",
        f"- **Mission** : `{mission_id}`",
        f"- **Contribuable** : {denomination}",
        f"- **NCC** : {ncc}",
        f"- **Exercice** : {exercice}",
        f"- **Type d'engagement** : {libelle_eng} (`{type_eng}`)",
        f"- **Version referentiel epinglee** : `{version_id}`",
        "",
    ]
    lignes.extend(_section_perimetre(meta))
    lignes.extend(
        [
            "## Passage comptable / fiscal",
            "",
            "| Regle | Sens | Montant (FCFA) | Risque |",
            "|---|---|---:|---|",
        ]
    )

    for ligne in passage.lignes:
        lignes.append(
            f"| `{ligne.regle_id}` | {ligne.sens} | "
            f"{_fmt_montant(ligne.montant)} | {ligne.niveau_risque} |"
        )

    if not passage.lignes:
        lignes.append("| — | — | — | — |")

    lignes.extend(
        [
            "",
            f"- **Total reintegrations** : {_fmt_montant(passage.total_reintegration)} FCFA",
            f"- **Total deductions** : {_fmt_montant(passage.total_deduction)} FCFA",
            f"- **Solde net (reint. − ded.)** : {_fmt_montant(passage.solde_net)} FCFA",
            "",
            "## Conclusions",
            "",
        ]
    )

    if not conclusions:
        lignes.append("_Aucune conclusion declenchee sur la derniere execution._")
        lignes.append("")
    else:
        for c in conclusions:
            mt = c.get("montant")
            mt_txt = _fmt_montant(Decimal(str(mt))) if mt is not None else "—"
            statut = c.get("statut") or "anomalie"
            piece = c.get("piece_mission_id")
            piece_txt = f" — pièce `{piece}`" if piece is not None else ""
            lignes.append(
                f"- `{c.get('regle_id')}` — statut `{statut}` — "
                f"sens `{c.get('sens') or '—'}` — "
                f"montant {mt_txt} — risque `{c.get('niveau_risque')}`"
                f"{piece_txt}"
            )
            if c.get("commentaire"):
                lignes.append(f"  - _{c['commentaire']}_")
        lignes.append("")

    lignes.extend(
        [
            "## Score de risque (heuristique)",
            "",
            f"> {score.avertissement}",
            "",
            f"- **Score** : {score.score}",
            f"- **Comptages** : {score.comptages or '{}'}",
            "",
        ]
    )

    ac_total = int(meta.get("a_confirmer_total") or 0)
    ac_regles = meta.get("a_confirmer_regles") or []
    lignes.extend(
        [
            "## Mentions `a_confirmer` (règles touchées)",
            "",
            f"- **Total** : {ac_total}",
            "",
            "> Paramètres encore marqués a_confirmer — non certifiés. "
            "Ne constituent pas du droit positif. Purge = circuit éditorial humain.",
            "",
        ]
    )
    if ac_regles:
        for item in ac_regles:
            rid = item.get("regle_id") if isinstance(item, Mapping) else None
            ment = item.get("mentions") if isinstance(item, Mapping) else None
            lignes.append(f"- `{rid}` ({item.get('nb') if isinstance(item, Mapping) else '—'})")
            if isinstance(ment, Sequence):
                for m in ment:
                    lignes.append(f"  - {m}")
        lignes.append("")
    else:
        lignes.append("_Aucune mention a_confirmer sur les règles touchées._")
        lignes.append("")

    lignes.extend(
        [
            "## Extrait du journal d audit",
            "",
        ]
    )

    if not extrait_audit:
        lignes.append("_Aucune entree d audit pour cette mission._")
    else:
        for e in extrait_audit:
            lignes.append(
                f"- `{e.get('horodatage')}` — **{e.get('acteur')}** — "
                f"`{e.get('action')}`"
            )

    lignes.append("")
    return "\n".join(lignes)
