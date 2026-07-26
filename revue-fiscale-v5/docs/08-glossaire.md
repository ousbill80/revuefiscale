# Glossaire

## Fiscalité ivoirienne

| Terme | Signification |
|---|---|
| **BIC** | Bénéfices industriels et commerciaux |
| **CGI** | Code Général des Impôts |
| **Annexe fiscale** | Texte annuel qui modifie le CGI. La chaîne de modification importe autant que le texte |
| **DGI** | Direction Générale des Impôts |
| **TVA** | Taxe sur la valeur ajoutée |
| **RAS** | Retenue à la source, notamment sur sommes versées aux non-résidents |
| **ITS** | Impôt sur les traitements et salaires |
| **IRC** | Impôt sur le revenu des créances |
| **IRVM** | Impôt sur le revenu des valeurs mobilières |
| **Patente** | Contribution des patentes — impôt professionnel local |
| **ETII** | État des transactions internationales intragroupes |
| **RBE** | Registre des bénéficiaires effectifs |
| **IME** | Impôt des microentreprises (cotisation du **RME**) — DGI, art. 71 bis CGI |
| **RME** | Régime des microentreprises |
| **TEE** | Taxe d'État de l'entreprenant — art. 72 et s. CGI (branche État du **RE**) |
| **TCE** | Taxe communale de l'entreprenant (branche communale du **RE**) |
| **RE / RSI / RNI** | Régime de l'entreprenant / réel simplifié / réel normal (nomenclature DGI) |

## Social

| Terme | Signification |
|---|---|
| **CNPS** | Caisse Nationale de Prévoyance Sociale |
| **Branches CNPS** | Prestations familiales · accidents du travail et maladies professionnelles · maternité · retraite |
| **Contribution employeur** | Taxes assises sur la masse salariale à la charge de l'employeur |
| **SYCEBNL** | Référentiel comptable des entités à but non lucratif |

## Comptabilité SYSCOHADA

| Réf. | Poste |
|---|---|
| **XB** | Chiffre d'affaires |
| **XG** | Résultat des activités ordinaires |
| **XH** | Résultat hors activités ordinaires |
| **XI** | Résultat net |
| **RS** | Impôt sur le résultat |
| **AD / AI** | Immobilisations incorporelles / corporelles |
| **CP** | Capitaux propres |
| **TE, RB, RD, RF** | Variations de stocks |

Comptes usuels : `701–707` produits · `66` charges de personnel · `6582` dons et libéralités ·
`443` TVA collectée · `445` TVA déductible.

## Projet

| Terme | Signification |
|---|---|
| **Format pivot** | Structure à 14 champs décrivant une règle fiscale |
| **Millésime** | Version datée d'une règle ou d'un texte, applicable à un exercice donné |
| **Agrégat normalisé** | Grandeur comptable définie une fois et référencée par nom dans les formules |
| **Effet croisé** | Conséquence d'une règle sur une autre, modélisée comme arête d'un graphe |
| **Proposition** | Sortie d'un modèle déposée en file de validation, jamais écrite directement |
| **Ancrage** | Rattachement d'une affirmation au fragment de texte qui la fonde |
| **Abstention** | Refus de répondre faute de source. Comportement correct, pas défaut |
| **VABF / VSR** | Vérification d'aptitude au bon fonctionnement / de service régulier |
| **Tenant** | Un cabinet ou une entreprise abonnée. Unité de cloisonnement des données |
| **Domaine éditorial** | Référentiel, corpus, sanctions — commun à tous les abonnés, maintenu par 2AàZ |
| **Domaine abonné** | Missions, balances, conclusions — cloisonné par tenant |
| **Épinglage** | Une mission fige la version du référentiel avec laquelle elle a démarré |
| **Objectif de mission** | But déclaré (libellé libre) rattaché à une mission — plusieurs possibles ; hors filtre moteur |
| **Objectif fiscal** | Unité d’impôt + exercices dans le périmètre (`objectif`) — pilote la sélection de règles |
| **Tâche** | Unité d’exécution dérivée du plan déterministe ; porte le workflow réviseur |
| **Risque (registre)** | Constat engagé qui **survit à la mission**, rattaché au **contribuable** — source N+1 (R4) ; `docs/25` |
| **Prescrit (statut risque)** | Clôture par écoulement du temps — **manuel** aujourd’hui ; auto (R5) désarmé sans délai millésimé sourcé (Lot 5) |
| **Point ouvert** | Legacy inter-exercices (`017`) — déprécié après R4 ; **GET** seul (POST/PATCH = 410 → `/risques`) |
| **Action (corrective / préventive)** | Suite d’un risque ; seule la vérif cabinet clôture — `docs/25` |
| **Version de référentiel** | Publication datée et figée du référentiel — ex. `v2026.3` |
| **Contestation** | Désaccord d'un cabinet sur une règle, remonté à l'éditeur |
| **Palier** | Niveau d'abonnement, déterminant quotas et fonctionnalités |
| **Métrage** | Comptage de la consommation IA par tenant, même quand elle est incluse |

## Termes techniques

| Terme | Signification |
|---|---|
| **RAG** | Génération augmentée par récupération : répondre depuis un corpus indexé, pas depuis la mémoire du modèle |
| **Recherche hybride** | Combinaison d'une recherche lexicale et d'une recherche vectorielle |
| **Reclassement** | Second tri des candidats retrouvés, pour ne garder que les plus pertinents |
| **RLS** | Sécurité au niveau ligne PostgreSQL — le mécanisme d'isolation entre cabinets |
| **`SET LOCAL`** | Pose une variable de session **pour la transaction seulement**. `SET` seul survit au pool de connexions et provoque des fuites inter-tenants |
| **AST** | Arbre syntaxique — représentation d'une expression, évaluée sans exécution de code |
