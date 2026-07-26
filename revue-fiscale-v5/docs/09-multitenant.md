# Multi-cabinets — isolation, éditorial, abonnements

Le document qui traduit une décision commerciale — 2AàZ édite, les cabinets s'abonnent — en
architecture.

---

## 1. Le retournement à comprendre avant tout le reste

Dans un outil interne, la promesse est : *« votre métier met à jour son référentiel en autonomie. »*

Dans un SaaS, la promesse s'inverse : *« vous n'avez plus à le faire — nous le faisons pour vous. »*

**Le référentiel fiscal maintenu centralement est le produit.** C'est ce qui justifie un abonnement
plutôt qu'un achat, c'est ce qui crée la barrière à l'entrée, et c'est ce qui fait que la veille
réglementaire par IA n'est pas un confort utilisateur mais **l'outil de production de l'éditeur**.

Corollaire économique : la charge IA la plus lourde — lire une annexe fiscale, en déduire les
règles impactées, proposer les nouvelles valeurs — est faite **une fois pour N abonnés**. Elle est
mutualisée. C'est ce qui rend tenable l'inclusion des tokens dans l'abonnement.

---

## 2. Les deux domaines de données

| | Domaine éditorial | Domaine abonné |
|---|---|---|
| Contenu | Référentiel, corpus, sanctions, versions publiées | Cabinets, missions, balances, conclusions, rapports |
| Propriétaire | 2AàZ, pour tous | Chaque cabinet, pour lui seul |
| Porte `tenant_id` | **Non** | **Oui, `NOT NULL`** |
| RLS | Non | **Oui, activée et forcée** |
| Qui écrit | Console éditoriale 2AàZ | L'application cabinet |
| Qui lit | Tout le monde | Le tenant propriétaire uniquement |

**Avant d'ajouter une table, réponds à une seule question : éditoriale ou abonné ?** La réponse
détermine `tenant_id`, RLS, et qui a le droit d'écrire.

---

## 3. L'isolation

### Le choix : base partagée, RLS PostgreSQL

Pas par économie — par sûreté opérationnelle.

Avec un schéma par cabinet, une migration sur quarante schémas qui échoue au vingt-troisième vous
laisse en état mixte, en production, un vendredi soir. Pour une équipe de cinq personnes, c'est le
scénario qui casse le produit. Une base partagée : une migration, une fois.

Et le référentiel étant central, un schéma par tenant obligerait soit à le dupliquer, soit à
maintenir quand même un schéma partagé — on retomberait sur un modèle hybride cumulant les
inconvénients des deux.

### Les six conditions

Sans elles, RLS donne un faux sentiment de sécurité, ce qui est pire que pas de sécurité du tout.

1. **`FORCE ROW LEVEL SECURITY`** en plus de `ENABLE` — sinon le propriétaire de la table
   contourne silencieusement la politique.
2. Le rôle applicatif n'est **ni superuser, ni propriétaire des tables, ni `BYPASSRLS`**.
3. **`tenant_id BIGINT NOT NULL`** sur chaque table cloisonnée.
4. **`SET LOCAL`, jamais `SET`.** Voir ci-dessous.
5. **Refus par défaut** — contexte absent = zéro ligne, jamais toutes.
6. **Test d'isolation bloquant** en intégration continue.

### Le piège n° 4, en détail

C'est la cause la plus fréquente de fuite inter-tenants en SaaS, et elle est invisible en
développement.

```python
# FAUX — la portée est la connexion
session.execute(text("SET app.tenant_id = '42'"))

# JUSTE — portée transaction (littéral)
session.execute(text("SET LOCAL app.tenant_id = '42'"))

# JUSTE — forme paramétrée : PostgreSQL refuse SET LOCAL ... = $1.
# set_config(..., is_local=true) ≡ SET LOCAL. Jamais is_local=false.
session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": "42"})
```

Avec un pool de connexions, un `SET` de session **survit à la fin de la requête**. La connexion
retourne au pool en conservant `tenant_id = 42`. La requête suivante, servant le cabinet 77,
récupère cette connexion — et si le code oublie de repositionner le contexte, elle lit les données
du cabinet 42.

En développement, avec un seul utilisateur, le bug ne se manifeste jamais.

Les politiques RLS castent via `NULLIF(current_setting('app.tenant_id', true), '')::BIGINT` :
contexte absent **ou** chaîne vide → zéro ligne, jamais une erreur de cast.

### Le contexte, en pratique

```python
from contextlib import contextmanager
from collections.abc import Iterator
from sqlalchemy import text
from sqlalchemy.orm import Session

@contextmanager
def contexte_tenant(session: Session, tenant_id: int) -> Iterator[None]:
    # set_config(..., true) ≡ SET LOCAL — portée = transaction en cours
    session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )
    yield
    # le contexte disparaît avec la transaction
```

Toute route API touchant le domaine abonné passe par ce contexte. Une route qui l'oublie doit
échouer, pas retourner des données.

**Corollaire :** un dépôt qui accède à une table cloisonnée **ne prend pas `tenant_id` en
paramètre**. C'est la base qui filtre. Si tu écris `WHERE tenant_id = ...` dans une requête
applicative, tu as mal compris le modèle : le filtre applicatif s'oublie, la politique RLS non.

### Le test qui protège

```python
def test_lecture_croisee_impossible(session, tenant_a, tenant_b):
    with contexte_tenant(session, tenant_a.id):
        missions = session.query(Mission).all()
    assert all(m.tenant_id == tenant_a.id for m in missions)

def test_sans_contexte_zero_ligne(session):
    # aucun SET LOCAL : refus par défaut
    assert session.query(Mission).count() == 0

def test_role_applicatif_sans_privileges(session):
    r = session.execute(text(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )).one()
    assert r.rolsuper is False and r.rolbypassrls is False
```

Ces trois tests sont **bloquants en intégration continue**. Pas d'exception, pas de contournement
temporaire.

### La porte de sortie commerciale

Un palier « Souverain » où un cabinet obtient une base dédiée : même code, autre chaîne de
connexion, résolue par tenant. Vous le **vendez** ; vous ne l'ingéniez pas maintenant.

---

## 4. Le circuit éditorial

Le référentiel devient un actif éditorial versionné, comme un logiciel.

```
Copilote IA          → proposition sourcée déposée en file
Fiscaliste 2AàZ      → revue : accepte, corrige, rejette
Responsable éditorial→ validation, affectation à une version
Publication          → version figée : v2026.3, publiée le 12/03/2026
Notification         → les abonnés sont informés, sans application d'office
```

### L'épinglage de version — le point critique

**Une mission épingle la version du référentiel avec laquelle elle a démarré.**

Sans cela, une mission ouverte le lundi et close le vendredi, avec une publication entre les deux,
produit deux résultats différents pour les mêmes données. La reproductibilité — qui est toute la
promesse de l'outil devant un vérificateur — disparaît.

Le cabinet voit sa version épinglée, est informé qu'une version plus récente existe, et décide
lui-même de migrer sa mission. Jamais d'office.

### Les contestations

Un cabinet ne peut pas modifier une règle. Mais il doit pouvoir dire *« je conteste celle-ci »*, avec
son argumentation, et que cela remonte à l'éditeur.

Sans ce canal, le premier désaccord de doctrine devient une demande de résiliation. Avec lui, il
devient une amélioration du produit pour tous.

```sql
CREATE TABLE contestation (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    regle_id    TEXT   NOT NULL REFERENCES regle(identifiant),
    version_ref TEXT   NOT NULL,
    motif       TEXT   NOT NULL,
    piece_jointe TEXT,
    statut      TEXT   NOT NULL DEFAULT 'ouverte',
    reponse     TEXT,
    traitee_le  TIMESTAMPTZ
);
```

---

## 5. Abonnements, quotas, métrage

### Pourquoi mesurer même quand c'est inclus

Les tokens sont inclus dans l'abonnement : coût variable, revenu fixe. Sans métrage, la dérive de
marge se découvre sur la facture du fournisseur, avec un trimestre de retard.

**Mesurer n'oblige pas à facturer.** Cela oblige à savoir.

### Les quatre garde-fous

| Garde-fou | Mise en œuvre |
|---|---|
| **Métrage par tenant** | Chaque appel enregistre tenant, modèle, tokens, coût estimé |
| **Quota par palier** | « Inclus jusqu'à N missions par mois », alerte à 80 %, blocage souple au-delà |
| **Cache mutualisé** | Le corpus est commun : même question de vingt cabinets → un seul appel |
| **Modèle proportionné** | Classer un libellé de grand livre n'appelle pas le modèle le plus cher |

### La mutualisation, chiffrée

| Usage | Qui paie la charge | Amortissement |
|---|---|---|
| Veille réglementaire, différentiel d'annexe | 2AàZ, une fois | **Sur tous les abonnés** |
| Conversion et mise à jour des règles | 2AàZ, une fois | **Sur tous les abonnés** |
| Rapprochement du plan de comptes | Par cabinet, une fois par client | Aucun |
| Lecture du grand livre | Par mission | Aucun |
| Rédaction du rapport | Par mission | Aucun |

C'est la première ligne qui coûte le plus, et c'est la seule qui soit mutualisée. Voilà pourquoi
l'inclusion des tokens dans l'abonnement est tenable — à condition que le métrage existe.

---

## 6. Provisionnement d'un cabinet

```
Souscription
   → création du tenant, du palier, des quotas
   → création du premier utilisateur administrateur
   → épinglage sur la dernière version publiée du référentiel
   → jeu de démonstration optionnel
   → invitation des autres utilisateurs
```

Objectif : **entièrement automatisé**. Un provisionnement manuel ne tient pas au-delà de dix
abonnés, et devient une source d'erreurs d'isolation.

---

## 7. Migrations

Tous les tenants sont sur la même version du schéma. Une migration ratée les casse tous ensemble.

- `up` **et** `down` obligatoires
- Testée sur un jeu représentatif — plusieurs tenants, volumétrie réaliste — avant publication
- Jamais d'altération de type en place
- Toute nouvelle table du domaine abonné crée `tenant_id`, RLS **et** sa politique **dans la même
  migration**. Une table cloisonnée sans politique est une fuite en attente.

---

## 8. Ce qui reste à décider

1. **Les paliers d'abonnement** — critère de tarification : nombre d'utilisateurs, de missions, de
   contribuables gérés ?
2. **Les quotas IA par palier** — combien de missions incluses par mois ?
3. **La politique de conservation** des données de mission après résiliation.
4. **Le délai d'engagement** sur la mise à jour du référentiel après publication d'une annexe
   fiscale — c'est une promesse contractuelle, elle doit être tenable.
5. **Le traitement des contestations** — délai de réponse, qui arbitre.
