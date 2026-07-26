"""Genere les 36 fiches metier Lots 2/3 + RA et retire les EMPLACEMENT.

Appelé par make seed apres generer_regles_lot1_bic.
Parametres marques a_confirmer — pas du droit positif certifié.
"""
from __future__ import annotations

from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[2] / "referentiel"
EMP = RACINE / "emplacements"
SO = "sans objet"
AC = ["date d effet 01/01/2026", "valeurs issues docs client 6/9/10 — a valider metier"]


def _dump(regle: dict, chemin: Path) -> None:
    chemin.write_text(
        yaml.safe_dump(regle, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def _base(**kw: object) -> dict:
    r: dict = {
        "reference_source": "CGI 2026 — docs client 6/9/10 (propositions metier)",
        "date_effet": "2026-01-01",
        "effets_croises": [],
        "a_confirmer": list(AC),
        "formule_plafonnement": SO,
        "questions_generees": [],
        "profils_applicables": ["Entreprises au regime reel"],
        "nature": "sans_objet",
    }
    r.update(kw)
    return r


def _cas(soldes: dict, montant: str, *, reponses: dict | None = None, agregats: dict | None = None) -> dict:
    return {
        "soldes": soldes,
        "agregats": agregats or {},
        "reponses": reponses or {},
        "declenche_attendu": True,
        "montant_attendu": montant,
    }


def _regles() -> list[dict]:
    out: list[dict] = []

    # ---- Lot 2 : TVA (3) ----
    out.append(_base(
        identifiant="TVA-COL-RAPPRO-CA", impot="TVA",
        reference_legale="CGI 2026, art. 339 et s. — rapprochement CA / TVA collectee",
        comptes_declencheurs=["701", "702", "703", "704", "705", "706", "707", "443"],
        condition_declenchement="agregat(CA) > 0 et reponse(q_ecart_ca_tva) = vrai",
        conditions_fond="Ecart entre CA comptable et CA declare a la TVA ?",
        questions_generees=[
            {"id": "q_ecart_ca_tva", "texte": "Ecart CA comptable / CA declare TVA ?", "type": "booleen"},
            {"id": "q_montant_ecart", "texte": "Montant de l ecart a signaler ?", "type": "montant"},
        ],
        resultat="reponse(q_montant_ecart)", niveau_risque="eleve",
        cas_test=_cas({"701": "100000000", "443": "18000000"}, "5000000",
                      reponses={"q_ecart_ca_tva": True, "q_montant_ecart": "5000000"},
                      agregats={"CA": "100000000"}),
    ))
    out.append(_base(
        identifiant="TVA-DED-PRORATA", impot="TVA",
        reference_legale="CGI 2026 — prorata de deduction TVA",
        comptes_declencheurs=["445"],
        condition_declenchement="solde(445) > 0 et reponse(q_operations_mixtes) = vrai",
        conditions_fond="Coexistence operations taxees et exonerees ?",
        questions_generees=[
            {"id": "q_operations_mixtes", "texte": "Operations taxees et exonerees ?", "type": "booleen"},
            {"id": "q_tva_non_ded", "texte": "TVA non deductible (prorata) ?", "type": "montant"},
        ],
        resultat="reponse(q_tva_non_ded)", niveau_risque="moyen",
        cas_test=_cas({"445": "20000000"}, "3000000",
                      reponses={"q_operations_mixtes": True, "q_tva_non_ded": "3000000"}),
    ))
    out.append(_base(
        identifiant="TVA-TIERS-NONRESIDENT", impot="TVA",
        reference_legale="CGI 2026, art. 442, 351 et 352",
        comptes_declencheurs=["604", "611", "622", "632"],
        condition_declenchement="(solde(604) > 0 ou solde(611) > 0 ou solde(622) > 0 ou solde(632) > 0) et reponse(q_prestataire_nonres) = vrai",
        conditions_fond="Prestataire non etabli en CI, prestation utilisee localement ?",
        questions_generees=[
            {"id": "q_prestataire_nonres", "texte": "Prestataire non resident ?", "type": "booleen"},
            {"id": "q_tva_tiers", "texte": "TVA due pour compte de tiers ?", "type": "montant"},
        ],
        resultat="reponse(q_tva_tiers)", niveau_risque="eleve",
        cas_test=_cas({"604": "0", "611": "10000000", "622": "0", "632": "0"}, "1800000",
                      reponses={"q_prestataire_nonres": True, "q_tva_tiers": "1800000"}),
    ))

    # ---- Lot 2 : OBL (6) hors OBL-108 ----
    out.append(_base(
        identifiant="OBL-36-ETII", impot="OBL",
        reference_legale="CGI 2026, art. 36 — etat des transactions internationales",
        comptes_declencheurs=["601", "701", "622"],
        condition_declenchement="reponse(q_parties_liees_etranger) = vrai",
        conditions_fond="Liens avec entreprise hors CI et transactions de l exercice ?",
        questions_generees=[
            {"id": "q_parties_liees_etranger", "texte": "Parties liees a l etranger ?", "type": "booleen"},
            {"id": "q_etii_manquant", "texte": "ETII manquant ou incomplet ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Enjeu estime ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        cas_test=_cas({"601": "1", "701": "1", "622": "1"}, "1000000",
                      reponses={"q_parties_liees_etranger": True, "q_etii_manquant": True, "q_montant": "1000000"}),
    ))
    out.append(_base(
        identifiant="OBL-36BIS-CBCR", impot="OBL",
        reference_legale="CGI 2026, art. 36 bis — CbCR",
        comptes_declencheurs=[],
        condition_declenchement="reponse(q_seuil_cbcr) = vrai et reponse(q_declaration_absente) = vrai",
        conditions_fond="CA consolide groupe >= seuil CbCR (a confirmer) ?",
        questions_generees=[
            {"id": "q_seuil_cbcr", "texte": "Seuil CbCR atteint ?", "type": "booleen"},
            {"id": "q_declaration_absente", "texte": "Declaration CbCR absente ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Enjeu estime ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        a_confirmer=AC + ["seuil 250 Md FCFA a confirmer"],
        cas_test=_cas({}, "2000000",
                      reponses={"q_seuil_cbcr": True, "q_declaration_absente": True, "q_montant": "2000000"}),
    ))
    out.append(_base(
        identifiant="OBL-49BIS-REGISTRES", impot="OBL",
        reference_legale="CGI 2026, art. 49 bis — registres societaires",
        comptes_declencheurs=[],
        condition_declenchement="reponse(q_registre_manquant) = vrai",
        conditions_fond="Registre actionnaires / associes tenu ?",
        questions_generees=[
            {"id": "q_registre_manquant", "texte": "Registre obligatoire manquant ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Enjeu estime ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        profils_applicables=["Societes commerciales"],
        cas_test=_cas({}, "500000",
                      reponses={"q_registre_manquant": True, "q_montant": "500000"}),
    ))
    out.append(_base(
        identifiant="OBL-49TER-RBE", impot="OBL",
        reference_legale="CGI 2026, art. 49 ter — registre des beneficiaires effectifs",
        comptes_declencheurs=[],
        condition_declenchement="reponse(q_rbe_manquant) = vrai",
        conditions_fond="RBE tenu et a jour ?",
        questions_generees=[
            {"id": "q_rbe_manquant", "texte": "RBE manquant ou obsolete ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Enjeu estime ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        profils_applicables=["Personnes morales"],
        cas_test=_cas({}, "1500000",
                      reponses={"q_rbe_manquant": True, "q_montant": "1500000"}),
    ))
    out.append(_base(
        identifiant="OBL-338-REEVALUATION", impot="OBL",
        reference_legale="CGI 2026, art. 338 — reevaluation d actifs",
        comptes_declencheurs=["105", "106", "211", "213"],
        condition_declenchement="(solde(105) > 0 ou solde(106) > 0) et reponse(q_reeval_non_declaree) = vrai",
        conditions_fond="Reevaluation d actifs correctement declaree ?",
        questions_generees=[
            {"id": "q_reeval_non_declaree", "texte": "Reevaluation non declaree / incomplete ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Montant a signaler ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"105": "10000000", "106": "0", "211": "1", "213": "0"}, "10000000",
                      reponses={"q_reeval_non_declaree": True, "q_montant": "10000000"}),
    ))
    out.append(_base(
        identifiant="OBL-ACOMPTES-IMPUTATION", impot="OBL",
        reference_legale="CGI 2026 — acomptes d impot et imputation",
        comptes_declencheurs=["444", "4456"],
        condition_declenchement="(solde(444) > 0 ou solde(4456) > 0) et reponse(q_imputation_anormale) = vrai",
        conditions_fond="Imputation des acomptes correcte ?",
        questions_generees=[
            {"id": "q_imputation_anormale", "texte": "Imputation anormale des acomptes ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Ecart d imputation ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"444": "5000000", "4456": "0"}, "500000",
                      reponses={"q_imputation_anormale": True, "q_montant": "500000"}),
    ))

    # ---- Lot 2 : ENR / Timbre (3) ----
    out.append(_base(
        identifiant="ENR-666-ACTES", impot="ENR",
        reference_legale="CGI 2026, art. 666 et s. — droits d enregistrement",
        comptes_declencheurs=["101", "105", "106", "11"],
        condition_declenchement="(solde(101) > 0 ou solde(105) > 0) et reponse(q_acte_non_enregistre) = vrai",
        conditions_fond="Acte soumis a enregistrement non enregistre ?",
        questions_generees=[
            {"id": "q_acte_non_enregistre", "texte": "Acte non enregistre ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Droits dus estimes ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"101": "50000000", "105": "0", "106": "0", "11": "0"}, "2500000",
                      reponses={"q_acte_non_enregistre": True, "q_montant": "2500000"}),
    ))
    out.append(_base(
        identifiant="TIMBRE-805-DOCS", impot="TIMBRE",
        reference_legale="CGI 2026, art. 805 et s. — droit de timbre",
        comptes_declencheurs=[],
        condition_declenchement="reponse(q_timbre_manquant) = vrai",
        conditions_fond="Documents soumis au timbre sans droit appose ?",
        questions_generees=[
            {"id": "q_timbre_manquant", "texte": "Timbre manquant sur documents ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Droits de timbre estimes ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="faible",
        cas_test=_cas({}, "200000",
                      reponses={"q_timbre_manquant": True, "q_montant": "200000"}),
    ))
    out.append(_base(
        identifiant="ENR-29-CONDAMNATION", impot="ENR",
        reference_legale="CGI 2026, art. 29 — droits de condamnation",
        comptes_declencheurs=["671", "678"],
        condition_declenchement="(solde(671) > 0 ou solde(678) > 0) et reponse(q_condamnation) = vrai",
        conditions_fond="Condamnation judiciaire soumise a droits ?",
        questions_generees=[
            {"id": "q_condamnation", "texte": "Condamnation soumise a enregistrement ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Droits dus ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"671": "0", "678": "3000000"}, "300000",
                      reponses={"q_condamnation": True, "q_montant": "300000"}),
    ))

    # ---- Lot 3 : 11 fiches ----
    out.append(_base(
        identifiant="RAS-92-NONRESIDENT", impot="RAS",
        reference_legale="CGI 2026, art. 92 — RAS non residents",
        comptes_declencheurs=["622", "651", "672"],
        condition_declenchement="(solde(622) > 0 ou solde(651) > 0 ou solde(672) > 0) et reponse(q_beneficiaire_nonres) = vrai",
        conditions_fond="Versement a non resident, prestation utilisee en CI ?",
        questions_generees=[
            {"id": "q_beneficiaire_nonres", "texte": "Beneficiaire non resident ?", "type": "booleen"},
            {"id": "q_ras_due", "texte": "RAS due non prelevee ?", "type": "montant"},
        ],
        resultat="reponse(q_ras_due)", niveau_risque="eleve",
        cas_test=_cas({"622": "8000000", "651": "0", "672": "0"}, "1600000",
                      reponses={"q_beneficiaire_nonres": True, "q_ras_due": "1600000"}),
    ))
    out.append(_base(
        identifiant="IRC-194-CREANCES", impot="IRC",
        reference_legale="CGI 2026, art. 194 — IRC interets non residents",
        comptes_declencheurs=["671", "674", "455", "462"],
        condition_declenchement="(solde(671) > 0 ou solde(674) > 0) et reponse(q_creancier_nonres) = vrai",
        conditions_fond="Interets verses a creancier hors CI ?",
        questions_generees=[
            {"id": "q_creancier_nonres", "texte": "Creancier non resident ?", "type": "booleen"},
            {"id": "q_irc_due", "texte": "IRC due ?", "type": "montant"},
        ],
        resultat="reponse(q_irc_due)", niveau_risque="eleve",
        cas_test=_cas({"671": "5000000", "674": "0", "455": "1", "462": "0"}, "900000",
                      reponses={"q_creancier_nonres": True, "q_irc_due": "900000"}),
    ))
    out.append(_base(
        identifiant="IRVM-182-DISTRIB", impot="IRVM",
        reference_legale="CGI 2026, art. 180 a 189 — IRVM distributions",
        comptes_declencheurs=["457", "455", "11"],
        condition_declenchement="(solde(457) > 0 ou solde(455) > 0) et reponse(q_distrib) = vrai",
        conditions_fond="Distribution de resultats / dividendes ?",
        questions_generees=[
            {"id": "q_distrib", "texte": "Distribution decidee / inscrite ?", "type": "booleen"},
            {"id": "q_irvm_due", "texte": "IRVM due ?", "type": "montant"},
        ],
        resultat="reponse(q_irvm_due)", niveau_risque="eleve",
        cas_test=_cas({"457": "20000000", "455": "0", "11": "0"}, "3000000",
                      reponses={"q_distrib": True, "q_irvm_due": "3000000"}),
    ))
    out.append(_base(
        identifiant="PAT-272-PATENTE", impot="PAT",
        reference_legale="CGI 2026, art. 272 et s. — patente",
        comptes_declencheurs=["635", "701"],
        condition_declenchement="agregat(CA) > 0 et reponse(q_patente_anormale) = vrai",
        conditions_fond="Patente declaree coherente avec l activite ?",
        questions_generees=[
            {"id": "q_patente_anormale", "texte": "Patente manquante ou sous-evaluee ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Ecart patente ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"635": "1000000", "701": "50000000"}, "400000",
                      reponses={"q_patente_anormale": True, "q_montant": "400000"},
                      agregats={"CA": "50000000"}),
    ))
    out.append(_base(
        identifiant="FONC-34-PATRIMOINE", impot="FONC",
        reference_legale="CGI 2026, art. 34 — contribution fonciere patrimoine",
        comptes_declencheurs=["211", "213", "22"],
        condition_declenchement="(solde(211) > 0 ou solde(213) > 0 ou solde(22) > 0) et reponse(q_foncier_manquant) = vrai",
        conditions_fond="Biens immobiliers correctement declares ?",
        questions_generees=[
            {"id": "q_foncier_manquant", "texte": "Contribution fonciere manquante ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Droits estimes ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"211": "100000000", "213": "0", "22": "0"}, "800000",
                      reponses={"q_foncier_manquant": True, "q_montant": "800000"}),
    ))
    out.append(_base(
        identifiant="FONC-171-ACOMPTELOYER", impot="FONC",
        reference_legale="CGI 2026, art. 171 — acompte sur loyers",
        comptes_declencheurs=["706", "707"],
        condition_declenchement="(solde(706) > 0 ou solde(707) > 0) et reponse(q_acompte_loyer) = vrai",
        conditions_fond="Acomptes sur loyers preleves / reverses ?",
        questions_generees=[
            {"id": "q_acompte_loyer", "texte": "Acompte loyer non reverse ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Montant acompte du ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        cas_test=_cas({"706": "12000000", "707": "0"}, "1800000",
                      reponses={"q_acompte_loyer": True, "q_montant": "1800000"}),
    ))
    out.append(_base(
        identifiant="ITS-119-MASSESAL", impot="ITS",
        reference_legale="CGI 2026, art. 119 — ITS masse salariale",
        comptes_declencheurs=["661", "662", "663", "664", "667"],
        condition_declenchement="(solde(661) > 0 ou solde(667) > 0) et reponse(q_ecart_masse) = vrai",
        conditions_fond="Ecart masse salariale comptable / declaree ITS ?",
        questions_generees=[
            {"id": "q_ecart_masse", "texte": "Ecart masse salariale ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Assiette omise ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        cas_test=_cas({"661": "80000000", "662": "0", "663": "0", "664": "0", "667": "0"}, "5000000",
                      reponses={"q_ecart_masse": True, "q_montant": "5000000"}),
    ))
    out.append(_base(
        identifiant="CE-146-EMPLOYEUR", impot="CE",
        reference_legale="CGI 2026, art. 134 a 146 — contribution employeur",
        comptes_declencheurs=["661", "664"],
        condition_declenchement="solde(661) > 0 et reponse(q_ce_anormale) = vrai",
        conditions_fond="CE calculee sur assiette complete (avantages inclus) ?",
        questions_generees=[
            {"id": "q_ce_anormale", "texte": "CE sous-evaluee ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Complement CE ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="eleve",
        cas_test=_cas({"661": "80000000", "664": "0"}, "2000000",
                      reponses={"q_ce_anormale": True, "q_montant": "2000000"}),
    ))
    out.append(_base(
        identifiant="CE-143-APPRENTISSAGE", impot="CE",
        reference_legale="CGI 2026, art. 143 — taxe d apprentissage",
        comptes_declencheurs=["633", "618"],
        condition_declenchement="reponse(q_apprentissage) = vrai",
        conditions_fond="Taxe d apprentissage / actions formation ?",
        questions_generees=[
            {"id": "q_apprentissage", "texte": "Anomalie taxe apprentissage ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Montant a signaler ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="faible",
        cas_test=_cas({"633": "1", "618": "0"}, "100000",
                      reponses={"q_apprentissage": True, "q_montant": "100000"}),
    ))
    out.append(_base(
        identifiant="OBNL-339-NONLUCRATIF", impot="OBNL",
        reference_legale="CGI 2026, art. 339 — organismes non lucratifs",
        comptes_declencheurs=["70", "60"],
        condition_declenchement="reponse(q_lucratif) = vrai",
        conditions_fond="Activite lucrative d un OBNL ?",
        questions_generees=[
            {"id": "q_lucratif", "texte": "Activite lucrative detectee ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Resultat taxable estime ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        profils_applicables=["Organismes non lucratifs"],
        cas_test=_cas({"70": "1", "60": "1"}, "3000000",
                      reponses={"q_lucratif": True, "q_montant": "3000000"}),
    ))
    out.append(_base(
        identifiant="OBNL-35-STARTUP", impot="OBNL",
        reference_legale="CGI 2026, art. 35 — regime startup / innovant",
        comptes_declencheurs=["701"],
        condition_declenchement="reponse(q_startup_anomalie) = vrai",
        conditions_fond="Conditions du regime startup respectees ?",
        questions_generees=[
            {"id": "q_startup_anomalie", "texte": "Conditions regime non respectees ?", "type": "booleen"},
            {"id": "q_montant", "texte": "Avantage indu ?", "type": "montant"},
        ],
        resultat="reponse(q_montant)", niveau_risque="moyen",
        profils_applicables=["Startups / innovants"],
        cas_test=_cas({"701": "1"}, "1000000",
                      reponses={"q_startup_anomalie": True, "q_montant": "1000000"}),
    ))

    # ---- RA (13) ----
    ra_specs = [
        ("RA-CNX-01", "Connexion fiscalo-comptable", ["13", "695"], "eleve",
         "reponse(q_revue_cnx) = vrai", "reponse(q_montant)",
         {"13": "200000000", "695": "50000000"}, "200000000",
         [{"id": "q_revue_cnx", "texte": "Lancer connexion fiscalo-comptable ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Resultat avant impot retenu ?", "type": "montant"}],
         {"q_revue_cnx": True, "q_montant": "200000000"}),
        ("RA-CNX-02", "Taux d impot effectif vs normatif", ["695", "13"], "moyen",
         "solde(695) > 0 et reponse(q_ecart_taux) = vrai", "reponse(q_montant)",
         {"695": "50000000", "13": "200000000"}, "5000000",
         [{"id": "q_ecart_taux", "texte": "Ecart taux effectif / normatif ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Ecart a signaler ?", "type": "montant"}],
         {"q_ecart_taux": True, "q_montant": "5000000"}),
        ("RA-FISC-01", "Differences permanentes reintegrations", ["671", "672", "658"], "eleve",
         "solde(671) > 0 ou solde(672) > 0 ou solde(658) > 0", "solde(671) + solde(672) + solde(658)",
         {"671": "1000000", "672": "2000000", "658": "0"}, "3000000"),
        ("RA-FISC-02", "Differences permanentes deductions", ["76", "761"], "moyen",
         "solde(76) > 0 ou solde(761) > 0", "reponse(q_montant)",
         {"76": "5000000", "761": "0"}, "1000000",
         [{"id": "q_montant", "texte": "Deduction permanente ?", "type": "montant"}],
         {"q_montant": "1000000"}),
        ("RA-FISC-03", "Differences temporaires reintegrations", ["691", "151"], "moyen",
         "solde(691) > 0 ou solde(151) > 0", "solde(691) + solde(151)",
         {"691": "4000000", "151": "0"}, "4000000"),
        ("RA-FISC-04", "Differences temporaires deductions", ["781", "151"], "moyen",
         "solde(781) > 0 et reponse(q_reprise_taxee) = vrai", "reponse(q_montant)",
         {"781": "2000000", "151": "0"}, "2000000",
         [{"id": "q_reprise_taxee", "texte": "Reprise anterieurement taxee ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant deduction temporaire ?", "type": "montant"}],
         {"q_reprise_taxee": True, "q_montant": "2000000"}),
        ("RA-FISC-05", "Resultat fiscal synthese", ["13"], "eleve",
         "reponse(q_synthese_rf) = vrai", "reponse(q_montant)",
         {"13": "200000000"}, "200000000",
         [{"id": "q_synthese_rf", "texte": "Calculer synthese resultat fiscal ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Resultat fiscal ?", "type": "montant"}],
         {"q_synthese_rf": True, "q_montant": "200000000"}),
        ("RA-IMMO-01", "Investissements incorporels et corporels", ["20", "21", "22", "23"], "moyen",
         "solde(20) > 0 ou solde(21) > 0 ou solde(22) > 0 ou solde(23) > 0", "reponse(q_montant)",
         {"20": "0", "21": "50000000", "22": "0", "23": "0"}, "1000000",
         [{"id": "q_montant", "texte": "Anomalie immo a signaler ?", "type": "montant"}],
         {"q_montant": "1000000"}),
        ("RA-IMMO-02", "Investissements financiers", ["26", "27"], "moyen",
         "solde(26) > 0 ou solde(27) > 0", "reponse(q_montant)",
         {"26": "10000000", "27": "0"}, "500000",
         [{"id": "q_montant", "texte": "Anomalie titres ?", "type": "montant"}],
         {"q_montant": "500000"}),
        ("RA-RECON-01", "Reconciliation capitaux propres", ["10", "11", "12", "13"], "eleve",
         "reponse(q_ecart_cp) = vrai", "reponse(q_montant)",
         {"10": "1", "11": "1", "12": "1", "13": "1"}, "2500000",
         [{"id": "q_ecart_cp", "texte": "Ecart reconciliation CP ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Ecart ?", "type": "montant"}],
         {"q_ecart_cp": True, "q_montant": "2500000"}),
        ("RA-TRANSF-01", "Transferts de charges", ["791", "781"], "moyen",
         "solde(791) > 0 ou solde(781) > 0", "reponse(q_montant)",
         {"791": "3000000", "781": "0"}, "500000",
         [{"id": "q_montant", "texte": "Transfert anormal ?", "type": "montant"}],
         {"q_montant": "500000"}),
        ("RA-STOCK-01", "Reconciliation variations de stocks", ["31", "32", "33", "603"], "moyen",
         "solde(31) > 0 ou solde(32) > 0 ou solde(33) > 0 ou solde(603) <> 0", "reponse(q_montant)",
         {"31": "10000000", "32": "0", "33": "0", "603": "2000000"}, "750000",
         [{"id": "q_montant", "texte": "Ecart stock bilan / P&L ?", "type": "montant"}],
         {"q_montant": "750000"}),
        ("RA-CIE-01", "Credit d impot pour emploi", ["4457", "695"], "faible",
         "reponse(q_cie) = vrai", "reponse(q_montant)",
         {"4457": "1", "695": "1"}, "300000",
         [{"id": "q_cie", "texte": "CIE a controler ?", "type": "booleen"},
          {"id": "q_montant", "texte": "Montant CIE douteux ?", "type": "montant"}],
         {"q_cie": True, "q_montant": "300000"}),
    ]

    for spec in ra_specs:
        ident, lib, comptes, risque, cond, resultat, soldes, montant = spec[:8]
        questions = spec[8] if len(spec) > 8 else []
        reponses = spec[9] if len(spec) > 9 else {}
        # Fill zero soldes for all accounts in condition for non-short-circuit OR
        soldes_full = {c: soldes.get(c, "0") for c in comptes}
        soldes_full.update(soldes)
        out.append(_base(
            identifiant=ident, impot="RA",
            reference_legale=f"Revue analytique — {lib} (doc client 6)",
            comptes_declencheurs=comptes,
            condition_declenchement=cond,
            conditions_fond=lib,
            questions_generees=questions,
            resultat=resultat, niveau_risque=risque,
            cas_test=_cas(soldes_full, montant, reponses=reponses),
        ))

    return out


def generer() -> int:
    RACINE.mkdir(parents=True, exist_ok=True)
    regles = _regles()
    assert len(regles) == 36, len(regles)
    for r in regles:
        _dump(r, RACINE / f"{r['identifiant']}.yaml")
    # Retirer tous les EMPLACEMENT (conversion 1:1 vers metier)
    if EMP.exists():
        for p in EMP.glob("EMPLACEMENT-*.yaml"):
            p.unlink()
        # garder le dossier vide ou le supprimer
        try:
            next(EMP.iterdir())
        except StopIteration:
            pass
    total = len(list(RACINE.rglob("*.yaml")))
    metier = len(list(RACINE.glob("*.yaml")))
    print(f"genere {len(regles)} fiches Lots2/3/RA ; racine={metier} ; total yaml={total}")
    if metier != 57 or total != 57:
        raise SystemExit(f"harnais attend 57 metier, trouve racine={metier} total={total}")
    return 0


def main() -> int:
    return generer()


if __name__ == "__main__":
    raise SystemExit(main())
