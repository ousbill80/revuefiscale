"""Rendu markdown du rapport de mission (texte)."""
from __future__ import annotations

import contextlib
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
        occ = (
            f" — {compteur} occurrence{'s' if compteur > 1 else ''}"
            if compteur > 0
            else ""
        )
        lignes.append(f"- [{badge}] {libelle}{occ}")
    lignes.append("")
    return lignes


_LIBELLES_GRAVITE = {
    "haute": "HAUTE",
    "moyenne": "MOYENNE",
    "faible": "FAIBLE",
}


def section_note_synthese(note: Mapping[str, Any] | None) -> list[str]:
    """Section « Note de synthèse » — dernière version *disponible* de la note.

    Partagée DOCX/PDF, purement déclarative : la note est lue en base
    (jamais générée ici — aucun appel LLM à l'export). Retourne une liste
    VIDE si aucune note disponible : pas de section vide dans le rapport.
    """
    if not isinstance(note, Mapping):
        return []
    contenu = note.get("contenu")
    if not isinstance(contenu, Mapping):
        return []

    lignes: list[str] = ["## Note de synthèse", ""]
    entete = "Executive summary de mission"
    version = note.get("version")
    if version is not None:
        entete += f" — version {version}"
    date_txt = _fmt_date_jjmmaaaa(note.get("cree_le"))
    if date_txt:
        entete += f" du {date_txt}"
    lignes.append(
        entete + " (assistance IA, consultative — l'humain signataire relit et signe)."
    )
    lignes.append("")

    contexte = str(contenu.get("contexte") or "").strip()
    if contexte:
        lignes.append(f"**Contexte** : {contexte}")
        lignes.append("")

    constats = [
        c for c in (contenu.get("constats") or []) if isinstance(c, Mapping)
    ]
    if constats:
        lignes.append(f"Principaux constats ({len(constats)}) :")
        lignes.append("")
        for c in constats:
            gravite = _LIBELLES_GRAVITE.get(
                str(c.get("gravite") or "").strip().lower(), "MOYENNE"
            )
            resume = str(c.get("resume") or "").strip()
            montant = c.get("montant")
            montant_txt = (
                f" (montant : {str(montant).strip()} FCFA)"
                if montant is not None and str(montant).strip()
                else ""
            )
            lignes.append(
                f"- [{gravite}] `{c.get('regle_id')}` — {resume}{montant_txt}"
            )
        lignes.append("")

    exposition = str(contenu.get("exposition") or "").strip()
    if exposition:
        lignes.append(f"**Exposition estimée** : {exposition}")
        lignes.append("")

    points = [
        str(p).strip()
        for p in (contenu.get("points_attention") or [])
        if str(p).strip()
    ]
    if points:
        lignes.append("Points d'attention :")
        lignes.append("")
        for p in points:
            lignes.append(f"- {p}")
        lignes.append("")

    recos = [
        str(r).strip()
        for r in (contenu.get("recommandations") or [])
        if str(r).strip()
    ]
    if recos:
        lignes.append("Recommandations prioritaires :")
        lignes.append("")
        for r in recos:
            lignes.append(f"- {r}")
        lignes.append("")

    return lignes


def section_commentaire_analytique(
    commentaire: Mapping[str, Any] | None,
) -> list[str]:
    """Section « Commentaire de revue analytique » — dernière version *disponible*.

    Partagée DOCX/PDF, purement déclarative : le commentaire est lu en base
    (jamais généré ici — aucun appel LLM à l'export). Retourne une liste
    VIDE si aucun commentaire disponible : pas de section vide.
    """
    if not isinstance(commentaire, Mapping):
        return []
    contenu = commentaire.get("contenu")
    if not isinstance(contenu, Mapping):
        return []

    lignes: list[str] = ["## Commentaire de revue analytique", ""]
    entete = "Lecture commentée des variations N/N-1"
    version = commentaire.get("version")
    if version is not None:
        entete += f" — version {version}"
    date_txt = _fmt_date_jjmmaaaa(commentaire.get("cree_le"))
    if date_txt:
        entete += f" du {date_txt}"
    lignes.append(
        entete + " (assistance IA, consultative — l'humain valide)."
    )
    lignes.append("")

    resume = str(contenu.get("resume") or "").strip()
    if resume:
        lignes.append(f"**Résumé** : {resume}")
        lignes.append("")

    explications = [
        e for e in (contenu.get("explications") or []) if isinstance(e, Mapping)
    ]
    if explications:
        lignes.append(f"Explications par poste ({len(explications)}) :")
        lignes.append("")
        for e in explications:
            gravite = _LIBELLES_GRAVITE.get(
                str(e.get("gravite") or "").strip().lower(), "MOYENNE"
            )
            poste = str(e.get("poste") or "—").strip() or "—"
            hypothese = str(e.get("hypothese_explicative") or "").strip()
            lignes.append(f"- [{gravite}] `{poste}` — {hypothese}")
            question = str(e.get("question_a_poser_au_client") or "").strip()
            if question:
                lignes.append(f"  - Question au client : {question}")
        lignes.append("")

    alertes = [
        str(a).strip()
        for a in (contenu.get("alertes_coherence") or [])
        if str(a).strip()
    ]
    if alertes:
        lignes.append("Alertes de cohérence :")
        lignes.append("")
        for a in alertes:
            lignes.append(f"- {a}")
        lignes.append("")

    return lignes


def _fmt_fcfa_entier(valeur: Any) -> str:
    """« 1 500 000 FCFA » depuis un montant str/Decimal (JSON-safe)."""
    try:
        montant = Decimal(str(valeur))
    except ArithmeticError:
        return f"{valeur} FCFA"
    return f"{montant:,.0f} FCFA".replace(",", " ")


def section_exposition_penalites(
    risques: Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    """Section « Exposition pénalités et intérêts (indicatif) » — DOCX/PDF.

    Reprend le chiffrage indicatif déjà sérialisé sur chaque risque
    (``chiffrage_penalites`` de backend/plateforme/risques.py — barème de
    backend/plateforme/penalites.py, aucun recalcul ici). Seuls les risques
    déjà filtrés en amont (ouverts + chiffrés) sont attendus : liste vide
    ou None → aucune section.
    """
    lignes_risques: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for r in risques or []:
        if not isinstance(r, Mapping):
            continue
        chiffrage = r.get("chiffrage_penalites")
        if isinstance(chiffrage, Mapping):
            lignes_risques.append((r, chiffrage))
    if not lignes_risques:
        return []

    lignes: list[str] = ["## Exposition pénalités et intérêts (indicatif)", ""]
    lignes.append(
        f"Risques ouverts chiffrés du contribuable ({len(lignes_risques)}) — "
        "intérêts et pénalités estimés depuis la fin de l'exercice d'origine :"
    )
    lignes.append("")
    total_general = Decimal("0")
    for r, chiffrage in lignes_risques:
        titre = str(r.get("libelle") or "—").strip() or "—"
        impot = str(r.get("impot") or "").strip()
        exercice = r.get("exercice_origine")
        prefixe = f"[{impot} {exercice}] " if impot and exercice else ""
        mois = int(chiffrage.get("mois_retard") or 0)
        with contextlib.suppress(ArithmeticError):
            total_general += Decimal(str(chiffrage.get("total_estime") or "0"))
        lignes.append(
            f"- {prefixe}{titre} — droit simple "
            f"{_fmt_fcfa_entier(chiffrage.get('droit_simple'))} "
            f"+ intérêts {_fmt_fcfa_entier(chiffrage.get('interet_retard'))} "
            f"+ pénalité {_fmt_fcfa_entier(chiffrage.get('penalite_assiette'))} "
            f"= total {_fmt_fcfa_entier(chiffrage.get('total_estime'))} "
            f"({mois} mois)"
        )
    lignes.append("")
    lignes.append(
        f"**Total général estimé** : {_fmt_fcfa_entier(total_general)}"
    )
    lignes.append("")
    lignes.append("Chiffrage indicatif, à valider par l'associé.")
    lignes.append("")
    return lignes


def section_provision_risques(
    provision: Mapping[str, Any] | None,
) -> list[str]:
    """Section « Provision pour risques fiscaux proposée » — DOCX/PDF.

    Reprend le payload de ``calculer_provision`` (backend/plateforme/
    provision_risques.py — aucun recalcul ici) : lignes provisionnables,
    total, passifs éventuels, écriture SYSCOHADA proposée et hypothèses.
    Provision absente ou totalement vide (total nul ET aucun passif
    éventuel) → aucune section.
    """
    if not isinstance(provision, Mapping):
        return []
    total = Decimal("0")
    with contextlib.suppress(ArithmeticError):
        total = Decimal(str(provision.get("total_provision") or "0"))
    passifs = [
        p for p in (provision.get("passifs_eventuels") or []) if isinstance(p, Mapping)
    ]
    if total == 0 and not passifs:
        return []

    lignes: list[str] = ["## Provision pour risques fiscaux proposée", ""]

    contenu = [
        x for x in (provision.get("lignes") or []) if isinstance(x, Mapping)
    ]
    if contenu:
        lignes.append(f"Risques provisionnables ({len(contenu)}) :")
        lignes.append("")
        for ligne in contenu:
            titre = str(ligne.get("titre") or "—").strip() or "—"
            impot = str(ligne.get("impot") or "").strip()
            exercice = ligne.get("exercice")
            probabilite = str(ligne.get("probabilite") or "probable").strip()
            lignes.append(
                f"- {titre} ({impot} {exercice}, {probabilite}) — provision "
                f"{_fmt_fcfa_entier(ligne.get('montant_provisionnable'))}"
            )
        lignes.append("")
        lignes.append(
            f"**Total de la provision proposée** : {_fmt_fcfa_entier(total)}"
        )
        lignes.append("")

    if passifs:
        lignes.append(f"Passifs éventuels ({len(passifs)}) :")
        lignes.append("")
        for p in passifs:
            titre = str(p.get("titre") or "—").strip() or "—"
            lignes.append(
                f"- {titre} — montant estimé "
                f"{_fmt_fcfa_entier(p.get('montant_estime'))} "
                "(mention en annexe recommandée)"
            )
        lignes.append("")

    ecriture = provision.get("ecriture_proposee")
    if isinstance(ecriture, Mapping) and total > 0:
        lignes.append("Écriture proposée :")
        lignes.append("")
        morceaux: list[str] = []
        montant_txt = _fmt_fcfa_entier(total)
        for le in ecriture.get("lignes") or []:
            if not isinstance(le, Mapping):
                continue
            sens = "Débit" if str(le.get("sens") or "") == "debit" else "Crédit"
            morceaux.append(
                f"{sens} {le.get('compte')} {le.get('intitule') or ''}".strip()
            )
            montant_txt = _fmt_fcfa_entier(le.get("montant"))
        if morceaux:
            lignes.append(f"- {' / '.join(morceaux)} — {montant_txt}")
        libelle = str(ecriture.get("libelle") or "").strip()
        if libelle:
            lignes.append(f"- Libellé : {libelle}")
        lignes.append("")

    hypotheses = [
        str(h).strip()
        for h in (provision.get("hypotheses") or [])
        if str(h).strip()
    ]
    if hypotheses:
        lignes.append("Hypothèses et mentions :")
        lignes.append("")
        for h in hypotheses:
            lignes.append(f"- {h}")
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
