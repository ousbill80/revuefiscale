# Session fiscaliste — 7 taux / seuils sourçables

> Préparée pour validation éditoriale 2AàZ. **Aucune purge** sans citation certaine du
> CGI CI 2026. L’annexe fiscale 2026 (LF 2025-987) **ne confirme pas** les montants
> art. 18 G (dons) — aucune occurrence « 18 G » dans le texte extractible ; le 2,5 %
> trouvé = taxe touristique ≠ dons.
>
> Inventaire source : `referentiel/INVENTAIRE_A_CONFIRMER.md` § « Taux et seuils (7) ».
> File : `GET /api/v1/editorial/a-confirmer` · `/console`.

## Corpus — éditorial ≠ runtime

| Élément | Statut |
|---|---|
| **`bloque_runtime`** | **non** — moteur / missions / démo ne s’arrêtent pas sans CGI |
| CGI CI 2026 intégral | **Absent** → `en_attente_corpus` — déposer `corpus_sources/CGI-CI-2026.pdf` (ou `.md` / `.txt`) **uniquement pour la purge** |
| Annexe fiscale 2026 | Présente (lien `corpus_sources/`) — ingestible `type=annexe`, **insuffisante** pour 18 G |
| Corpus indexé actuel | Seed **`[DÉMO FICTIF]`** + annexe éventuelle |
| Consultation publique | https://cgici.com/ (viewer HTML DGI) ; https://dgi.gouv.ci/ — pas un dépôt PDF auto |

Commande dès dépôt CGI (chemin déjà prêt) :

```bash
make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026
```

## Fiche des 7 mentions (priorité art. 18 G)

| # | Règle | Champ | Valeur actuelle `a_confirmer` | Article allégué (YAML) | Preuve requise | Statut |
|---|---|---|---|---|---|---|
| 1 | `BIC-CHG-18G-DONS` | taux | taux 2,5 % — verifier art. 18 G / annexe fiscale | CGI 2026, art. 18 G | Citation CGI CI 2026 art. 18 G (alinéa taux / % du CA) ; **pas** l’annexe seule | `en_attente_corpus` |
| 2 | `BIC-CHG-18G-DONS` | seuil | plafond 200 000 000 FCFA — verifier art. 18 G | CGI 2026, art. 18 G | Citation CGI CI 2026 art. 18 G (plafond absolu) | `en_attente_corpus` |
| 3 | `BIC-CHG-18A3-FRAISSIEGE` | taux | taux 5%/20% | CGI 2026, art. 18 A 3° | Citation CGI art. 18 A 3° (plafonds % CA / frais généraux) | `en_attente_corpus` |
| 4 | `BIC-CHG-18A6-SOUSCAP` | taux | taux BCEAO + 2 | CGI 2026, art. 18 A 6° | Citation CGI art. 18 A 6° (marge au-dessus taux BCEAO) | `en_attente_corpus` |
| 5 | `BIC-CHG-18A4-ADMIN` | seuil | plafond 3 000 000 FCFA / beneficiaire / an | CGI 2026, art. 18 A 4° | Citation CGI art. 18 A 4° (plafond indemnités) | `en_attente_corpus` |
| 6 | `OBL-108-HONORAIRES` | seuil | seuils 50 000 / 10 000 | CGI 2026, art. 108 ; note 002/MFB/DGI-DLCD | Citation CGI art. 108 **et/ou** note DGI datée (seuils déclaration) | `en_attente_corpus` |
| 7 | `OBL-36BIS-CBCR` | seuil | seuil 250 Md FCFA a confirmer | CGI 2026, art. 36 bis — CbCR | Citation CGI art. 36 bis (seuil CA consolidé CbCR) | `en_attente_corpus` |

### Ordre de séance recommandé

1. **Art. 18 G — dons** (lignes 1–2) : lire l’article intégral dans le CGI indexé
   (`rechercher_corpus` / `lire_article`), coller la citation exacte dans la proposition
   éditoriale, puis valider ou rejeter chaque `a_confirmer` (taux puis plafond).
2. Art. 18 A 3° / 4° / 6° (lignes 3–5).
3. Art. 108 + note DGI (ligne 6) — prévoir aussi le PDF/note si distinct du CGI.
4. Art. 36 bis CbCR (ligne 7).

## Circuit de purge (après preuve)

1. Proposition sourcée (citation + page / alinéa) → file éditoriale (`en_attente` → `valide`).
2. Humain 2AàZ retire la mention du YAML **uniquement** si la citation correspond.
3. **Interdit** : hardcode moteur, seed auto, analogie française, combler un vide
   « plausible ».

## Valeurs encodées aujourd’hui (non certifiées)

Rappel — présentes dans les formules YAML pour le harnais moteur, **marquées
`a_confirmer`** ; ne constituent pas du droit positif certifié :

| Règle | Expression / paramètre encodé |
|---|---|
| `BIC-CHG-18G-DONS` | `min(0.025 * agregat(CA) ; 200000000)` |
| `BIC-CHG-18A3-FRAISSIEGE` | `min(0.05 * agregat(CA) ; 0.2 * agregat(FRAIS_GENERAUX))` |
| `BIC-CHG-18A6-SOUSCAP` | mention « BCEAO + 2 » en `a_confirmer` (assiette 30 % = agrégat séparé / bloqueur) |
| `BIC-CHG-18A4-ADMIN` | `3000000 * reponse(q_nb_admin)` |
| `OBL-108-HONORAIRES` | seuils en question booléenne (pas en formule) |
| `OBL-36BIS-CBCR` | seuil en question booléenne |

---

Aucun taux, article ou date inventé dans cette fiche.
