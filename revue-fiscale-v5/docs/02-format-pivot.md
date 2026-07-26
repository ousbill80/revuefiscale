# Le format pivot

Chaque règle fiscale est décrite par quatorze champs. C'est le contrat entre le métier et le code :
une fois figé, il ne change plus sans avenant.

**En SaaS, une règle appartient à une version publiée du référentiel.** Elle porte donc, en plus
des quatorze champs, un rattachement à `version_referentiel` — et une mission épingle cette version
à son ouverture. Une règle publiée s'applique à tous les abonnés : l'erreur ne se rattrape pas
dossier par dossier.

## Les quatorze champs

| Champ | Type | Rôle |
|---|---|---|
| `identifiant` | clé unique | Convention `IMPÔT-CATÉGORIE-ARTICLE-LIBELLÉ` |
| `impot` | énumération | BIC, TVA, RAS, ITS, CE, IRC, IRVM, PAT, FONC, ENR, TIMBRE, OBL, OBNL, RA |
| `reference_legale` | structuré | Article + source + millésime, séparés |
| `date_effet` / `date_fin` | date | Sélection du millésime applicable à l'exercice |
| `profils_applicables` | expression de filtre | Attributs de profil, avec exclusions explicites |
| `comptes_declencheurs` | liste | Numéros ou préfixes SYSCOHADA, sous-comptes résolus |
| `nature` | énumération | `permanente` · `temporaire` · `sans_objet` |
| `condition_declenchement` | expression booléenne | Analysée en AST, évaluée sans exécution de code |
| `conditions_fond` | texte + critères | Les critères non lisibles deviennent des questions |
| `formule_plafonnement` | expression arithmétique | Renvoie aux agrégats normalisés |
| `questions_generees` | liste typée | Type de réponse + conditionnement = arbre de décision |
| `resultat` | expression + effet | Montant à réintégrer ou déduire, sanction rattachée |
| `niveau_risque` | énumération pondérée | `faible` · `moyen` · `eleve` |
| `effets_croises` | arêtes de graphe | Renvois vers des identifiants de règles, avec type d'effet |

## Grammaire des expressions

Liste blanche stricte. Toute construction hors de cette liste est refusée à la saisie.

```
expression   := terme (('+' | '-') terme)*
terme        := facteur (('*' | '/') facteur)*
facteur      := nombre | fonction | reference | '(' expression ')'
fonction     := 'min' '(' args ')' | 'max' '(' args ')' | 'abs' '(' expression ')'
reference    := 'solde' '(' compte ')' | 'agregat' '(' nom ')' | 'reponse' '(' id ')'
condition    := comparaison (('et' | 'ou') comparaison)*
comparaison  := expression ('>' | '>=' | '<' | '<=' | '=' | '<>') expression
               | 'non' comparaison
```

**Interdits absolus :** appel de fonction hors liste blanche, accès à un attribut, indexation,
littéral de chaîne exécutable, boucle. L'évaluateur ne fait qu'arithmétique et comparaison.

## Agrégats normalisés

Définis une fois, référencés par nom. Jamais redéfinis localement.

| Nom | Définition SYSCOHADA |
|---|---|
| `CA` | Somme des comptes 701 à 707 (poste XB) |
| `RESULTAT_AVANT_IMPOT` | Résultat net (XI) + impôt sur le résultat (RS) |
| `BENEFICE_COMPTABLE` | Poste XI |
| `FRAIS_GENERAUX` | Charges d'exploitation hors achats et hors dotations — **définition à figer** |

## Questions typées

```yaml
questions:
  - id: q1
    texte: "Le bénéficiaire est-il un organisme éligible au sens de l'article ?"
    type: booleen
  - id: q2
    texte: "Disposez-vous des reçus justificatifs ?"
    type: booleen
    conditionnee_par: "reponse(q1) = vrai"
  - id: q3
    texte: "Montant total des dons non justifiés ?"
    type: montant
    conditionnee_par: "reponse(q2) = faux"
```

Types disponibles : `booleen` · `montant` · `date` · `choix` · `texte`.
Le champ `conditionnee_par` construit l'arbre de décision.

## Effets croisés

```yaml
effets_croises:
  - cible: TVA-DED-PRORATA
    type: remet_en_cause
    commentaire: "Un don en nature peut remettre en cause la déduction de TVA d'amont"
```

Types d'effet : `declenche` · `remet_en_cause` · `alimente` · `neutralise`.
Le moteur détecte les cycles à l'exécution et interrompt la propagation en le signalant.

## Sanctions rattachées

```yaml
sanction:
  reference: LPF-XXX
  type: majoration          # amende_fixe | majoration | interet_retard
  taux: 0.10                # À CONFIRMER
  base: reintegration
```

Sans table de sanctions, on signale un risque sans pouvoir le chiffrer. C'est elle qui permet de
tenir la promesse d'un « redressement estimé et pénalités ».

## Exemple complet

Voir `.cursor/rules/90-encoder-regle.mdc` — règle `BIC-CHG-18G-DONS` avec son cas de test.
