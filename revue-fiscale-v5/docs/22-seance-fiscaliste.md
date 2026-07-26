# Séance fiscaliste — playbook console

> Accélérer la revue humaine **sans** valider à la place du fiscaliste.
> Aucune purge `a_confirmer` automatique. Aucun taux inventé.

| | |
|---|---|
| Console | `http://localhost:8000/console` |
| Compte démo | `editorial@2aaz.ci` / `EditorialDemo2026!` |
| Bandeau UI | Vue **À confirmer** → **Ordre de séance** (Annexe → CGI → Dates non prouvées → Bloqués) |
| Playbook Annexe 8 | [`docs/18-lot-fiscaliste-annexe-8.md`](18-lot-fiscaliste-annexe-8.md) |
| Rapport CGI v2 | [`docs/21-cgi-vs-a-confirmer-v2.md`](21-cgi-vs-a-confirmer-v2.md) |
| Catalogue croisement | `referentiel/croisement_cgi_2026.json` |

---

## Ordre de séance

| # | Lot | Vue console | Sens | Action typique |
|---|---|---|---|---|
| **1** | **Annexe (~8)** | À confirmer → Vue **Pistes Annexe** | Amendements Annexe 2026 sourcés | Lire extrait · Marquer en revue · **ne pas** purger dates seed sur seule Annexe |
| **2** | **CGI claires (~6–8)** | À confirmer → Vue **Pistes CGI** / **Claires CGI** | Marqueur chiffre sous article allégué | Panneau **Contexte CGI** (partagé) · `faux_amis_potentiels` si catalogue · Propositions → Accepter / Patch / Appliquer |
| **3** | **Dates non prouvées (~43 faibles)** | Vue **Dates non prouvées (faibles)** | Article présent **sans** preuve du marqueur (souvent dates `01/01/2026`) | Revue priorisée · **interdit** de promouvoir en « claire » auto |
| **4** | **Bloqués (~70)** | Vue **Bloqués CGI** | Hors périmètre / bloqueur / article absent | Noter · ticket séparé · rester bloqué si pas de fragment |

Contrastes CGI (~2) : lire raison (faux ami / alinéa) avant toute acceptation.

---

## Comment ouvrir la séance

```bash
# Prérequis corpus CGI (une fois)
make ingerer-cgici DEPUIS_CACHE=1   # ou PDF CGI si disponible

# Croisement + catalogue JSON (faibles inclus, 0 purge)
make croiser-cgi

# Seeds propositions (idempotent — n'accepte / ne purge aucun YAML)
make seed-pistes-annexe
make seed-pistes-cgi
# alias éventuel : make seed-editorial-pistes

make dev
```

1. Ouvrir **http://localhost:8000/console**
2. Connexion staff **editorial** (bouton démo si `ENV=dev` + localhost)
3. Menu **À confirmer** — bandeau **Ordre de séance** + stats secondaires repliables
4. Suivre l’ordre Annexe → CGI → Dates non prouvées → Bloqués
5. Sur chaque ligne : panneau **Contexte CGI** partagé (1–3 extraits, faux amis catalogue si présents, ou « pas de fragment CGI trouvé — reste bloqué ») + lien **Ouvrir proposition**
6. Menu **Propositions** : compteurs Annexe/CGI seedées · même panneau Contexte CGI · **Accepter** (primary) / **Patch** / **Appliquer** (disabled si non autorisé)

---

## Boutons — ce qu’ils font / ne font pas

| Bouton | Effet | YAML `a_confirmer` |
|---|---|---|
| Marquer en revue | Overlay workflow + note | **Intact** |
| Remettre en attente | Retire overlay | **Intact** |
| Accepter | `ouverte` → `acceptee` (statut seul) | **Intact** (sauf mode appliquer) |
| Patch | Télécharge `.propose.yaml` | **Intact** |
| Appliquer | 1 champ / 1 mention + backup + journal — **disabled** si non autorisé | Retrait **seulement** si `retirer_a_confirmer_autorise` **et** case cochée **et** double confirm |
| Corriger / Rejeter | Statut seul | **Intact** |

---

## Contexte CGI (API)

```
GET /api/v1/editorial/a-confirmer/contexte-cgi?entree_id=BIC-CHG-18G-DONS%230&millesime=2026&limite=3
GET /api/v1/editorial/propositions/{id}/contexte-cgi?millesime=2026
GET /api/v1/editorial/corpus/rechercher?q=art.%2018&type=cgi&millesime=2026&limite=3
```

Réponse : fragments + `classe_croisement` + `faux_amis_potentiels` (catalogue, si présents). Filtre strict `type=cgi` + `millesime=2026`. Pas de LLM. Pas de montant calculé.

---

## Interdits séance

- Purger un `a_confirmer` sans source CGI certaine + action humaine explicite
- Promouvoir un match **faible** / date non prouvée en piste claire automatiquement
- Inventer un taux / seuil / date (même « par analogie »)
- Traiter Annexe comme CGI intégral

**À confirmer** : toute lecture d’un extrait corpus comme droit positif applicable à une fiche seed reste soumise au fiscaliste 2AàZ.
