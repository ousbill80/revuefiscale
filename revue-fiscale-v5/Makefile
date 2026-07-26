.PHONY: install db-up db-down migrate seed seed-pistes-annexe seed-pistes-cgi \
	seed-editorial-pistes croiser-cgi demolot demolot1 demolot234 demo-mission smoke-mission \
	purge-sessions-upload check-llm etat-referentiel inventaire-a-confirmer ingerer-corpus ingerer-cgici \
	frontend frontend-dev dev \
	test test-regles test-isolation test-expressions lint format ci clean \
	prod-up prod-down prod-logs prod-seed


PY := python3
VENV := .venv
BIN := $(VENV)/bin
MISSION_UI := frontend/mission

install:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	@echo "OK — activez avec : source $(VENV)/bin/activate"
	@echo "Frontend mission : make frontend puis make dev → http://localhost:8000/app/"

# Build React (Vite) → frontend/mission/dist — servi par FastAPI sur /app
frontend:
	cd $(MISSION_UI) && npm install && npm run build
	@echo "OK — dist pret. Relancez make dev si le serveur tournait deja (mount au demarrage)."

# Hot-reload UI seule (proxy /api → :8000). Lancer make dev en parallele.
frontend-dev:
	cd $(MISSION_UI) && npm install && npm run dev

db-up:
	docker compose up -d db
	@echo "Attente de PostgreSQL..."
	@until docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate

db-down:
	docker compose down -v

# Stack Docker prod-like (api + db). Doc : docs/20-deploiement.md
# Ne touche pas au scrape corpus — runtime uniquement.
prod-up:
	@test -f .env || (echo "Copiez .env.example → .env avant prod-up"; exit 1)
	docker compose up -d --build
	@echo "Attente health API..."
	@i=0; until curl -fsS http://localhost:$${API_HOST_PORT:-8000}/sante >/dev/null 2>&1; do \
		i=$$((i+1)); if [ $$i -gt 90 ]; then echo "API non healthy"; exit 1; fi; sleep 2; \
	done
	@curl -fsS http://localhost:$${API_HOST_PORT:-8000}/sante && echo ""
	@echo "OK — http://localhost:$${API_HOST_PORT:-8000}/app/"

prod-down:
	docker compose down

prod-logs:
	docker compose logs -f api db

prod-seed:
	docker compose --profile seed run --rm seed

migrate:
	@for f in migrations/*.sql; do \
		echo "→ $$f"; \
		docker compose exec -T db psql -U postgres -d revue_fiscale -v ON_ERROR_STOP=1 -f - < $$f; \
	done
	@echo "Migrations appliquees."

seed:
	$(BIN)/python -m backend.scripts.seed_referentiel

# 8 propositions Annexe 2026 (a_valider_humain) — n'accepte / ne purge aucun YAML.
seed-pistes-annexe:
	$(BIN)/python -m backend.scripts.seed_propositions_annexe_pistes

# Croisement CGI × a_confirmer → docs/21 + fusion catalogue (nouvelles pistes claires).
# Prérequis : corpus cgi en base (make ingerer-cgici DEPUIS_CACHE=1).
croiser-cgi:
	$(BIN)/python -m backend.scripts.croiser_cgi_a_confirmer

# Propositions CGI 2026 (a_valider_humain) — idempotent, n'accepte / ne purge aucun YAML.
# Prérequis : corpus cgi + idéalement make croiser-cgi. Rapports : docs/19 + docs/21.
seed-pistes-cgi:
	$(BIN)/python -m backend.scripts.seed_propositions_cgi_pistes

# Annexe + CGI en une cible — YAML intact (statut a_valider_humain).
seed-editorial-pistes: seed-pistes-annexe seed-pistes-cgi
	@echo "OK — seed-editorial-pistes (Annexe + CGI). Aucune acceptation / purge YAML."

# Parcours démo commercial /app — cabinet isolé + client + mission FICTIF.
# Prérequis : make seed. Credentials : CABINET_DEMO_* (.env.example). ENV=dev uniquement.
demolot:
	$(BIN)/python -m backend.scripts.demo_commercial

# Alias historique (= demolot).
demo-mission: demolot

# Parcours techniques moteur (lots) — pas le chemin commercial.
demolot1:
	$(BIN)/python -m backend.scripts.demo_parcours_lot1

demolot234:
	$(BIN)/python -m backend.scripts.demo_parcours_lot234

# Seed démo + smoke E2E API (auth → mission → balance → restitution).
smoke-mission: demolot
	$(BIN)/pytest tests/e2e/test_smoke_mission.py tests/e2e/test_demo_commercial.py -q -m db

# Purge sessions upload pièces orphelines (TTL). DRY=1 pour lister sans supprimer.
purge-sessions-upload:
	$(BIN)/python -m backend.scripts.purge_sessions_upload $(if $(DRY),--dry-run,) $(if $(TTL),--ttl-heures $(TTL),)

# Smoke auth Moonshot + DeepSeek (masque les clés). Exit 0 = les deux OK ;
# 2 = DeepSeek OK / Moonshot KO (PDF texte OK, scans non) ; 1 = rien d'authentifié.
check-llm:
	$(BIN)/python -m backend.scripts.check_llm

etat-referentiel:
	$(BIN)/python -m backend.scripts.etat_referentiel

inventaire-a-confirmer:
	$(BIN)/python -m backend.scripts.inventaire_a_confirmer

# Ingestion corpus brouillon (fragments sourcés) — ne valide aucune règle fiscale.
# Ex. : make ingerer-corpus FICHIER=corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf TYPE=annexe MILLESIME=2026
ingerer-corpus:
	@test -n "$(FICHIER)" || (echo "Usage: make ingerer-corpus FICHIER=… TYPE=cgi|annexe MILLESIME=2026"; exit 1)
	@test -n "$(TYPE)" || (echo "TYPE requis (cgi|annexe|note_dgi|doctrine|autre)"; exit 1)
	$(BIN)/python -m backend.scripts.ingerer_corpus \
		--fichier "$(FICHIER)" \
		--type "$(TYPE)" \
		$(if $(MILLESIME),--millesime $(MILLESIME),) \
		$(if $(TITRE),--titre "$(TITRE)",) \
		$(if $(DRY_RUN),--dry-run,)

# CGI+LPF depuis https://cgici.com/ (brouillon éditorial — pas un visa fiscaliste).
# Ex. : make ingerer-cgici MILLESIME=2026
#       make ingerer-cgici DRY_RUN=1
#       make ingerer-cgici DEPUIS_CACHE=1
# Workers parallèles (cache HTML seulement, puis 1× DEPUIS_CACHE=1) :
#       make ingerer-cgici CACHE_SEULEMENT=1 OFFSET=0 LIMIT=180
#       make ingerer-cgici CACHE_SEULEMENT=1 FROM_PAGE=500 TO_PAGE=973
ingerer-cgici:
	$(BIN)/python -m backend.scripts.ingerer_cgici \
		$(if $(MILLESIME),--millesime $(MILLESIME),--millesime 2026) \
		$(if $(PAUSE),--pause $(PAUSE),) \
		$(if $(MAX_PAGES),--max-pages $(MAX_PAGES),) \
		$(if $(FROM_PAGE),--from-page $(FROM_PAGE),) \
		$(if $(TO_PAGE),--to-page $(TO_PAGE),) \
		$(if $(OFFSET),--offset $(OFFSET),) \
		$(if $(LIMIT),--limit $(LIMIT),) \
		$(if $(SEULEMENT_MANQUANTES),--seulement-manquantes,) \
		$(if $(CACHE_SEULEMENT),--cache-seulement,) \
		$(if $(DEPUIS_CACHE),--depuis-cache,) \
		$(if $(DRY_RUN),--dry-run,) \
		$(if $(TITRE),--titre "$(TITRE)",)

# API :8000 — /app = React (si make frontend) sinon HTML ; /console = editorial ; /billing
dev:
	@echo "UI mission  : http://localhost:8000/app/"
	@echo "Console     : http://localhost:8000/console/  (ex-/admin)"
	@echo "Admin billing : http://localhost:8000/billing/"
	@echo "Hot-reload UI : make frontend-dev  (en parallele)"
	$(BIN)/uvicorn backend.main:app --reload --port 8000

test:
	$(BIN)/pytest -q

test-expressions:
	$(BIN)/pytest tests/referentiel -q

test-isolation:
	$(BIN)/pytest tests/isolation -q -m db

test-regles:
	$(BIN)/pytest tests/regles -q

lint:
	$(BIN)/ruff check .
	$(BIN)/mypy backend

# CI locale / GitHub Actions : lint ciblé + isolation + règles + smoke.
# Dette E501/UP017 massive hors périmètre : ignoree ici ; le nouveau code
# doit passer ruff sans ces exclusions (cible NEW_CODE ci-dessous).
NEW_CODE := backend/plateforme/rbac.py \
	backend/plateforme/email_outbox.py \
	backend/plateforme/paliers.py \
	backend/socle/routes.py \
	backend/restitution/service.py \
	backend/restitution/rapport.py \
	backend/abonne/routes.py \
	backend/abonne/service.py \
	backend/moteur/routes.py \
	backend/billing/factures.py \
	backend/billing/routes.py \
	backend/billing/config_editeur.py \
	backend/config.py \
	backend/plateforme/routes.py \
	backend/plateforme/objectifs.py \
	backend/plateforme/objectifs_fiscaux.py \
	backend/plateforme/taches.py \
	backend/plateforme/risques.py \
	backend/plateforme/actions_risque.py \
	backend/plateforme/prescription.py \
	backend/scripts/evaluer_prescription.py \
	tests/isolation/test_prescription_r5.py \
	backend/editorial/inventaire_a_confirmer.py \
	backend/editorial/pistes_annexe.py \
	backend/editorial/pistes_cgi.py \
	backend/editorial/croisement_cgi.py \
	backend/editorial/contexte_cgi.py \
	backend/editorial/acceptation_proposition.py \
	backend/editorial/routes.py \
	backend/corpus/recherche.py \
	backend/corpus/routes.py \
	backend/scripts/croiser_cgi_a_confirmer.py \
	tests/e2e \
	tests/e2e/test_demo_commercial.py \
	backend/scripts/demo_commercial.py \
	tests/isolation/test_rbac_matrice.py \
	tests/socle/test_balances_fictives.py \
	tests/billing/test_mentions_facture.py \
	tests/editorial/test_pistes_annexe.py \
	tests/editorial/test_pistes_cgi.py \
	tests/editorial/test_croisement_cgi.py \
	tests/editorial/test_contexte_cgi.py \
	tests/editorial/test_acceptation_proposition.py \
	tests/corpus/test_recherche.py \
	tests/billing/test_config_editeur.py

ci:
	@echo "=== CI : lint (nouveau code, strict) ==="
	$(BIN)/ruff check $(NEW_CODE)
	@echo "=== CI : note dette lint préexistante (E501/I001/…) hors NEW_CODE ==="
	@echo "=== CI : test-isolation ==="
	$(BIN)/pytest tests/isolation -q -m db
	@echo "=== CI : test-regles ==="
	$(BIN)/pytest tests/regles -q
	@echo "=== CI : test-editorial ==="
	$(BIN)/pytest tests/editorial -q
	@echo "=== CI : smoke-mission (API + démo commercial) ==="
	$(BIN)/pytest tests/e2e/test_smoke_mission.py tests/e2e/test_demo_commercial.py -q -m db
	@echo "CI OK."

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache
