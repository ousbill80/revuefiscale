# Procès-verbal fondations (étape 0) — provisoire technique

Document de décisions pour débloquer le code. Toute ligne marquée
**À CONFIRMER** doit être validée par 2AàZ / fiscaliste avant production.

Date scaffold : 2026-07-25 · Éditeur : 2AàZ SAS · Dev : ZenAPI SAS

---

## 1. Corpus réglementaire

| Source | Statut numérique | Action |
|---|---|---|
| Annexe fiscale 2026 (PDF fourni au dépôt) | Présent en PDF | Vérifier extractibilité texte vs scan — **À CONFIRMER** |
| CGI 2026 | Non ingéré en base | Ingestion étape 7 |
| Code minier / pétrolier (PDF dépôt) | Hors cœur CGI | Hors périmètre Porte 1 |
| Notes DGI | Non fournies | **À CONFIRMER** disponibilité |

**Décision provisoire :** Porte 1 (mission) avance sans corpus indexé.
Porte 2 (agent) **bloquée** tant que le CGI n’est pas extractible article par article.

---

## 2. Format pivot

Les 14 champs de `docs/02-format-pivot.md` sont **figés** pour le code.
Toute évolution = avenant + migration `regle_version`.

Grammaire d’expressions : liste blanche existante (`analyseur.py`) — figée.

## 3. Agrégats normalisés

| Agrégat | Définition provisoire | Statut |
|---|---|---|
| `CA` | Somme soldes comptes 701–707 | Aligné doc pivot |
| `BENEFICE_COMPTABLE` | Poste XI / compte résultat selon mapping | **À CONFIRMER** mapping exact |
| `RESULTAT_AVANT_IMPOT` | Bénéfice + IS si présent | **À CONFIRMER** |
| `FRAIS_GENERAUX` | Charges 60–65 hors achats/dotations (hypothèse) | **À CONFIRMER** — critique |

## 4. Paliers et quotas (techniques)

| Palier | Missions / mois | Statut |
|---|---|---|
| essentiel | 5 | **À CONFIRMER** commercialement |
| standard | 20 | **À CONFIRMER** |
| premium | 100 | **À CONFIRMER** |
| souverain | 10 000 (base dédiée plus tard) | **À CONFIRMER** |

Quotas tokens IA : non facturés en Porte 1 ; métrage activé dès B9.

## 5. Jeux de données anonymisés

| Jeu | Statut |
|---|---|
| Balance SYSCOHADA anonymisée #1 | **MANQUANT** — bloquant qualité étape 5 |
| Balance #2 / #3 | **MANQUANT** |
| Plan de comptes de référence | Mapping identité provisoire dans `socle/mapping.py` |

**Décision provisoire :** tests unitaires sur balances synthétiques ;
remplacer dès réception des jeux clients.

## 6. Mentions « À CONFIRMER » référentiel

La règle `BIC-CHG-18G-DONS` porte encore des `a_confirmer` (taux, plafond, date).
Les 56 autres emplacements du harnais sont des **enveloppes non sourcées**
(`EMPLACEMENT-XXX`) destinées à être remplacées par le fiscaliste — jamais
présentées comme droit positif ivoirien.

---

## Signature

| Rôle | Nom | Date | Visa |
|---|---|---|---|
| Éditeur 2AàZ | | | En attente |
| Fiscaliste | | | En attente |
| Tech ZenAPI | scaffold auto | 2026-07-25 | Provisoire |
