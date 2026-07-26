# CGI CI 2026 (cgici) × inventaire `a_confirmer`

> **v2** : croisement automatisé dans [`docs/21-cgi-vs-a-confirmer-v2.md`](21-cgi-vs-a-confirmer-v2.md) (claire=6, contraste=2, faible=43, bloque=70). `make croiser-cgi`.


> Rapport de croisement éditorial — **pas** une validation fiscale.
> Aucun `a_confirmer` retiré des YAML. Aucun taux / seuil / article affirmé hors citation CGI.
> Statut des propositions : **`a_valider_humain`**.

| | |
|---|---|
| Source | https://cgici.com/ `V2026` → `corpus_sources/CGI-CI-2026-cgici.txt` + HTML cache |
| Ingestion | `make ingerer-cgici` / `make ingerer-cgici DEPUIS_CACHE=1` — voir `docs/17-ingestion-cgici.md` |
| Résultat ingestion | **1** `source_document` (`id=211`, offset LPF) · **1495** articles · **3437** fragments · millésime **2026** |
| Cache | **357** pages HTTP OK · ~1,36 Mo texte · index ArticleLink ~1430 |
| Inventaire croisé | **121** mentions / **57** fiches (`referentiel/file_validation_a_confirmer.json`) |
| Généré | 2026-07-26 |

---

## Principe : CGI intégral ≠ purge automatique

Le corpus CGI+LPF **fournit le texte** pour citation et revue humaine.
Il **ne retire** aucun `a_confirmer`. Une occurrence chiffrée dans l’article allégué
est une **piste**, pas un visa.

| Besoin | Annexe 2026 | CGI cgici 2026 |
|---|---|---|
| Amendements de l’année | Oui | Complément |
| Texte **complet** art. 18 A–G, 108, 36 bis… | Non | **Oui (présent)** |
| Purge massive des 121 `a_confirmer` | Interdit | **Interdit** sans visa fiscaliste ligne à ligne |

Collision CGI/LPF : l’ingestion avec **offset LPF (+5000)** évite que l’art. 18 LPF
(contrôle) écrase l’art. 18 CGI (charges). Utiliser `source_document_id=211`.

---

## Verdict chiffré (honnête)

| Classe | Mentions (≈) | Sens |
|---|---:|---|
| **Piste CGI claire** (marqueur trouvé sous l’article allégué) | **6** | 18 G taux+seuil · 18 A 4° · 18 A 6° · 108 · 36 bis |
| **Contraste / piège de libellé** | **1** | `BIC-CHG-18A3-FRAISSIEGE` : 5 %/20 % est sous **18 A 5°**, pas 3° ; « frais de siège » **absent** du texte art. 18 |
| **Article présent, date non confirmée** | **~41** | Présence art. ≠ preuve de `01/01/2026` |
| **Hors périmètre / seed client** | **51** | Pas un lookup CGI |
| **Toujours bloqué / incomplet** | **reste** | Bloqueurs (assiette 30 %, FRAIS_GENERAUX…) · `49 ter` **absent** du découpage · notes DGI hors CGI |

**0 purge** YAML. **0** fiche certifiée supplémentaire.
Les 6 pistes claires + 1 contraste = lot seed `a_valider_humain`
(`make seed-pistes-cgi`).

---

## A. Pistes claires — `a_valider_humain`

Citations tirées de `article_corpus` **source 211** (texte CGI charges / obligations).
Découpe heuristique — vérifier sur cgici.com / PDF DGI avant visa.

### A1. `BIC-CHG-18G-DONS` — art. 18 G) dons

| | |
|---|---|
| Mentions | `BIC-CHG-18G-DONS#0` (taux) · `#1` (seuil) |
| Article DB | `18` (bloc A–G, ~22 ko) |
| Extrait | « La valeur des dons et libéralités consentis est déductible dans la double limite de **2,5 %** du chiffre d'affaires et de **200 millions** de francs par an. » (loi citée dans le HTML : 2003-206) |
| Suggestion | Croiser les paramètres seed `0.025` / `200000000` avec cette double limite. **Ne pas** purger la date `#2` sur ce seul passage. |
| Statut | `a_valider_humain` |

### A2. `BIC-CHG-18A4-ADMIN` — art. 18 A) 4°

| | |
|---|---|
| Mention | `BIC-CHG-18A4-ADMIN#1` (seuil) |
| Extrait | « Les indemnités de fonction allouées aux administrateurs […] sont déductibles dans la limite de **3 000 000** de francs par an et par bénéficiaire. » |
| Suggestion | Le plafond seed **3 000 000** apparaît sous **4°** (pas un autre alinéa). Exceptions PDG / missions : lire le reste de l’alinéa avant purge. |
| Statut | `a_valider_humain` |

### A3. `BIC-CHG-18A6-SOUSCAP` — art. 18 A) 6°

| | |
|---|---|
| Mention | `BIC-CHG-18A6-SOUSCAP#3` (taux) |
| Extrait | « le taux des intérêts servis ne peut excéder le taux moyen des avances de la **BCEAO** […] **majoré de deux points** » |
| Suggestion | La mention seed « BCEAO + 2 » a une citation. Les `#1`/`#2` (assiette 30 %, autres limites) restent **bloqueurs** — hors piste chiffrée seule. |
| Statut | `a_valider_humain` (taux seulement) |

### A4. `OBL-108-HONORAIRES` — art. 108

| | |
|---|---|
| Mention | `OBL-108-HONORAIRES#1` (seuil) |
| Extrait | « […] lorsqu'elles dépassent **50 000** francs par an pour un même bénéficiaire » ; « sommes dépassant **10000** francs par an » (droits d'auteur / inventeur, §2°) |
| Suggestion | Les deux seuils seed sont présents dans l’art. 108 CGI. La **note 002/MFB/DGI-DLCD** n’est **pas** dans ce corpus — ne pas l’inventer. |
| Statut | `a_valider_humain` · note DGI toujours à déposer si requise |

### A5. `OBL-36BIS-CBCR` — art. 36 bis

| | |
|---|---|
| Mention | `OBL-36BIS-CBCR#2` (seuil) |
| Extrait | « chiffre d'affaires hors taxes consolidé égal ou supérieur à **250 000 000 000** de francs » |
| Suggestion | Seuil **250 Md** présent. Date `#0` et valeurs client `#1` : hors confirmation par ce seul alinéa. |
| Statut | `a_valider_humain` |

---

## B. Contraste / piège — ne pas purger tel quel

### B1. `BIC-CHG-18A3-FRAISSIEGE` — libellé 3° ≠ plafond 5 %/20 %

| | |
|---|---|
| Mention | `BIC-CHG-18A3-FRAISSIEGE#2` (taux 5 %/20 %) |
| Art. 18 A) **3°** (texte) | Salaire du conjoint de l'exploitant individuel — **pas** de 5 %/20 % |
| Art. 18 A) **5°** (texte) | « La déduction est plafonnée à **5 %** du chiffre d'affaires dans la limite de **20 %** des frais généraux de l'entreprise débitrice. » (intérêts / redevances / services entre entreprises du même groupe) |
| « frais de siège » | **0** occurrence littérale dans l’art. 18 CGI indexé |
| Suggestion | Piste de **réalignement éditorial** : le plafond 5 %/20 % est sous **5°** (proche de `BIC-CHG-18A5-INTERETS`), pas sous 3°. Fiscaliste décide du renommage / fusion de fiches. **Interdit** de purger le taux 18 A 3° en affirmant qu’il « confirme » le 3°. |
| Statut | `a_valider_humain` · **contraste** |

---

## C. Toujours bloqués (sélection)

- **Dates** `01/01/2026` en masse : l’article est là ; la date d’effet seed n’est **pas** prouvée par la seule présence du texte.
- **Bloqueurs** : définition `FRAIS_GENERAUX`, assiette 30 % sous-cap, fraction 18 B 1°, etc.
- **`OBL-49TER-RBE`** : référence `49 ter` **absente** du découpage `article_corpus` (présents : `49`, `49 bis` seulement) — ne pas inventer l’article.
- **Hors périmètre** (~51) : valeurs « doc client » — validation métier, pas CGI.
- **Famille 18 B / 18 D / 18 E / 18 F** : texte présent dans le bloc art. 18, mais marqueurs seed (dates, agrégats) non traités comme pistes chiffrées ici.

---

## Propositions éditoriales (file humaine)

Seed DB (idempotent) :

```bash
make seed-pistes-cgi
```

→ propositions `ouverte` / `a_valider_humain` (source `cgi_2026_croisement`).
Catalogue : `referentiel/propositions_cgi_2026_pistes.json`.
Console : `/console` → À confirmer → Vue **Pistes CGI (~7)** ou **Pistes sourcées**.
Workflow statut ≠ purge YAML.

Ordre de séance recommandé (reprend `docs/15-session-fiscaliste-7-seuils.md`) :

1. Art. **18 G** (taux puis plafond)
2. Art. **18 A 4°** / **6°** (plafond admin / BCEAO+2)
3. Art. **108** (+ note DGI si disponible)
4. Art. **36 bis**
5. **Contraste 18 A 3° vs 5°** (frais siège / 5 %/20 %)

---

## Qualité d’ingestion (limites)

1. Découpe `Art.` heuristique — pas le décompte officiel DGI.
2. Offset LPF **obligatoire** pour croiser l’art. 18 charges (sinon collision avec LPF).
3. HTML cgici : espaces / intitulés variables ; toujours ouvrir la page source avant visa.
4. Scrape ≠ titre de propriété ni licence commerciale (voir `docs/17-ingestion-cgici.md`).

---

## Rappels d’architecture

- Domaine **éditorial** (corpus commun) — pas de `tenant_id`.
- L’IA / ce rapport **propose** ; le moteur **ne calcule** rien depuis ce texte ; l’humain **valide**.
- Épinglage de millésime inchangé.

**À confirmer** : toute lecture d’un taux, seuil ou date comme droit positif applicable à une fiche seed reste soumise au fiscaliste 2AàZ ; le contraste 18 A 3°/5° en priorité avant toute purge de `BIC-CHG-18A3-FRAISSIEGE`.
