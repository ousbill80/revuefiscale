"""Genere les 20 fiches metier Lot1 (5 types + 15 doc5) et aligne le harnais a 57.

Appelé par make seed avant le chargement en base.
Les paramètres restent marques a_confirmer — pas du droit positif certifié.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[2] / "referentiel"
EMP = RACINE / "emplacements"
SO = "sans objet"


def _dump(regle: dict, chemin: Path) -> None:
    chemin.write_text(
        yaml.safe_dump(regle, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def _base(**kw: object) -> dict:
    r: dict = {
        "reference_source": "CGI 2026 — doc client 2/5 format pivot (propositions metier)",
        "date_effet": "2026-01-01",
        "effets_croises": [],
    }
    r.update(kw)
    return r


def _regles() -> list[dict]:
    out: list[dict] = []
    out.append(_base(
        identifiant="BIC-PROV-18E1-RISQUES", impot="BIC",
        reference_legale="CGI 2026, art. 18 E 1° ; relevé des provisions art. 36",
        profils_applicables=["Entreprises au regime reel"],
        comptes_declencheurs=["691"], nature="temporaire",
        condition_declenchement="solde(691) > 0 et (reponse(q_perte_precisee) = faux ou reponse(q_releve) = faux)",
        conditions_fond="Perte precisee et probable ? Au releve art. 36 ?",
        formule_plafonnement=SO,
        questions_generees=[
            {"id": "q_perte_precisee", "texte": "Perte/charge nettement precisee et probable ?", "type": "booleen"},
            {"id": "q_releve", "texte": "Figure au releve des provisions (art. 36) ?", "type": "booleen"},
        ],
        resultat="solde(691)", niveau_risque="moyen",
        a_confirmer=["date d effet", "perimetre exclusions 18 E 1°"],
        cas_test={"soldes": {"691": "12000000"}, "agregats": {}, "reponses": {"q_perte_precisee": False, "q_releve": True}, "declenche_attendu": True, "montant_attendu": "12000000"},
    ))
    out.append(_base(
        identifiant="BIC-CHG-18A6-SOUSCAP", impot="BIC",
        reference_legale="CGI 2026, art. 18 A 6°",
        profils_applicables=["Societes au reel — parties liees"],
        comptes_declencheurs=["671", "674"], nature="permanente",
        condition_declenchement="solde(671) > 0 ou solde(674) > 0",
        conditions_fond="Limites cumulatives art. 18 A 6° — partiellement encodees.",
        formule_plafonnement="0.3 * agregat(RESULTAT_AVANT_IMPOT)",
        questions_generees=[
            {"id": "q_capital_libere", "texte": "Capital social libere ?", "type": "montant"},
            {"id": "q_taux_applique", "texte": "Taux d interet applique ?", "type": "montant"},
        ],
        resultat="max(0 ; solde(671) + solde(674) - (0.3 * agregat(RESULTAT_AVANT_IMPOT)))",
        niveau_risque="eleve",
        a_confirmer=["date d effet", "assiette 30 % — RESULTAT_AVANT_IMPOT a figer", "limites (a)(c)(d)(e)", "taux BCEAO + 2"],
        cas_test={"soldes": {"671": "80000000", "674": "20000000"}, "agregats": {"RESULTAT_AVANT_IMPOT": "200000000"}, "reponses": {}, "declenche_attendu": True, "montant_attendu": "40000000"},
    ))
    out.append(_base(
        identifiant="BIC-AMORT-18B-INFO", impot="BIC",
        reference_legale="CGI 2026, art. 18 B 1°",
        profils_applicables=["Entreprises au reel — materiel informatique"],
        comptes_declencheurs=["681"], nature="temporaire",
        condition_declenchement="solde(681) > 0 et reponse(q_duree_ok) = faux",
        conditions_fond="Duree d amortissement informatique entre 2 et 5 ans.",
        formule_plafonnement=SO,
        questions_generees=[
            {"id": "q_duree_comptable", "texte": "Duree comptable (annees) ?", "type": "montant"},
            {"id": "q_duree_ok", "texte": "Duree comprise entre 2 et 5 ans ?", "type": "booleen"},
        ],
        resultat="solde(681)", niveau_risque="moyen",
        a_confirmer=["date d effet", "fraction recalculee vs dotation entiere"],
        cas_test={"soldes": {"681": "5000000"}, "agregats": {}, "reponses": {"q_duree_ok": False, "q_duree_comptable": "1"}, "declenche_attendu": True, "montant_attendu": "5000000"},
    ))
    out.append(_base(
        identifiant="BIC-CHG-18A4-ADMIN", impot="BIC",
        reference_legale="CGI 2026, art. 18 A 4°",
        profils_applicables=["Societes anonymes"],
        comptes_declencheurs=["6581"], nature="permanente",
        condition_declenchement="solde(6581) > 0",
        conditions_fond="Indemnites de fonction administrateurs SA.",
        formule_plafonnement="3000000 * reponse(q_nb_admin)",
        questions_generees=[{"id": "q_nb_admin", "texte": "Nombre d administrateurs beneficiaires ?", "type": "montant"}],
        resultat="max(0 ; solde(6581) - (3000000 * reponse(q_nb_admin)))",
        niveau_risque="moyen",
        a_confirmer=["date d effet", "plafond 3 000 000 FCFA / beneficiaire / an"],
        cas_test={"soldes": {"6581": "10000000"}, "agregats": {}, "reponses": {"q_nb_admin": "2"}, "declenche_attendu": True, "montant_attendu": "4000000"},
    ))
    out.append(_base(
        identifiant="OBL-108-HONORAIRES", impot="OBL",
        reference_legale="CGI 2026, art. 108 ; note 002/MFB/DGI-DLCD",
        profils_applicables=["Toutes entreprises"],
        comptes_declencheurs=["622", "628"], nature="sans_objet",
        condition_declenchement="reponse(q_seuil_depasse) = vrai et reponse(q_declaration) = faux",
        conditions_fond="Declaration des sommes versees ; seuils a confirmer.",
        formule_plafonnement=SO,
        questions_generees=[
            {"id": "q_seuil_depasse", "texte": "Seuil de declaration depasse ?", "type": "booleen"},
            {"id": "q_declaration", "texte": "Declaration souscrite ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Montant non declare ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        effets_croises=[{"cible": "TVA-DED-PRORATA", "type": "remet_en_cause", "commentaire": "Perte possible TVA — A CONFIRMER"}],
        a_confirmer=["date d effet", "seuils 50 000 / 10 000", "comptes 622/628"],
        cas_test={"soldes": {"622": "1", "628": "0"}, "agregats": {}, "reponses": {"q_seuil_depasse": True, "q_declaration": False, "q_montant": "7500000"}, "declenche_attendu": True, "montant_attendu": "7500000"},
    ))

    doc5 = [
        ("BIC-CHG-18A1-SALAIRES", "CGI 2026, art. 18 A 1°", ["661", "663", "664"],
         "(solde(661) > 0 ou solde(663) > 0 ou solde(664) > 0) et reponse(q_travail_effectif) = faux",
         "reponse(q_montant_excessif)", "moyen", SO,
         [{"id": "q_travail_effectif", "texte": "Travail effectif ?", "type": "booleen"},
          {"id": "q_montant_excessif", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"661": "50000000", "663": "0", "664": "0"}, "reponses": {"q_travail_effectif": False, "q_montant_excessif": "50000000"}}),
        ("BIC-CHG-18A2-LOYERS", "CGI 2026, art. 18 A 2°", ["622", "623"],
         "(solde(622) > 0 ou solde(623) > 0) et reponse(q_loyer_excessif) = vrai",
         "reponse(q_fraction)", "moyen", SO,
         [{"id": "q_loyer_excessif", "texte": "Loyer excessif ?", "type": "booleen"},
          {"id": "q_fraction", "texte": "Fraction a reintegrer ?", "type": "montant"}],
         {"soldes": {"622": "30000000", "623": "0"}, "reponses": {"q_loyer_excessif": True, "q_fraction": "5000000"}}),
        ("BIC-AMORT-18B-GENERAL", "CGI 2026, art. 18 B ; relevé art. 35", ["681"],
         "solde(681) > 0 et reponse(q_duree_admise) = faux",
         "reponse(q_fraction)", "moyen", SO,
         [{"id": "q_duree_admise", "texte": "Duree d usage admise ?", "type": "booleen"},
          {"id": "q_fraction", "texte": "Fraction a reintegrer ?", "type": "montant"}],
         {"soldes": {"681": "8000000"}, "reponses": {"q_duree_admise": False, "q_fraction": "2000000"}}, "temporaire"),
        ("BIC-CHG-18A3-FRAISSIEGE", "CGI 2026, art. 18 A 3°", ["631", "632", "634"],
         "solde(631) > 0 ou solde(632) > 0 ou solde(634) > 0",
         "max(0 ; solde(631) + solde(632) + solde(634) - min(0.05 * agregat(CA) ; 0.2 * agregat(FRAIS_GENERAUX)))",
         "eleve", "min(0.05 * agregat(CA) ; 0.2 * agregat(FRAIS_GENERAUX))",
         [{"id": "q_liee", "texte": "Beneficiaire liee ?", "type": "booleen"}],
         {"soldes": {"631": "100000000", "632": "0", "634": "0"}, "agregats": {"CA": "1000000000", "FRAIS_GENERAUX": "200000000"}, "reponses": {}},
         "permanente", "60000000"),
        ("BIC-CHG-18A6-CCATAUX", "CGI 2026, art. 18 A 6°", ["671"],
         "solde(671) > 0 et (reponse(q_capital_libere) = faux ou reponse(q_taux_excede) = vrai)",
         "reponse(q_fraction)", "eleve", SO,
         [{"id": "q_capital_libere", "texte": "Capital libere ?", "type": "booleen"},
          {"id": "q_taux_excede", "texte": "Taux > BCEAO+2 ?", "type": "booleen"},
          {"id": "q_fraction", "texte": "Interets a reintegrer ?", "type": "montant"}],
         {"soldes": {"671": "10000000"}, "reponses": {"q_capital_libere": True, "q_taux_excede": True, "q_fraction": "1500000"}}),
        ("BIC-CHG-18D-IMPOTS", "CGI 2026, art. 18 D", ["64"],
         "solde(64) > 0 et reponse(q_non_deductible) = vrai",
         "reponse(q_montant)", "moyen", SO,
         [{"id": "q_non_deductible", "texte": "Impots non deductibles ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"641": "8000000"}, "reponses": {"q_non_deductible": True, "q_montant": "3000000"}}),
        ("BIC-CHG-18F-PENALITES", "CGI 2026, art. 18 F", ["6580", "647"],
         "solde(6580) > 0 ou solde(647) > 0",
         "solde(6580) + solde(647)", "faible", SO,
         [{"id": "q_est_sanction", "texte": "Amende/penalite ?", "type": "booleen"}],
         {"soldes": {"6580": "2000000", "647": "500000"}, "reponses": {}}),
        ("BIC-CHG-18E-CADEAUX", "CGI 2026, art. 18 E", ["6257", "6583"],
         "(solde(6257) > 0 ou solde(6583) > 0) et reponse(q_non_pro) = vrai",
         "reponse(q_montant)", "moyen", SO,
         [{"id": "q_non_pro", "texte": "Sans caractere professionnel ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"6257": "1500000", "6583": "0"}, "reponses": {"q_non_pro": True, "q_montant": "1500000"}}),
        ("BIC-CHG-18-MIXTES", "CGI 2026, art. 18 (charges mixtes)", ["625", "624"],
         "reponse(q_mixte) = vrai et reponse(q_montant_mixte) > 0",
         "(2 * reponse(q_montant_mixte)) / 3", "moyen", "reponse(q_montant_mixte) / 3",
         [{"id": "q_mixte", "texte": "Charges mixtes ?", "type": "booleen"},
          {"id": "q_montant_mixte", "texte": "Montant charges mixtes ?", "type": "montant"}],
         {"soldes": {"625": "1"}, "reponses": {"q_mixte": True, "q_montant_mixte": "9000000"}},
         "permanente", "6000000"),
        ("BIC-AMORT-18B-VEHICULES", "CGI 2026, art. 18 B (vehicules tourisme)", ["681"],
         "solde(681) > 0 et reponse(q_vt) = vrai et reponse(q_plafond_excede) = vrai",
         "reponse(q_fraction)", "moyen", SO,
         [{"id": "q_vt", "texte": "Vehicule de tourisme ?", "type": "booleen"},
          {"id": "q_plafond_excede", "texte": "Prix > plafond ?", "type": "booleen"},
          {"id": "q_fraction", "texte": "Fraction a reintegrer ?", "type": "montant"}],
         {"soldes": {"681": "4000000"}, "reponses": {"q_vt": True, "q_plafond_excede": True, "q_fraction": "1000000"}}, "permanente"),
        ("BIC-CHG-18B-CREDITBAILVT", "CGI 2026, art. 18 B (credit-bail VT)", ["622", "6125"],
         "reponse(q_vt) = vrai et reponse(q_part_non_ded) > 0",
         "reponse(q_part_non_ded)", "moyen", SO,
         [{"id": "q_vt", "texte": "Vehicule de tourisme ?", "type": "booleen"},
          {"id": "q_part_non_ded", "texte": "Part loyer non deductible ?", "type": "montant"}],
         {"soldes": {"622": "1"}, "reponses": {"q_vt": True, "q_part_non_ded": "800000"}}),
        ("BIC-PROV-18E1-CREANCES", "CGI 2026, art. 18 E 1° ; relevé art. 36", ["6594", "691"],
         "(solde(6594) > 0 ou solde(691) > 0) et (reponse(q_individualisee) = faux ou reponse(q_releve) = faux)",
         "solde(6594) + solde(691)", "moyen", SO,
         [{"id": "q_individualisee", "texte": "Creances individualisees ?", "type": "booleen"},
          {"id": "q_releve", "texte": "Au releve provisions ?", "type": "booleen"}],
         {"soldes": {"6594": "7000000", "691": "0"}, "reponses": {"q_individualisee": False, "q_releve": True}}, "temporaire"),
        ("BIC-CHG-18A5-INTERETS", "CGI 2026, art. 18 A 5°", ["671", "672", "674"],
         "(solde(671) > 0 ou solde(672) > 0 ou solde(674) > 0) et reponse(q_hors_exploitation) = vrai",
         "reponse(q_montant)", "moyen", SO,
         [{"id": "q_hors_exploitation", "texte": "Hors exploitation ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"671": "0", "672": "4000000", "674": "0"}, "reponses": {"q_hors_exploitation": True, "q_montant": "4000000"}}),
        ("BIC-CHG-18A-ASSURANCES", "CGI 2026, art. 18 A", ["625"],
         "solde(625) > 0 et reponse(q_hors_exploitation) = vrai",
         "reponse(q_montant)", "faible", SO,
         [{"id": "q_hors_exploitation", "texte": "Hors exploitation ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"625": "2500000"}, "reponses": {"q_hors_exploitation": True, "q_montant": "2500000"}}),
        ("BIC-CHG-18A1-EXPATRIES", "CGI 2026, art. 18 A 1°", ["661", "667"],
         "(solde(661) > 0 ou solde(667) > 0) et reponse(q_anomalie) = vrai",
         "reponse(q_montant)", "eleve", SO,
         [{"id": "q_anomalie", "texte": "Fictive/excessive ou ITS absentes ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant a reintegrer ?", "type": "montant"}],
         {"soldes": {"661": "0", "667": "20000000"}, "reponses": {"q_anomalie": True, "q_montant": "5000000"}}),
    ]

    for row in doc5:
        ident, ref, comptes, cond, resultat, risque, formule, questions, cas = row[:9]
        nature = row[9] if len(row) > 9 and isinstance(row[9], str) and row[9] in ("permanente", "temporaire", "sans_objet") else "permanente"
        montant = None
        if len(row) > 9 and isinstance(row[9], str) and row[9] not in ("permanente", "temporaire", "sans_objet"):
            # unused
            pass
        if len(row) > 10:
            montant = row[10]
        elif len(row) > 9 and row[9] not in ("permanente", "temporaire", "sans_objet"):
            montant = row[9]
            nature = "permanente"

        # Normalize cas
        cas = dict(cas)
        cas.setdefault("agregats", {})
        cas.setdefault("reponses", {})
        if "declenche_attendu" not in cas:
            cas["declenche_attendu"] = True
        if "montant_attendu" not in cas:
            # default from resultat simple cases
            if montant:
                cas["montant_attendu"] = str(montant)
            else:
                # try from reponse or single solde patterns handled in tests via explicit above
                cas["montant_attendu"] = str(cas.get("reponses", {}).get("q_montant") or cas.get("reponses", {}).get("q_fraction") or cas.get("reponses", {}).get("q_montant_excessif") or "0")

        # Fix special montants
        special_mt = {
            "BIC-CHG-18A3-FRAISSIEGE": "60000000",
            "BIC-CHG-18-MIXTES": "6000000",
            "BIC-CHG-18F-PENALITES": "2500000",
            "BIC-PROV-18E1-CREANCES": "7000000",
            "BIC-CHG-18A1-SALAIRES": "50000000",
            "BIC-CHG-18A2-LOYERS": "5000000",
            "BIC-AMORT-18B-GENERAL": "2000000",
            "BIC-CHG-18A6-CCATAUX": "1500000",
            "BIC-CHG-18D-IMPOTS": "3000000",
            "BIC-CHG-18E-CADEAUX": "1500000",
            "BIC-AMORT-18B-VEHICULES": "1000000",
            "BIC-CHG-18B-CREDITBAILVT": "800000",
            "BIC-CHG-18A5-INTERETS": "4000000",
            "BIC-CHG-18A-ASSURANCES": "2500000",
            "BIC-CHG-18A1-EXPATRIES": "5000000",
        }
        if ident in special_mt:
            cas["montant_attendu"] = special_mt[ident]

        natures = {
            "BIC-AMORT-18B-GENERAL": "temporaire",
            "BIC-PROV-18E1-CREANCES": "temporaire",
        }
        nature = natures.get(ident, "permanente")

        ac = ["date d effet 01/01/2026", "valeurs issues doc client 5 — a valider metier"]
        if ident == "BIC-CHG-18A3-FRAISSIEGE":
            ac.extend(["taux 5%/20%", "definition FRAIS_GENERAUX"])

        out.append(_base(
            identifiant=ident, impot="BIC", reference_legale=ref,
            profils_applicables=["Entreprises au regime reel"],
            comptes_declencheurs=comptes, nature=nature,
            condition_declenchement=cond, conditions_fond=ref,
            formule_plafonnement=formule, questions_generees=questions,
            resultat=resultat, niveau_risque=risque,
            a_confirmer=ac, cas_test=cas,
        ))
    return out


def generer() -> int:
    """Ecrit les 20 fiches Lot1. Le harnais 57 est aligne par generer_regles_lots_234."""
    RACINE.mkdir(parents=True, exist_ok=True)
    regles = _regles()
    assert len(regles) == 20, len(regles)
    for r in regles:
        _dump(r, RACINE / f"{r['identifiant']}.yaml")
    metier = len(list(RACINE.glob("*.yaml")))
    print(f"genere {len(regles)} fiches Lot1 ; racine metier={metier}")
    return 0


def main() -> int:
    return generer()


if __name__ == "__main__":
    sys.exit(main())
