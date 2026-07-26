# Ordre de construction

Séquence de dépendances, pas un planning.

---

## Avertissement sur le calendrier

Le périmètre — plateforme SaaS multi-cabinets, six couches, quatorze domaines fiscaux, corpus
indexé, agent outillé, circuit éditorial, harnais d'évaluation — **n'est pas livrable en trois mois
par cinq personnes** sans arbitrage. Trois options, à trancher explicitement avec le client plutôt
qu'à découvrir au deuxième mois :

1. **Étaler** — allonger le délai.
2. **Couper** — livrer les étapes 0 à 6 et reporter la couche d'intelligence.
3. **Assumer** — accepter un risque qualité, en le documentant.

Le passage en SaaS multi-cabinets **ajoute** du travail par rapport à un outil interne :
provisionnement, isolation, quotas, métrage, circuit éditorial, deux frontends.

---

## Étape 0 — Fondations *(bloquant)*

- [x] **Vérifier la disponibilité du corpus.** PV provisoire : `docs/00-fondations-pv.md`
      (extractibilité CGI **À CONFIRMER** métier)
- [ ] Purger les **71 mentions « À CONFIRMER »** recensées dans les cinq référentiels
- [x] Figer le format pivot : schéma, grammaire d'expressions, modèle de millésimes
- [x] Figer les agrégats normalisés, en particulier `FRAIS_GENERAUX` *(hypothèse provisoire
      **À CONFIRMER**)*
- [x] Définir les **paliers d'abonnement** et les quotas associés *(bornes techniques
      **À CONFIRMER** commercialement)*
- [ ] Obtenir un plan de comptes de référence et sa correspondance SYSCOHADA
- [ ] Obtenir deux à trois jeux de données réels anonymisés

**Sortie :** format pivot validé par procès-verbal, paliers arrêtés.

## Étape 1 — Socle multi-cabinets *(avant tout le reste — on ne rétrofitte pas l'isolation)*

- [x] Tables `tenant`, `utilisateur`, `quota`
- [x] Politiques RLS **activées et forcées**, rôle applicatif sans privilèges
- [x] `contexte_tenant()` avec `SET LOCAL` / `set_config(..., true)`, point de passage obligé
- [x] Provisionnement automatisé d'un cabinet
- [x] **`tests/isolation/` au vert et bloquant en CI**

**Sortie :** deux cabinets coexistent, aucune fuite possible, prouvé par test.

## Étape 2 — Socle de données

- [x] Lecteurs balance, états financiers, grand livre, FEC *(déclarations : extension)*
- [x] Mapping configurable vers le plan de comptes
- [x] Contrôles d'équilibre, de concordance, de complétude — bloquants
- [x] Rapport de fiabilisation horodaté

## Étape 3 — Référentiel et console éditoriale

- [x] Modèle : règles, versions, sanctions, effets croisés
- [x] Analyseur d'expressions et évaluateur — **sans `eval`**
- [x] Validation de syntaxe à la saisie
- [x] Versions de référentiel, publication, notification
- [x] Console éditoriale 2AàZ *(frontend/admin servi sur `/console`)*
- [x] Admin billing MVP *(auth staff, CRUD abonnés, `/billing`)*
- [x] Surfaces SaaS documentées — `docs/11-saas-surfaces.md`
- [x] **S2–S6** : quotas enforced, espace abonné, console auth staff, factures,
      portail client (`/client`), layout full-page finance
- [x] **S7** : durcissement — auth agent/usages, empty state client, PDF facture,
      jeton invitation copiable (`docs/13-s7-durcissement.md`)

**Sortie :** un fiscaliste 2AàZ crée une règle et publie une version, seul.

## Étape 4 — Moteur

- [x] Sélection sur **version épinglée**, déclenchement, questionnement, calcul, propagation
- [x] Détection de cycle dans le graphe d'effets croisés
- [x] Journal d'audit chaîné, en écriture seule
- [x] **Test du principe directeur** — modifier un seuil en console, sans recompilation
- [x] **Test d'épinglage** — une mission épinglée sur N donne le même résultat après publication de N+1

## Étape 5 — Chargement des règles

- [x] 33 règles BIC et revue analytique, avec cas de test *(1 règle métier + enveloppes
      EMPLACEMENT non sourcées — à remplacer par le fiscaliste)*
- [x] 24 règles des autres domaines, avec cas de test *(idem enveloppes)*
- [x] `make test-regles` au vert sur les 57

## Étape 6 — Restitution

- [x] Passage comptable / fiscal
- [x] Notation et chiffrage via la table de sanctions *(score heuristique documenté ;
      sanctions CGI non inventées)*
- [x] Rapport de mission, exports Word et PDF depuis gabarits modifiables *(markdown livré ;
      Word/PDF : extension)*
- [x] Consultation du journal d'audit

**Sortie :** une mission complète, de l'import au rapport, dans un cabinet abonné.

## Étape 7 — Corpus

- [x] Ingestion, découpage **par article**, métadonnées, versionnement temporel
- [x] Index lexical et vectoriel *(lexical livré ; vectoriel : extension)*
- [x] Recherche hybride : filtre, double recherche, reclassement

**Sortie :** on retrouve le texte de l'art. 18 G applicable à l'exercice 2024.
*(Démo FICTIF uniquement tant que CGI non ingéré.)*

## Étape 8 — Évaluation *(avant l'agent)*

- [x] Jeu de 50 à 100 cas écrits par le fiscaliste 2AàZ, dont 20 pièges *(22 cas démo ;
      à enrichir par fiscaliste)*
- [x] Métriques : récupération, citation, abstention, invention
- [x] Intégration CI avec blocage sur régression

## Étape 9 — Agent

- [x] Deux outils d'abord : `rechercher_corpus`, `lire_article`
- [x] Citation obligatoire, vérification d'ancrage
- [x] Puis `simuler_regle`, `impact_texte`, `proposer_regle`
- [x] File éditoriale et interface de validation
- [x] **Métrage par tenant et cache mutualisé** *(métrage livré ; cache : extension)*

**Sortie :** taux d'invention à zéro sur le jeu de référence.

## Étape 10 — Cas d'usage

- [x] Veille réglementaire et différentiel d'annexe *(usage éditorial, mutualisé — priorité)*
- [x] Conversion assistée d'une règle *(usage éditorial)*
- [ ] Rapprochement de plan de comptes et lecture du grand livre *(usage cabinet)*
- [ ] Rédaction assistée du rapport *(usage cabinet)*

Chacun mesuré sur son propre sous-jeu d'évaluation.

---

## Les deux erreurs à ne pas commettre

**Rétrofitter l'isolation.** Ajouter le multi-tenant après coup oblige à reprendre chaque requête,
chaque route et chaque migration. C'est l'étape 1, pas l'étape 8.

**Commencer par l'agent.** On obtient une démonstration séduisante en trois jours, puis six semaines
à chasser des hallucinations qu'on ne sait pas mesurer.
