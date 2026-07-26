# Sécurité et confidentialité

Plateforme SaaS traitant, pour le compte de plusieurs cabinets, les données comptables et sociales
de leurs propres clients. Deux niveaux de confidentialité imbriqués.

---

## Le risque n° 1 : la fuite inter-cabinets

Ce n'est plus « une erreur fiscale » mais « le cabinet A voit les dossiers du cabinet B ». C'est
l'incident qui tue un produit SaaS : irréversible, public, et fatal commercialement.

### Le modèle : base partagée + RLS PostgreSQL

Tables **éditoriales** (référentiel, corpus, sanctions) : communes, sans `tenant_id`.
Tables **abonné** (missions, balances, conclusions) : `tenant_id NOT NULL`, RLS activée **et forcée**.

### Les six conditions

1. `FORCE ROW LEVEL SECURITY` en plus de `ENABLE` — sinon le propriétaire contourne la politique
2. Rôle applicatif ni superuser, ni propriétaire, ni `BYPASSRLS`
3. `tenant_id BIGINT NOT NULL` sur chaque table cloisonnée
4. **`SET LOCAL`, jamais `SET`**
5. Refus par défaut — contexte absent = zéro ligne
6. Test d'isolation bloquant en intégration continue

### Le piège n° 4

```python
session.execute(text("SET app.tenant_id = '42'"))        # FAUX — portée connexion
session.execute(text("SET LOCAL app.tenant_id = '42'"))  # JUSTE — portée transaction
# Forme paramétrée (SET LOCAL refuse $1) — is_local=true obligatoire :
session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": "42"})
```

Avec un pool de connexions, un `SET` survit à la requête. La connexion recyclée sert le cabinet
suivant avec le contexte du précédent. **En développement, avec un seul utilisateur, ce bug ne se
manifeste jamais.**

### Les tests bloquants

- Lecture avec le contexte de A → ne voit que A
- Lecture sans contexte → **zéro ligne**, jamais toutes
- Écriture d'une ligne portant le `tenant_id` d'un autre → refusée
- Le rôle applicatif n'a ni `BYPASSRLS` ni la propriété des tables

Ces tests échouent → le déploiement s'arrête.

---

## Socle

- Chiffrement AES-256 au repos, TLS 1.3 en transit. Sans exception.
- Authentification forte, gestion centralisée des identités, expiration et révocation de session.
- Rôles par tenant : administrateur, réviseur, lecteur. Les rôles éditoriaux 2AàZ sont séparés et
  ne donnent **aucun** accès aux données de mission des abonnés.
- Sauvegardes chiffrées quotidiennes, restauration testée trimestriellement.

## Séparation des consoles

Trois surfaces (voir `docs/11-saas-surfaces.md`) :

| Surface | URL | Public |
|---|---|---|
| Espace abonné | `/app` | Cabinets / entreprises |
| Console éditoriale | `/console` (ex-`/admin`) | Staff 2AàZ — référentiel |
| Admin billing | `/billing` | Staff propriétaire — abonnés, paliers |

Ce sont des applications distinctes. Un écran éditorial ou billing ne doit jamais être
atteignable depuis l'application cabinet, ni l'inverse.

**Un administrateur 2AàZ (billing ou editorial) ne lit pas les missions d'un abonné.** L'accès à
des données de mission, en cas de support, exige un consentement explicite du cabinet, limité
dans le temps et journalisé. Le billing ne lit que `tenant` / `abonnement` / `quota`.

---

## Injection par document

La plateforme ingère des documents qu'elle ne contrôle pas : balances, pièces scannées, sorties
d'OCR, textes réglementaires, libellés de grand livre.

**Un document ingéré est une donnée, jamais une instruction.**

- Contenu ingéré passé au modèle dans un bloc explicitement marqué non fiable
- Un fragment ressemblant à une consigne est ignoré et signalé
- Aucun contenu ingéré ne peut déclencher un appel d'outil
- Vaut aussi pour les libellés d'écritures : du texte à classer, pas une commande

---

## Données et modèles

- **Pseudonymisation en amont** de tout appel : dénomination, NCC, RCCM, identifiants de personnes,
  matricules.
- **Aucune donnée de mission ne sert à entraîner un modèle.** À exiger contractuellement du
  fournisseur, et à répercuter dans les conditions d'abonnement.
- **Aucune donnée réelle dans une conversation de développement.** Jeux anonymisés uniquement.
- Le **cache mutualisé** ne porte que sur des questions relatives au **corpus réglementaire**, jamais
  sur des données de mission. Une réponse mise en cache ne doit jamais contenir de donnée d'abonné.

## Options de déploiement du modèle

| | Description | Pour | Contre |
|---|---|---|---|
| **A** | Interface commerciale, contrat à rétention nulle | Qualité, coût maîtrisé | Données hors du SI |
| **B** | Modèle à poids ouverts auto-hébergé | Souveraineté totale | Coût, qualité en retrait |
| **C** | Hybride : pseudonymisation puis interface commerciale | Qualité de A, exposition réduite | Une étape de plus |

**Recommandé : C.** L'architecture reste agnostique — bascule vers B sans redéveloppement.

---

## Journal d'audit

Écriture seule, chaînage cryptographique, cloisonné par tenant. `UPDATE` et `DELETE` révoqués pour
le rôle applicatif au niveau PostgreSQL, pas seulement par convention.

Journalisé : réponses saisies, conclusions, amendements du réviseur, appels au modèle avec version
et instructions, validations éditoriales, publications de version, accès de support.

## Conservation et réversibilité

À la résiliation d'un abonnement : export intégral des données du cabinet dans un format ouvert,
puis suppression selon la politique convenue. Le cabinet reste propriétaire de ses données de
mission ; 2AàZ reste propriétaire du référentiel.
