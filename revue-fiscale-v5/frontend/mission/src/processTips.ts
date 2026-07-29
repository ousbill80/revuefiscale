/**
 * Textes d’aide process du wizard / restitution.
 * Processus plateforme uniquement — aucun article, taux ni seuil CGI.
 * Les interprétations fiscales chiffrées viennent du référentiel (contenu_pedagogique).
 */

export const PROCESS_TIPS = {
  roleAdmin:
    "Administration du cabinet : équipe, invitations, paramètres. Accès complet aux missions.",
  roleReviseur:
    "Peut créer et exécuter des missions, importer des balances. Pas de gestion d’équipe.",
  roleLecteur:
    "Consultation seule des dossiers et restitutions — aucune écriture ni exécution.",

  /* ——— Client ——— */
  portefeuille:
    "Réutilise une fiche déjà cloisonnée à votre cabinet (RLS). Aucune donnée d’un autre abonné n’est visible.",
  formePm:
    "Personne morale — identité d’entreprise. Sert au cadrage de mission, pas au calcul des montants.",
  formePp:
    "Personne physique — fiche allégée. Le profil est recopié dans la mission.",
  regime:
    "Régime déclaré du contribuable — filtre de cadrage pour le moteur. Les barèmes restent dans le référentiel épinglé, jamais dans l’écran.",
  formeJuridique:
    "Statut juridique saisi pour le dossier. N’invente aucune règle : il oriente le profil de mission.",
  ncc: "Numéro de compte contribuable DGI — en pratique le n° figurant sur la DFE. Une seule saisie suffit.",
  dfe: "La DFE est la pièce d’immatriculation. Ne resaisissez pas le NCC ici sauf référence documentaire distincte.",
  centreImpots:
    "Centre des impôts de rattachement (DFE / avis). Déterminé par le siège effectif — saisie libre, pas de liste figée non sourcée.",
  siegeEffectif:
    "Adresse réelle d’exploitation / domicile fiscal. Justificatifs usuels : bail, facture CIE ou SODECI (pièces hors formulaire).",

  /* ——— Mission ——— */
  exercice:
    "Année contrôlée. Le moteur applique le millésime du référentiel en vigueur pour cet exercice, puis l’épingle à la mission.",
  secteur:
    "Secteur d’activité du contribuable — prérempli depuis la fiche client, sans seuil codé dans l’interface.",
  typeEntite:
    "Précision de profil pour déclencher les bons contrôles du référentiel épinglé.",
  crossBorder:
    "Signale des flux internationaux. Active des contrôles du référentiel s’ils existent pour le millésime — aucun taux n’est saisi ici.",
  typeEngagement:
    "Contexte de la lettre de mission (préventive, CAC, due diligence…). Oriente libellés et rapport — n’altère aucune formule.",
  perimetreImpots:
    "Aucun coché = tous les impôts. Une sélection restreint le moteur aux codes pivot choisis (revue partielle).",
  perimetreExonerations:
    "Exonérations et allègements = règles du référentiel épinglé uniquement. Cet écran n’invente aucune liste CGI ; les mentions « à confirmer » restent à valider côté éditeur.",
  perimetreDons:
    "Dons / libéralités : si le millésime contient une règle (ex. famille BIC dons), elle s’applique à l’exécution. Aucun plafond ni taux n’est affiché dans le cadrage.",
  exclusionsDeclarees:
    "Exclusions narratives hors codes (ex. hors contrôles sur place). Figées dès le passage en cours.",
  seuilSignification:
    "Seuil de matérialité du cabinet pour cette mission (FCFA). Pas un barème CGI — vide = pas de classement auto.",
  objectifsMission:
    "Buts déclarés de la lettre de mission (plusieurs possibles). Libellés libres du cabinet — n’altèrent ni le filtre d’impôts ni les formules.",
  epingleWizard:
    "À la création, la mission épingle une version du référentiel. Les recalculs ultérieurs restent sur cette version, pour un résultat stable.",

  /* ——— Sources ——— */
  sourceActive:
    "Unique source des soldes (solde_compte). Le moteur lit ces montants de façon déterministe — pas d’IA dans le calcul.",
  annexes:
    "Pièces jointes pour la traçabilité du dossier. Elles n’alimentent pas solde_compte et n’écrasent pas la source active.",
  balanceFichier:
    "CSV / Excel / JSON de soldes SYSCOHADA. Contrôles bloquants avant calcul — une source active unique par mission.",
  referentielEpingleFlux:
    "Le millésime publié est figé à la création (ou à la première exécution). Les recalculs restent sur cette version.",
  lancerRevue:
    "Importe la source, épingle le référentiel si besoin, exécute le moteur déterministe, puis ouvre la restitution à valider.",
  quota:
    "Capacité d’abonnement du cabinet (missions incluses). Un blocage empêche une nouvelle création — pas un résultat fiscal.",

  /* ——— Résultat / restitution ——— */
  artefact:
    "Livrable de la revue : synthèse, passage comptable → fiscal, risques et rapport. L’humain valide ; le moteur a déjà calculé.",
  epingle:
    "Version du référentiel figée au démarrage de la mission. Sans épinglage, une mission ouverte plusieurs jours pourrait diverger.",
  aConfirmer:
    "Paramètre ou libellé encore marqué « à confirmer » côté éditeur 2AàZ. Ce n’est pas un blocage du moteur : signalez-le avant d’opposer le chiffre à un tiers.",
  soldeNet:
    "Réintégrations moins déductions, agrégées par le moteur. À données et version épinglée constantes, le solde est reproductible.",
  reintegration:
    "Montant à ajouter au résultat fiscal selon les conclusions du moteur. Calcul déterministe — aucune estimation par IA.",
  deduction:
    "Montant à retrancher du résultat fiscal selon les conclusions du moteur. Même traçabilité article / données / réponses.",
  passage:
    "Tableau de passage comptable → fiscal : chaque ligne cite une règle du référentiel épinglé et un sens (réintégration ou déduction).",
  exportWord:
    "Export Word du rapport moteur (données de cette mission uniquement, cloisonnées au cabinet).",
  exportPdf:
    "Export PDF du même artefact. Identique au contenu validé à l’écran pour cette exécution.",
  audit:
    "Journal en écriture seule : création, imports, exécutions, changements de statut. Complète la traçabilité, ne la remplace pas.",
  scoreRisque:
    "Indicateur de priorisation des conclusions. Aide au triage réviseur — ne modifie aucun montant moteur.",
  traitement:
    "Suivi local du cabinet (ouvert / documenté / clos). Workflow humain, hors calcul fiscal.",
  lienClient:
    "Lien magique lecture seule pour le contribuable. Isolé à cette mission — pas d’accès aux autres dossiers du cabinet.",
  rapport:
    "Artefact markdown produit par le moteur. Base du livrable Word/PDF — à relire avant transmission.",
} as const;

export type ProcessTipKey = keyof typeof PROCESS_TIPS;
