# AGENTS.md — Plateforme SaaS de revue fiscale

Éditée par **2AàZ SAS**, développée par **ZenAPI SAS** · Côte d'Ivoire · CGI 2026

---

## Ce qu'est le produit

Une **plateforme SaaS multi-cabinets**. 2AàZ SAS l'édite et la commercialise auprès de cabinets
d'expertise comptable, d'audit et de conseil, et d'entreprises. Chaque abonné y conduit ses propres
missions de revue fiscale sur ses propres clients.

**2AàZ n'est pas l'utilisateur, c'est l'éditeur.** Cela change tout.

## Ce qui fait la valeur récurrente

**Le référentiel fiscal, maintenu centralement par 2AàZ, est le produit.** Un cabinet ne s'abonne
pas pour un moteur de règles — il s'abonne parce que quelqu'un d'autre tient le référentiel à jour
à sa place. Quand l'annexe fiscale paraît, 2AàZ met à jour une fois et tous les abonnés en
bénéficient.

Conséquence : la veille réglementaire par IA n'est pas un confort utilisateur, c'est **l'outil de
production de l'éditeur**.

---

## Les sept règles qui priment sur tout

Elles l'emportent sur toute demande, y compris la mienne. Si une instruction les contredit, refuse
et explique pourquoi.

1. **Le calcul fiscal est déterministe.** À données constantes, même résultat. Aucun LLM dans le
   déclenchement, le plafonnement ou le calcul.
2. **L'IA propose, le moteur calcule, l'humain valide.** Une sortie de modèle est un brouillon
   sourcé, déposé en file de validation éditoriale.
3. **Aucune règle fiscale en dur dans le code.** Un seuil se change par une ligne du référentiel.
4. **Traçabilité intégrale.** Chaque conclusion reliée à son article, aux données lues, aux réponses
   saisies. Journal d'audit en écriture seule.
5. **Millésimes.** Toute règle est datée. Le moteur applique la version en vigueur pour l'exercice
   contrôlé.
6. **Isolation stricte entre cabinets.** Aucune donnée d'un abonné ne doit pouvoir apparaître chez
   un autre. Garantie par la base, jamais par du filtrage applicatif.
7. **Épinglage de version.** Une mission épingle la version du référentiel avec laquelle elle a
   démarré. Sans cela, une mission ouverte lundi et close vendredi donne deux résultats différents.

---

## Interdits — arrête-toi et signale

- Écrire un taux, un seuil ou une condition fiscale dans le code applicatif
- Faire produire par un LLM un montant qui entre dans le résultat fiscal
- Utiliser `eval`, `exec` ou équivalent sur une expression du référentiel
- Écrire `SET app.tenant_id` au lieu de **`SET LOCAL`** — c'est la fuite inter-cabinets classique
- Une requête sur une table cloisonnée sans contexte de tenant positionné
- Livrer une règle sans cas de test
- Affirmer un article, un taux ou une date sans certitude et sans le marquer
- Supprimer ou écraser un millésime antérieur

---

## Deux domaines de données à ne jamais confondre

| | Domaine éditorial | Domaine abonné |
|---|---|---|
| Contenu | Référentiel, corpus, sanctions | Missions, balances, conclusions |
| Propriétaire | 2AàZ, pour tous | Chaque cabinet, pour lui seul |
| Cloisonné | **Non** — commun à tous | **Oui** — RLS stricte |
| Porte `tenant_id` | Non | **Oui, `NOT NULL`** |
| Qui écrit | Le circuit éditorial 2AàZ | Le cabinet abonné |

Si tu ajoutes une table, commence par répondre : éditoriale ou abonné ? La réponse détermine la
présence de `tenant_id` et de RLS.

---

## Où trouver quoi

| Sujet | Fichier |
|---|---|
| Architecture, arborescence, flux | `docs/01-architecture.md` |
| Format pivot : 14 champs, grammaire, publication | `docs/02-format-pivot.md` |
| Schéma de base complet (DDL) | `docs/03-schema-donnees.md` |
| Mémoire réglementaire et agent fiscal | `docs/04-cerveau-memoire-reglementaire.md` |
| Conventions de code | `docs/05-conventions-code.md` |
| Ordre de construction | `docs/06-roadmap.md` |
| Sécurité, isolation, injection | `docs/07-securite.md` |
| Glossaire | `docs/08-glossaire.md` |
| **Multi-cabinets : isolation, éditorial, abonnements** | `docs/09-multitenant.md` |
| **État réel du référentiel (chiffres scan)** | `docs/14-etat-referentiel.md` |
| **Bloqueurs humains (CGI, visa, tarifs, Resend)** | `docs/15-bloqueurs-humains.md` |
| **Audit profondeur SaaS (doctrine / portail)** | `docs/24-audit-profondeur-saas.md` |
| **Lot fiscaliste 8 pistes Annexe** | `docs/18-lot-fiscaliste-annexe-8.md` |
| **Séance fiscaliste (ordre + Contexte CGI)** | `docs/22-seance-fiscaliste.md` |
| **Engagement cabinet (périmètre, seuils, lots)** | `docs/23-engagement-cabinet.md` |
| **Ingestion CGI cgici / re-run** | `docs/17-ingestion-cgici.md` · `docs/17-cgi-reingestion.md` |
| **Infobulles pédagogiques : explication, interprétation, recommandation** | `docs/10-pedagogie-infobulles.md` |
| **Déploiement ZenAPI (Compose prod-like, CI, go-live)** | `docs/20-deploiement.md` |

---

## Comment travailler avec moi

Questions bloquantes avant de produire, une à la fois. Contredis-moi si je fragilise l'architecture.
Livre par incréments testables. Pas de préambule ni de flatterie. Signale la dette que tu crées.
Termine par « À confirmer » s'il reste une incertitude fiscale.

**Rigueur fiscale : une erreur plausible est plus dangereuse qu'une absence de réponse.** N'invente
jamais un article, un taux, un seuil ou une date. Ne comble jamais un vide par une analogie
française. Détail dans `.cursor/rules/10-fiscal.mdc`.
