# Conventions de code

## Langue

Code, noms de tables et de colonnes, messages d'erreur : **français**, parce que le domaine est
français et que les experts métier relisent. Commentaires en français. Bibliothèques et frameworks
gardent leurs noms d'origine.

## Nommage

| Élément | Convention | Exemple |
|---|---|---|
| Module Python | `snake_case` | `declenchement.py` |
| Classe | `PascalCase` | `EvaluateurExpression` |
| Fonction, variable | `snake_case` | `calculer_plafond()` |
| Constante | `MAJUSCULES` | `AGREGATS_NORMALISES` |
| Table, colonne | `snake_case` singulier | `regle_version`, `date_effet` |
| Identifiant de règle | `IMPÔT-CAT-ART-LIBELLÉ` | `BIC-CHG-18G-DONS` |
| Composant React | `PascalCase` | `TableauPassage.tsx` |

## Structure d'un module de couche

```
backend/<couche>/
  __init__.py       exporte l'interface publique, rien d'autre
  modeles.py        entités et schémas Pydantic
  service.py        logique métier
  depot.py          accès base
  erreurs.py        exceptions nommées de la couche
  tests/
```

Une couche n'importe **jamais** directement le dépôt d'une autre couche : elle passe par son
service. Le moteur n'importe rien de `agent/` ni de `corpus/` — cette dépendance est interdite et
doit être vérifiée par un test d'architecture.

## Contexte de tenant — la convention qui évite l'incident

Toute route touchant le domaine abonné ouvre une transaction et pose le contexte via
**`set_config('app.tenant_id', …, true)`** (équivalent `SET LOCAL`). Jamais `SET` ni
`set_config(..., false)` : avec un pool de connexions, un GUC de session survit à la
transaction et sert le cabinet suivant avec le mauvais contexte. PostgreSQL refuse les
paramètres liés sur `SET LOCAL … = :t` — d'où `set_config`.

Un dépôt qui accède à une table cloisonnée **ne prend pas `tenant_id` en paramètre** — c'est la
base qui filtre. Si tu écris `WHERE tenant_id = ...` dans une requête applicative, tu as mal
compris le modèle : le filtre applicatif s'oublie, la politique RLS non.

## Erreurs

```python
class ErreurMoteur(Exception):
    # Base des erreurs du moteur d'analyse.
    pass

class CompteAbsent(ErreurMoteur):
    def __init__(self, compte: str, mission_id: int) -> None:
        super().__init__(f"Compte {compte} absent de la mission {mission_id}")
```

Jamais de valeur par défaut silencieuse sur un calcul fiscal. Une donnée manquante est une erreur
explicite qui remonte à l'utilisateur, pas un zéro.

## Journalisation

Logger structuré, en JSON. Chaque entrée porte `mission_id`, `execution_id` et `regle_id` quand ils
existent. **Jamais de donnée identifiante de contribuable dans un log** — utilise l'identifiant
interne.

## Montants

`NUMERIC(18,2)` en base, `Decimal` en Python. **Jamais de `float` sur un montant fiscal.** Arrondi
au franc CFA, mode d'arrondi explicite et documenté par règle.

## Dates

`DATE` en base, `datetime.date` en Python, ISO `AAAA-MM-JJ` dans les API, `JJ/MM/AAAA` à l'affichage.
Les périodes sont toujours `[date_effet, date_fin)` — borne de fin exclue.

## Commits

```
<couche>: <ce que ça change>

moteur: detection de cycle dans la propagation des effets croises
referentiel: contrainte de coherence sur les millesimes
corpus: decoupage par alinea avec entete repete
```

Un commit qui touche à la fois le moteur et l'agent est probablement mal découpé.

## Revue — ce qu'on refuse

- Un taux ou un seuil fiscal dans un fichier de code
- Un appel LLM sous `backend/moteur/`
- Une règle sans cas de test
- Une migration sans `down`
- Un `except` nu ou un `float` sur un montant
- Une requête en boucle sur une collection
- `SET` au lieu de `SET LOCAL` pour le contexte de tenant
- Une table du domaine abonné sans `tenant_id NOT NULL` ni politique RLS dans la même migration
