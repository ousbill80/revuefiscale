"""Dossier de travail ZIP : contenu, résilience par pièce, cloisonnement."""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme import archive_mission  # noqa: E402
from backend.plateforme.compte_rendu import enregistrer_compte_rendu  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.reponses_client import enregistrer_reponse  # noqa: E402
from backend.plateforme.temps_mission import saisir_temps  # noqa: E402
from backend.plateforme.visas_mission import poser_visa  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _commentaire_disponible,
    _conclusions_non_verifiables,
    _connexion,
    _mission,
)


def _preparer(session, tid, mid, suffixe):
    """Un commentaire disponible (2 questions) + 2 conclusions non vérifiables."""
    _conclusions_non_verifiables(
        session,
        tid,
        mid,
        [
            (f"OBL-36-ETII-{suffixe}", "État des transactions intragroupes"),
            (f"BIC-12-AMORT-{suffixe}", "Justification des amortissements"),
        ],
    )
    _commentaire_disponible(session, tid, mid)


def _telecharger_zip(client, h, mid):
    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip", headers=h)
    assert resp.status_code == 200, resp.text
    return resp


def test_zip_valide_contenu_et_sommaire(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    resp = _telecharger_zip(client, h, mid)
    # ZIP valide (magic) + en-têtes de téléchargement.
    assert resp.content[:4] == b"PK\x03\x04"
    assert resp.headers["content-type"].startswith("application/zip")
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "dossier_travail_PM_DEMANDE_FICTIF_2025.zip" in dispo

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "00_sommaire.txt" in noms
        assert "02_rapport_restitution.docx" in noms
        assert "03_rapport_restitution.pdf" in noms
        assert "06_suivi_circularisation.csv" in noms
        # Livrables annexes attendus sur cette mission (items présents).
        assert "01_lettre_mission.docx" in noms
        assert "04_rapport_risques.pdf" in noms
        assert "05_demande_renseignements.docx" in noms
        assert "07_controle_cloture.txt" in noms

        # Chaque format est réellement celui annoncé.
        assert z.read("02_rapport_restitution.docx")[:4] == b"PK\x03\x04"
        assert z.read("03_rapport_restitution.pdf")[:5] == b"%PDF-"
        assert z.read("04_rapport_risques.pdf")[:5] == b"%PDF-"

        # CSV : en-tête « ; » + items du suivi (mêmes clés que l'endpoint).
        csv_txt = z.read("06_suivi_circularisation.csv").decode("utf-8")
        assert csv_txt.splitlines()[0] == "cle_item;libelle;statut;date_relance;note"
        assert "analytique:7011" in csv_txt
        assert f"piece:OBL-36-ETII-{suffixe}" in csv_txt
        assert ";en_attente;" in csv_txt

        # Contrôle de clôture lisible.
        ctrl = z.read("07_controle_cloture.txt").decode("utf-8")
        assert "CONTRÔLE QUALITÉ DE PRÉ-CLÔTURE" in ctrl
        assert "Clôture recommandée" in ctrl

        # Une seule exécution, aucun risque, ni temps/visa/réponse :
        # 08, 09, 10, 11 et 12 sont omises.
        assert "08_comparatif_executions.txt" not in noms
        assert "09_provision_risques.txt" not in noms
        assert "10_temps_mission.csv" not in noms
        assert "11_visas_supervision.txt" not in noms
        assert "12_reponses_client.txt" not in noms

        # 13 — programme de travail : toujours présent (init paresseuse),
        # toutes les diligences à faire sur une mission fraîche.
        assert "13_programme_travail.txt" in noms
        programme = z.read("13_programme_travail.txt").decode("utf-8")
        assert "PROGRAMME DE TRAVAIL" in programme
        assert "[À FAIRE] CAD-01" in programme
        assert "0/15 diligences faites (0.0 %)" in programme

        # 14 — courrier d'envoi du rapport : toujours présent (produit
        # même sans exécution), format Word réel.
        assert "14_courrier_envoi_rapport.docx" in noms
        assert z.read("14_courrier_envoi_rapport.docx")[:4] == b"PK\x03\x04"

        # 15 — échéancier fiscal : toujours présent (dates déterministes),
        # groupé par impôt avec les échéances TVA de l'exercice revu.
        assert "15_echeancier_fiscal.txt" in noms
        echeancier = z.read("15_echeancier_fiscal.txt").decode("utf-8")
        assert "ÉCHÉANCIER FISCAL" in echeancier
        assert "TVA" in echeancier
        assert "exercice 2025" in echeancier

        # 17 — lettre d'affirmation de la direction : toujours présente
        # (produite même sans exécution ni risque), format Word réel.
        assert "17_lettre_affirmation.docx" in noms
        assert z.read("17_lettre_affirmation.docx")[:4] == b"PK\x03\x04"

        # 18 — prescription des risques : toujours présente (listes
        # vides sans risque non clos), avec exercices reprenables.
        assert "18_prescription_risques.txt" in noms
        prescription = z.read("18_prescription_risques.txt").decode("utf-8")
        assert "PRESCRIPTION DES RISQUES" in prescription
        assert "Exercices encore reprenables" in prescription
        assert "RISQUES PRESCRITS À BASCULER (0)" in prescription
        assert "Exposition prescrite" in prescription
        assert "pratique LPF CI" in prescription

        # 19 — civisme déclaratif : toujours présent (rapprochement
        # déterministe) ; sans pièce en data room, les échéances passées
        # sont manquantes.
        assert "19_civisme_fiscal.txt" in noms
        civisme = z.read("19_civisme_fiscal.txt").decode("utf-8")
        assert "CIVISME DÉCLARATIF" in civisme
        assert "exercice 2025" in civisme
        assert "régime : reel" in civisme
        assert "Taux de civisme :" in civisme
        assert "Échéances couvertes  : 0" in civisme
        assert "ÉCHÉANCES MANQUANTES" in civisme
        assert "TVA" in civisme
        assert "Rapprochement consultatif" in civisme

        # 20 — plan d'actions : toujours présent (plan vide sans risque
        # non clos), synthèse à zéro et mention consultative.
        assert "20_plan_actions.txt" in noms
        plan = z.read("20_plan_actions.txt").decode("utf-8")
        assert "PLAN D'ACTIONS POST-REVUE" in plan
        assert "Actions suggérées : 0 (haute : 0, moyenne : 0, basse : 0)" in plan
        assert "Exposition totale : 0 FCFA" in plan
        assert "Aucun risque ouvert — rien à planifier." in plan
        assert "consultatif" in plan

        # 21 — courrier de relance : toujours présent (items du suivi en
        # attente sur cette mission → liste numérotée), mention de relecture.
        assert "21_courrier_relance.txt" in noms
        relance = z.read("21_courrier_relance.txt").decode("utf-8")
        assert "Objet : Relance — pièces et renseignements en attente" in relance
        assert "Madame, Monsieur," in relance
        assert "demeurent en attente" in relance
        assert "1. " in relance
        assert "aucune relance n'est nécessaire" not in relance
        assert "Courrier généré automatiquement" in relance

        # 22 — bilan de pré-clôture : toujours présent (points ok /
        # attention, jamais bloquant) ; mission fraîche sans visa ni
        # temps → points d'attention et « prêt à clôturer : non ».
        assert "22_bilan_cloture.txt" in noms
        bilan = z.read("22_bilan_cloture.txt").decode("utf-8")
        assert "BILAN DE PRÉ-CLÔTURE" in bilan
        assert f"Mission #{mid}" in bilan
        assert "statut :" in bilan
        assert "bilan au" in bilan
        assert "[ATTENTION] Aucun visa posé (0/4 phases)" in bilan
        assert "[ATTENTION] Aucun temps saisi" in bilan
        assert "point(s) d'attention" in bilan
        assert "prêt à clôturer : non" in bilan
        assert (
            "Bilan consultatif — la clôture reste à l'appréciation du "
            "fiscaliste." in bilan
        )

        # 23 — ordre du jour de restitution : toujours présent (sections
        # « à compléter en séance » sans données), mention consultative.
        assert "23_ordre_du_jour.txt" in noms
        odj = z.read("23_ordre_du_jour.txt").decode("utf-8")
        assert "ORDRE DU JOUR — RÉUNION DE RESTITUTION" in odj
        assert "PM Demande FICTIF" in odj
        assert "exercice 2025" in odj
        assert "1. Introduction et rappel du périmètre de la mission" in odj
        assert "6. Questions diverses" in odj
        assert (
            "Document de travail interne préparatoire à la réunion de "
            "restitution — consultatif" in odj
        )

        # 24 — compte-rendu de réunion : absent (aucun consigné).
        assert "24_compte_rendu_reunion.txt" not in noms

        # Sommaire : identification + pièces incluses + omissions motivées.
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "DOSSIER DE TRAVAIL" in sommaire
        assert "PM Demande FICTIF" in sommaire
        assert "2025" in sommaire
        assert "PIÈCES INCLUSES (17)" in sommaire
        assert (
            "14_courrier_envoi_rapport.docx : Courrier d'envoi du rapport"
            in sommaire
        )
        assert (
            "15_echeancier_fiscal.txt : Échéancier fiscal de l'exercice revu"
            in sommaire
        )
        assert (
            "17_lettre_affirmation.docx : Lettre d'affirmation de la "
            "direction (à faire signer)" in sommaire
        )
        assert (
            "18_prescription_risques.txt : Analyse de prescription des "
            "risques (délai de reprise)" in sommaire
        )
        assert (
            "19_civisme_fiscal.txt : Civisme déclaratif (échéancier "
            "rapproché des pièces collectées)" in sommaire
        )
        assert (
            "20_plan_actions.txt : Plan d'actions post-revue "
            "(suggestions par risque non clos)" in sommaire
        )
        assert (
            "21_courrier_relance.txt : Courrier de relance des éléments "
            "en attente (circularisation)" in sommaire
        )
        assert (
            "22_bilan_cloture.txt : Bilan de pré-clôture "
            "(points ok / attention, consultatif)" in sommaire
        )
        assert (
            "23_ordre_du_jour.txt : Ordre du jour de la réunion de "
            "restitution" in sommaire
        )
        # 16 — rentabilité : omise sans honoraires ni taux horaire saisis.
        assert "16_rentabilite_mission.txt" not in noms

        assert "PIÈCES OMISES (7)" in sommaire
        assert (
            "24_compte_rendu_reunion.txt : OMISE — aucun compte-rendu de "
            "réunion consigné sur la mission" in sommaire
        )
        assert "08_comparatif_executions.txt : OMISE" in sommaire
        assert "09_provision_risques.txt : OMISE" in sommaire
        assert (
            "10_temps_mission.csv : OMISE — aucun temps saisi sur la mission"
            in sommaire
        )
        assert (
            "11_visas_supervision.txt : OMISE — aucun visa posé sur la mission"
            in sommaire
        )
        assert (
            "12_reponses_client.txt : OMISE — aucune réponse client saisie"
            in sommaire
        )
        assert (
            "16_rentabilite_mission.txt : OMISE — paramètres de rentabilité "
            "non renseignés" in sommaire
        )
        assert "Généré le" in sommaire


def test_comparatif_et_provision_inclus_quand_disponibles(session):
    """Deux exécutions + un risque ouvert probable → pièces 08 et 09."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    # Seconde exécution (règles différentes → nouveaux/disparus).
    _conclusions_non_verifiables(
        session,
        tid,
        mid,
        [(f"TVA-05-DED-{suffixe}", "Déductions de TVA à justifier")],
    )
    with contexte_tenant(session, tid):
        cid = session.execute(
            text("SELECT contribuable_id FROM mission WHERE id = :m"),
            {"m": mid},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, probabilite, "
                "exercice_origine) "
                "VALUES (:t, :c, 'TVA', 'TVA collectée non déclarée', "
                "1000000, 'ouvert', 'probable', 2024)"
            ),
            {"t": tid, "c": cid},
        )
    session.commit()

    resp = _telecharger_zip(client, h, mid)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "08_comparatif_executions.txt" in noms
        assert "09_provision_risques.txt" in noms

        comparatif = z.read("08_comparatif_executions.txt").decode("utf-8")
        assert "COMPARATIF DES DEUX DERNIÈRES EXÉCUTIONS" in comparatif
        assert f"TVA-05-DED-{suffixe}" in comparatif
        assert f"OBL-36-ETII-{suffixe}" in comparatif
        assert "RÈGLES DISPARUES" in comparatif
        assert "Synthèse :" in comparatif
        assert "Delta montant des anomalies" in comparatif

        provision = z.read("09_provision_risques.txt").decode("utf-8")
        assert "PROVISION POUR RISQUES FISCAUX" in provision
        assert "TVA collectée non déclarée" in provision
        assert "Total provision proposée" in provision
        assert "DEBIT  6911" in provision
        assert "CREDIT 1918" in provision

        # 18 — prescription : le risque ouvert 2024 (reprenable) y figure.
        assert "18_prescription_risques.txt" in noms
        prescription = z.read("18_prescription_risques.txt").decode("utf-8")
        assert "TVA collectée non déclarée" in prescription
        assert "exercice 2024" in prescription

        # 20 — plan d'actions : le risque ouvert donne une action suggérée.
        assert "20_plan_actions.txt" in noms
        plan = z.read("20_plan_actions.txt").decode("utf-8")
        assert "PLAN D'ACTIONS POST-REVUE" in plan
        assert "Actions suggérées : 1" in plan
        assert "TVA collectée non déclarée" in plan
        assert "(TVA, exercice 2024)" in plan
        assert "exposition : 1000000" in plan
        assert "Exposition totale : 1000000" in plan
        assert "FCFA" in plan
        assert "Motifs :" in plan
        assert "Aucun risque ouvert" not in plan
        assert "consultatif" in plan

        # 22 — bilan de pré-clôture : le risque ouvert est signalé.
        assert "22_bilan_cloture.txt" in noms
        bilan = z.read("22_bilan_cloture.txt").decode("utf-8")
        assert "BILAN DE PRÉ-CLÔTURE" in bilan
        assert "[ATTENTION] 1 risque(s) ouvert(s)" in bilan
        assert "prêt à clôturer : non" in bilan

        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "PIÈCES INCLUSES (19)" in sommaire
        # Ni temps, ni visa, ni réponse, ni paramètre de rentabilité, ni
        # compte-rendu sur cette mission → 10/11/12/16/24 omises.
        assert "PIÈCES OMISES (5)" in sommaire
        assert "14_courrier_envoi_rapport.docx" in noms
        assert "15_echeancier_fiscal.txt" in noms
        assert "17_lettre_affirmation.docx" in noms
        assert "18_prescription_risques.txt" in noms
        assert "19_civisme_fiscal.txt" in noms
        assert "20_plan_actions.txt" in noms
        assert "21_courrier_relance.txt" in noms


def test_temps_visas_reponses_inclus_quand_disponibles(session):
    """Temps saisi + visa posé + réponse client → pièces 10, 11 et 12."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    cle = f"piece:OBL-36-ETII-{suffixe}"

    saisir_temps(
        session,
        tid,
        mid,
        collaborateur="Awa Koné",
        phase="controles",
        date_jour=date(2025, 3, 10),
        heures="3.5",
        note="Revue des déductions TVA",
    )
    saisir_temps(
        session,
        tid,
        mid,
        collaborateur="Moussa Diabaté",
        phase="cadrage",
        date_jour=date(2025, 3, 8),
        heures="2",
    )
    poser_visa(
        session,
        tid,
        mid,
        phase="cadrage",
        role="preparateur",
        vise_par="Awa Koné",
        commentaire="Cadrage documenté",
    )
    enregistrer_reponse(
        session,
        tid,
        mid,
        cle_item=cle,
        contenu="État intragroupe transmis en PJ.",
        pieces_recues="etat_intragroupe_2025.pdf",
        saisie_par=email,
    )
    # Compte-rendu de réunion consigné → pièce 24 incluse.
    enregistrer_compte_rendu(
        session,
        tid,
        mid,
        date_reunion="2025-03-12",
        participants="Awa Koné (cabinet)\nM. Yao (client)",
        points_convenus="Régularisation TVA avant le 15/04.\nLettre d'affirmation à signer.",
    )
    session.commit()
    # Paramètres de rentabilité convenus → pièce 16 incluse.
    assert client.put(
        f"/api/v1/missions/{mid}/rentabilite",
        headers=h,
        json={"honoraires": 800000, "taux_horaire": 40000},
    ).status_code == 200

    resp = _telecharger_zip(client, h, mid)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "10_temps_mission.csv" in noms
        assert "11_visas_supervision.txt" in noms
        assert "12_reponses_client.txt" in noms
        assert "16_rentabilite_mission.txt" in noms

        # 10 — CSV « ; » : en-tête, entrées, synthèse (sans valorisation).
        temps = z.read("10_temps_mission.csv").decode("utf-8")
        lignes = temps.splitlines()
        assert lignes[0] == "date_jour;collaborateur;phase;heures;note"
        assert (
            "2025-03-10;Awa Koné;controles;3.5;Revue des déductions TVA"
            in lignes
        )
        assert "2025-03-08;Moussa Diabaté;cadrage;2;" in lignes
        assert "synthese;total_heures=5.5" in lignes
        assert "par_phase;controles;3.5" in lignes
        assert "par_phase;cadrage;2" in lignes
        assert "par_collaborateur;Awa Koné;3.5" in lignes
        assert "par_collaborateur;Moussa Diabaté;2" in lignes
        assert "valorisation" not in temps

        # 11 — registre des visas : visés, manquants, synthèse.
        visas = z.read("11_visas_supervision.txt").decode("utf-8")
        assert "REGISTRE DES VISAS DE SUPERVISION" in visas
        assert "PHASE CADRAGE — incomplète" in visas
        assert "[VISÉ] preparateur : Awa Koné" in visas
        assert "Cadrage documenté" in visas
        assert "[MANQUANT] reviseur" in visas
        assert "[MANQUANT] associe" in visas
        assert "PHASE COLLECTE — incomplète" in visas
        assert "Synthèse : 0 phase(s) complète(s), 1 visa(s) posé(s)." in visas

        # 12 — réponses client : contenu, pièces, saisie, statut règle.
        reponses = z.read("12_reponses_client.txt").decode("utf-8")
        assert "RÉPONSES CLIENT SAISIES" in reponses
        assert f"ITEM {cle}" in reponses
        assert "Contenu : État intragroupe transmis en PJ." in reponses
        assert "Pièces reçues : etat_intragroupe_2025.pdf" in reponses
        assert f"Saisie par : {email} le " in reponses
        assert (
            f"Statut de la règle OBL-36-ETII-{suffixe} en dernière "
            "exécution : non_verifiable" in reponses
        )

        # 16 — rentabilité : honoraires, temps valorisés, marge (Decimal).
        rentabilite = z.read("16_rentabilite_mission.txt").decode("utf-8")
        assert "RENTABILITÉ DE LA MISSION" in rentabilite
        assert "Honoraires convenus : 800000 FCFA" in rentabilite
        assert "Taux horaire        : 40000 FCFA/h" in rentabilite
        # 5.5 h × 40 000 = 220 000 ; marge 580 000 ; 72.5 %.
        assert "- controles : 3.5 h = 140000 FCFA" in rentabilite
        assert "- Awa Koné : 3.5 h = 140000 FCFA" in rentabilite
        assert "Coût total estimé : 220000 FCFA" in rentabilite
        assert "Marge estimée     : 580000 FCFA" in rentabilite
        assert "Taux de marge     : 72.5 %" in rentabilite
        assert "marge" in rentabilite

        # 22 — bilan de pré-clôture : temps saisis et visa posé en [OK].
        assert "22_bilan_cloture.txt" in noms
        bilan = z.read("22_bilan_cloture.txt").decode("utf-8")
        assert "BILAN DE PRÉ-CLÔTURE" in bilan
        assert "[OK] 5.5 h saisies" in bilan
        assert "[OK] Visas posés 1/4 phases" in bilan
        assert "[ATTENTION] Restitution non visée aux trois rangs" in bilan
        assert "Synthèse :" in bilan
        assert "Bilan consultatif" in bilan

        # 24 — compte-rendu de réunion consigné : présent, mis en forme
        # (date JJ/MM/AAAA, participants, points convenus, mention).
        assert "24_compte_rendu_reunion.txt" in noms
        cr = z.read("24_compte_rendu_reunion.txt").decode("utf-8")
        assert "COMPTE-RENDU DE LA RÉUNION DE RESTITUTION" in cr
        assert f"Mission #{mid} — réunion du 12/03/2025" in cr
        assert "PARTICIPANTS" in cr
        assert "  Awa Koné (cabinet)" in cr
        assert "  M. Yao (client)" in cr
        assert "POINTS CONVENUS" in cr
        assert "  Régularisation TVA avant le 15/04." in cr
        assert "  Lettre d'affirmation à signer." in cr
        assert (
            "Compte-rendu consigné par le fiscaliste — document "
            "consultatif : il ne constitue pas un avis fiscal." in cr
        )

        # Sommaire cohérent : 10/11/12/16/24 incluses, plus omises.
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "PIÈCES INCLUSES (22)" in sommaire
        assert "PIÈCES OMISES (2)" in sommaire
        assert (
            "24_compte_rendu_reunion.txt : Compte-rendu de la réunion de "
            "restitution (saisie du fiscaliste)" in sommaire
        )
        assert (
            "16_rentabilite_mission.txt : Rentabilité de la mission"
            in sommaire
        )
        assert "10_temps_mission.csv : Feuille de temps" in sommaire
        assert "11_visas_supervision.txt : Registre des visas" in sommaire
        assert "12_reponses_client.txt : Réponses client saisies" in sommaire
        assert (
            "13_programme_travail.txt : Programme de travail" in sommaire
        )
        assert (
            "14_courrier_envoi_rapport.docx : Courrier d'envoi du rapport"
            in sommaire
        )
        assert (
            "15_echeancier_fiscal.txt : Échéancier fiscal de l'exercice revu"
            in sommaire
        )
        assert "17_lettre_affirmation.docx" in noms
        assert (
            "17_lettre_affirmation.docx : Lettre d'affirmation de la "
            "direction (à faire signer)" in sommaire
        )


def test_piece_en_echec_est_omise_et_notee(session, monkeypatch):
    """Un rendu qui lève n'empêche jamais l'archive : pièce omise + motif."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    def _boom(*_a, **_k):
        raise RuntimeError("panne simulée du rendu Word")

    monkeypatch.setattr(archive_mission, "rendre_rapport_docx", _boom)
    resp = _telecharger_zip(client, h, mid)
    assert resp.content[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "02_rapport_restitution.docx" not in noms
        # Les autres pièces restent produites (indépendance des pièces).
        assert "03_rapport_restitution.pdf" in noms
        assert "06_suivi_circularisation.csv" in noms
        assert "14_courrier_envoi_rapport.docx" in noms
        assert "15_echeancier_fiscal.txt" in noms
        assert "17_lettre_affirmation.docx" in noms
        assert "18_prescription_risques.txt" in noms
        assert "19_civisme_fiscal.txt" in noms
        assert "20_plan_actions.txt" in noms
        assert "21_courrier_relance.txt" in noms
        assert "22_bilan_cloture.txt" in noms
        assert "23_ordre_du_jour.txt" in noms
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert (
            "02_rapport_restitution.docx : OMISE — panne simulée du rendu Word"
            in sommaire
        )
        # Panne Word + 08 (une seule exécution) + 09 (aucun risque)
        # + 10/11/12 (ni temps, ni visa, ni réponse)
        # + 16 (paramètres de rentabilité non renseignés)
        # + 24 (aucun compte-rendu de réunion consigné).
        assert "PIÈCES OMISES (8)" in sommaire


def test_dossier_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip", headers=h_b)
    assert resp.status_code == 404
    # Le tenant légitime, lui, télécharge normalement.
    assert _telecharger_zip(client, h_a, mid).status_code == 200


def test_dossier_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip")
    assert resp.status_code in (401, 403)


# ── Mise en forme pure du compte-rendu (sans DB) ─────────────────────


def test_mise_en_forme_compte_rendu_pure():
    """PUR — date JJ/MM/AAAA, sections, mention consultative."""
    texte = archive_mission.mettre_en_forme_compte_rendu(
        {
            "date_reunion": "2025-06-30",
            "participants": "Awa Koné\nM. Yao",
            "points_convenus": "Régulariser la TVA.\nSigner la lettre.",
        },
        1023,
    )
    lignes = texte.splitlines()
    assert lignes[0] == "COMPTE-RENDU DE LA RÉUNION DE RESTITUTION"
    assert lignes[1] == "Mission #1023 — réunion du 30/06/2025"
    assert "PARTICIPANTS" in lignes
    assert "  Awa Koné" in lignes
    assert "  M. Yao" in lignes
    assert "POINTS CONVENUS" in lignes
    assert "  Régulariser la TVA." in lignes
    assert "  Signer la lettre." in lignes
    assert lignes[-1] == archive_mission.MENTION_COMPTE_RENDU
    assert "consultatif" in archive_mission.MENTION_COMPTE_RENDU


def test_mise_en_forme_compte_rendu_champs_vides():
    """PUR — champs vides ou date invalide : jamais d'exception."""
    texte = archive_mission.mettre_en_forme_compte_rendu(
        {"date_reunion": "", "participants": "", "points_convenus": ""}, 7
    )
    assert "réunion du [non renseignée]" in texte
    assert texte.count("  [non renseignés]") == 2
    assert archive_mission.MENTION_COMPTE_RENDU in texte
