# Infobulles pédagogiques — explication, interprétation, recommandation

Chaque indicateur, chaque widget, chaque terme technique et chaque chiffre affiché par la
plateforme porte une infobulle qui explique ce qu'il est, interprète la valeur affichée pour
**cette mission-là**, et propose une piste d'action.

---

## 1. Pourquoi c'est un choix produit, pas un ornement

**Ça abaisse le seuil de compétence requis.** Aujourd'hui, lire un taux d'impôt effectif de 11 %
et savoir que c'est anormal demande un réviseur expérimenté. Avec l'infobulle, un collaborateur de
deuxième année le voit.

Pour un SaaS vendu à des cabinets, c'est directement commercial : vos abonnés peuvent confier des
missions à des profils moins seniors. Vous ne vendez plus un outil, vous vendez **de la capacité**.

Effet secondaire non négligeable : chaque question que l'infobulle répond est une question qui
n'arrive pas au support.

---

## 2. Le principe non négociable

> **Le contenu pédagogique est une donnée du référentiel, pas du code frontend.**

Une infobulle qui dit *« un taux de vétusté supérieur à 80 % signale un sous-investissement ou des
immobilisations totalement amorties »* énonce une **règle d'analyse**. Si elle est écrite dans un
composant React, vous avez enfreint la règle n° 3 du projet : aucune règle fiscale en dur dans le
code.

Conséquences directes :

- Le contenu pédagogique est **daté et versionné** comme une règle
- Il est **publié par 2AàZ** via le circuit éditorial, pas modifié par un développeur
- Il est **épinglé** avec la mission — une mission de l'exercice 2024 affiche l'interprétation de
  2024
- Toute affirmation fiscale qu'il contient **cite son article**

Le frontend n'écrit aucun texte pédagogique. Il affiche ce que l'API lui renvoie.

---

## 3. Les trois niveaux

Toute infobulle a la même structure en trois temps. Le premier est statique, les deux autres
dépendent des données de la mission.

### Niveau 1 — Définition *(statique)*

Ce qu'est l'indicateur ou le terme, en une à trois phrases. Pas de jargon non expliqué. Rédigé
pour un collaborateur de deuxième année, pas pour un associé.

### Niveau 2 — Interprétation *(dynamique)*

Ce que **cette valeur-là** signifie. C'est le cœur de la valeur ajoutée : pas *« le taux effectif
mesure la charge d'impôt rapportée au résultat »* mais *« votre taux effectif est de 11 %, soit
14 points sous le taux normatif — l'écart est significatif »*.

L'interprétation compare la valeur observée à des **seuils déclarés dans le référentiel**, jamais
à des constantes codées.

### Niveau 3 — Recommandation *(dynamique)*

Ce qu'il y a à faire ou à vérifier. Formulée comme une **piste à instruire**, jamais comme une
conclusion.

> *« Trois causes expliquent habituellement un tel écart : des différences permanentes non
> retraitées, un report déficitaire imputé, ou un crédit d'impôt. Vérifiez d'abord le tableau de
> passage (RA-FISC-01). »*

**L'outil documente, alerte, chiffre et propose. Le réviseur valide.** Une infobulle ne dit jamais
« réintégrez 50 000 000 ». Elle dit « ce montant paraît devoir être réintégré, voici pourquoi et
voici l'article ».

---

## 4. Le modèle de données

```sql
CREATE TABLE contenu_pedagogique (
    id                     BIGSERIAL PRIMARY KEY,
    cle                    TEXT NOT NULL,          -- 'RA-CNX-02' | 'terme.difference_permanente'
    genre                  TEXT NOT NULL,          -- indicateur | terme | widget | champ
    version_referentiel_id BIGINT NOT NULL REFERENCES version_referentiel(id),
    date_effet             DATE NOT NULL,
    date_fin               DATE,

    titre                  TEXT NOT NULL,
    definition             TEXT NOT NULL,          -- niveau 1, statique
    gabarit_interpretation TEXT,                   -- niveau 2, avec variables
    gabarit_recommandation TEXT,                   -- niveau 3, avec variables

    seuils                 JSONB NOT NULL DEFAULT '[]',
    references_legales     TEXT[] NOT NULL DEFAULT '{}',
    renvois                TEXT[] NOT NULL DEFAULT '{}',   -- autres clés à consulter
    niveau_lecture         TEXT NOT NULL DEFAULT 'collaborateur',

    UNIQUE (cle, version_referentiel_id),
    CHECK (date_fin IS NULL OR date_fin > date_effet)
);
```

Table du **domaine éditorial** : commune à tous les abonnés, sans `tenant_id`, écrite par 2AàZ.

---

## 5. Les gabarits paramétrés

Un gabarit est un texte à trous, rempli par du code déterministe avec les valeurs de la mission.
Les variables disponibles sont celles du contexte d'évaluation — `solde()`, `agregat()`, le
résultat de la règle — plus les seuils déclarés.

```yaml
cle: RA-CNX-02
genre: indicateur
titre: Taux d'impôt effectif

definition: >
  Le taux effectif rapporte la charge d'impôt comptabilisée au résultat avant impôt.
  L'écart avec le taux normatif révèle l'ampleur des retraitements fiscaux — ou une anomalie.

seuils:
  - nom: ecart_faible
    condition: "abs(valeur - taux_normatif) <= 0.03"
    ton: neutre
  - nom: ecart_notable
    condition: "abs(valeur - taux_normatif) > 0.03 et abs(valeur - taux_normatif) <= 0.10"
    ton: attention
  - nom: ecart_fort
    condition: "abs(valeur - taux_normatif) > 0.10"
    ton: alerte

gabarit_interpretation:
  ecart_faible: >
    Taux effectif de {valeur:%}, proche du taux normatif de {taux_normatif:%}.
    Les retraitements fiscaux sont d'ampleur limitée sur cet exercice.
  ecart_notable: >
    Taux effectif de {valeur:%} contre {taux_normatif:%} attendu, soit un écart de
    {ecart:points}. L'écart mérite d'être expliqué par les retraitements identifiés.
  ecart_fort: >
    Taux effectif de {valeur:%} contre {taux_normatif:%} attendu, soit {ecart:points} d'écart.
    Un écart de cette ampleur est rarement dû aux seules différences permanentes.

gabarit_recommandation:
  ecart_faible: >
    Aucune vérification particulière. Confirmez que la charge d'impôt (poste RS) est
    correctement isolée.
  ecart_notable: >
    Rapprochez cet écart du tableau de passage : la somme des différences permanentes et
    temporaires doit l'expliquer. Si ce n'est pas le cas, un retraitement manque.
  ecart_fort: >
    Trois causes habituelles : différences permanentes non retraitées, report déficitaire imputé,
    ou crédit d'impôt non identifié. Commencez par RA-FISC-01, puis vérifiez l'existence d'un
    report déficitaire et du crédit d'impôt pour emploi (RA-CIE-01).

references_legales: ["CGI 2026 — taux de droit commun (À CONFIRMER)"]
renvois: ["RA-FISC-01", "RA-FISC-03", "RA-CIE-01", "terme.difference_permanente"]
```

**Les conditions de seuil utilisent la même grammaire d'expressions que les règles.** Même
analyseur, même liste blanche, même interdiction d'exécution de code. On ne crée pas un second
langage.

### Le formatage des variables

| Suffixe | Effet | Exemple |
|---|---|---|
| `{valeur}` | Montant en francs CFA, séparateur d'espace | `150 000 000` |
| `{valeur:%}` | Pourcentage à une décimale | `11,3 %` |
| `{valeur:points}` | Écart en points de pourcentage | `13,7 points` |
| `{valeur:date}` | Date au format `JJ/MM/AAAA` | `31/12/2024` |

Le formatage est fait par le serveur, pas par le frontend — pour qu'un export Word ou PDF affiche
exactement la même chose que l'écran.

---

## 6. Le rôle de l'IA — auteur, pas narrateur

Tentation à écarter : générer l'infobulle à la volée par appel au modèle.

**Non.** Trois raisons :

1. **Non déterminisme** — deux réviseurs devant le même chiffre liraient deux textes différents.
   Un rapport de mission doit être reproductible.
2. **Coût et latence** — un écran affiche vingt indicateurs. Vingt appels par écran, multipliés par
   tous les abonnés, ruinent l'inclusion des tokens dans l'abonnement.
3. **Responsabilité** — un texte généré à la volée n'a pas été relu par un fiscaliste. Il engage
   pourtant 2AàZ auprès de tous ses abonnés.

**Le bon usage :** le copilote **rédige les gabarits** en phase éditoriale, à partir du corpus et
de la règle. Le fiscaliste 2AàZ relit, corrige, valide. Le gabarit publié est ensuite rempli par
du code déterministe.

L'IA écrit une fois ce qui sera lu des milliers de fois — et ce qu'elle écrit passe par la file de
validation, comme une règle.

---

## 7. Le catalogue — ce qui doit porter une infobulle

| Genre | Exemples | Niveau 2 et 3 dynamiques ? |
|---|---|---|
| **Indicateur** | Taux effectif, taux de vétusté, prorata de TVA, variation d'effectif | Oui |
| **Montant calculé** | Réintégration, déduction, plafond, écart de concordance | Oui |
| **Résultat de règle** | Conclusion de `BIC-CHG-18G-DONS` | Oui |
| **Terme technique** | Différence permanente, fait générateur, prorata, assiette, HAO | Non — définition seule |
| **Poste SYSCOHADA** | XI, RS, XG, AD, CP | Non — définition et renvoi au poste |
| **Widget** | Tableau de passage, graphe d'effets croisés, synthèse des risques | Oui — lecture d'ensemble |
| **Champ de saisie** | Chaque question du questionnement, chaque champ de profil | Non — aide à la saisie |
| **Statut** | « À CONFIRMER », « Règle non activée », « Version épinglée » | Oui — explique l'état |

**Règle de couverture :** tout chiffre affiché sans infobulle est un défaut, au même titre qu'un
texte qui déborde. À vérifier par un test automatisé qui parcourt les écrans et signale les valeurs
non documentées.

---

## 8. Comportement d'interface

### Divulgation progressive

**Survol ou appui** → une bulle courte : titre, une phrase d'interprétation, le ton.
**Clic** → un panneau latéral : les trois niveaux complets, l'article fondateur, les renvois, et
un lien vers la règle du référentiel.

La bulle courte ne dépasse jamais deux lignes. Le panneau peut être long.

### Le ton, visible d'un coup d'œil

| Ton | Signification |
|---|---|
| **Neutre** | Valeur dans la normale, rien à instruire |
| **Attention** | Écart à expliquer, sans présomption d'anomalie |
| **Alerte** | Écart significatif, à instruire en priorité |
| **Opportunité** | Avantage fiscal potentiellement non réclamé — crédit d'impôt, exonération |

Le ton découle du seuil déclaré, jamais d'un choix du développeur. Il ne repose pas uniquement sur
la couleur : une icône et un libellé l'accompagnent.

### Mobile et tactile

**Il n'y a pas de survol sur un écran tactile.** L'indicateur porte une pastille d'information
explicitement tapable. Le panneau s'ouvre en feuille depuis le bas, pas en bulle flottante.

### Accessibilité

- Atteignable au clavier, `aria-describedby` sur l'élément documenté
- Fermeture à `Échap`, focus rendu à l'élément d'origine
- Le ton annoncé textuellement, pas seulement par la couleur
- Contraste conforme aux recommandations d'accessibilité

### Dans le rapport exporté

Les infobulles ne disparaissent pas à l'export. Les interprétations de ton **alerte** deviennent
des notes de bas de page dans le rapport de mission, avec leur article. C'est ce qui rend le
rapport lisible par le contribuable, pas seulement par le réviseur qui l'a produit.

---

## 9. Trois exemples complets

### Indicateur — taux de vétusté *(RA-IMMO-01)*

> **Taux de vétusté — 87 %**
>
> **Définition.** Rapport des amortissements cumulés aux immobilisations brutes. Il mesure le degré
> d'usure comptable de l'outil de production.
>
> **Interprétation.** À 87 %, votre parc est très largement amorti. Deux lectures : un
> sous-investissement durable, ou des immobilisations totalement amorties encore en service et
> jamais sorties du bilan.
>
> **À vérifier.** Recherchez les immobilisations à valeur nette comptable nulle encore inscrites à
> l'actif. Vérifiez le traitement fiscal des cessions de l'exercice, en particulier l'éventuel
> engagement de réinvestissement des plus-values *(RA-FISC-03)*.
>
> *Ton : attention · Sources : SYSCOHADA postes AD et AI · CGI 2026, amortissements et plus-values*

### Terme — différence permanente

> **Différence permanente**
>
> **Définition.** Écart entre le résultat comptable et le résultat fiscal qui ne se résorbera
> jamais. Une amende n'est pas déductible fiscalement et ne le sera à aucun exercice futur : c'est
> une différence permanente.
>
> À distinguer de la **différence temporaire**, qui se retourne sur un exercice ultérieur — une
> provision non déductible aujourd'hui mais déductible lors de sa reprise.
>
> **Pourquoi cela compte.** La nature détermine le traitement dans le tableau de passage et
> l'existence d'un impôt différé.
>
> *Renvois : terme.difference_temporaire · RA-FISC-01 · RA-FISC-03*

### Montant — réintégration *(BIC-CHG-18G-DONS)*

> **Réintégration — 50 000 000 F CFA**
>
> **Définition.** Fraction des dons et libéralités excédant le plafond de déductibilité, à
> réintégrer au résultat fiscal.
>
> **Interprétation.** Vous avez comptabilisé 150 000 000 au compte 6582. Le plafond applicable est
> de 100 000 000, soit 2,5 % de votre chiffre d'affaires de 4 000 000 000 — la borne absolue de
> 200 000 000 n'est pas atteinte. L'excédent de 50 000 000 n'est pas déductible.
>
> **À vérifier.** Confirmez que les bénéficiaires figurent parmi les organismes éligibles et que
> les reçus sont disponibles. À défaut, c'est la totalité des 150 000 000 qui devient non
> déductible, et non le seul excédent.
>
> **Effet croisé.** Un don en nature peut remettre en cause la déduction de TVA d'amont
> *(TVA-DED-PRORATA)*.
>
> *Ton : alerte · Source : CGI 2026, art. 18 G (taux et plafond À CONFIRMER)*

---

## 10. Ce qu'une infobulle ne fait jamais

- **Affirmer une conclusion fiscale définitive.** Elle propose, le réviseur tranche.
- **Contenir un taux ou un seuil en dur.** Tout vient du référentiel.
- **Être générée à la volée par un modèle de langage.** Gabarits validés, remplis par du code.
- **Citer un article sans le dater.** Un article de 2023 n'est pas celui de 2026.
- **Afficher une donnée d'un autre cabinet.** Elle passe par le même cloisonnement que le reste.
- **Masquer une incertitude.** Si le seuil est marqué `À CONFIRMER`, l'infobulle le dit.
- **Remplacer la traçabilité.** Elle complète le renvoi à l'article, elle ne s'y substitue pas.

---

## 11. Mise en œuvre

| Étape roadmap | Ce qui s'ajoute |
|---|---|
| **3 — Référentiel** | Table `contenu_pedagogique`, saisie dans la console éditoriale, validation des conditions de seuil par l'analyseur existant |
| **4 — Moteur** | Résolution des seuils et remplissage des gabarits, dans le même passage que le calcul |
| **6 — Restitution** | Composant d'infobulle, panneau latéral, notes de bas de page à l'export |
| **9 — Agent** | Rédaction assistée des gabarits en phase éditoriale, avec citation |

**Ordre recommandé :** commencer par les termes techniques, qui n'ont qu'un niveau statique et se
rédigent vite. Puis les indicateurs de la revue analytique, qui ont déjà des seuils identifiés dans
le référentiel. Les résultats de règles en dernier, parce qu'ils dépendent du moteur.

**Charge métier à prévoir :** environ 60 à 80 entrées pour une couverture correcte — les 57 règles,
une vingtaine de termes, une dizaine d'indicateurs et de widgets. C'est un livrable éditorial de
2AàZ, comparable à la purge des `À CONFIRMER` en volume.

---

## 12. Ce qui reste à décider

1. **Le niveau de lecture cible** — collaborateur de deuxième année, ou chef de mission ? Cela
   change tout le registre de rédaction. Un champ `niveau_lecture` est prévu si vous voulez servir
   les deux.
2. **Les seuils** — qui les fixe, sur quelle base ? Le taux de vétusté à 80 % est un usage
   professionnel, pas une norme. Il doit être assumé et documenté comme tel.
3. **La langue** — français uniquement, ou anglais pour les groupes internationaux ?
4. **La couverture minimale** exigée avant mise en service. Nous recommandons : 100 % des termes
   techniques et des indicateurs, 100 % des règles de niveau de risque élevé.
