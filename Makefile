# file-sorter tasks (RUN-001.3). Every build, test and run goes through Docker (CLAUDE.md).
# Recipes run in Git Bash on Windows (DOC-003.D4, DOC-003.D11).
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose
# RUN-002.D2: a linked worktree tests in its own compose project, so parallel runs never share db-test.
WT_NAME := $(shell git rev-parse --git-dir 2>/dev/null | grep -q '/worktrees/' && basename "$$(git rev-parse --show-toplevel)" | tr 'A-Z.' 'a-z-' | tr -cd 'a-z0-9_-')
# RUN-009.D1: ...and mounts the main checkout's git-ignored fixtures/images/, read-only.
MAIN_CHECKOUT := $(shell dirname "$$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")
TEST := $(if $(WT_NAME),FIXTURE_IMAGES="$(MAIN_CHECKOUT)/fixtures/images" )$(COMPOSE) $(if $(WT_NAME),-p file-sorter-$(WT_NAME)) --profile test run --rm test
# RUN-011.D1: Ollama for the gpu tier and the gates only, in the same compose project.
OLLAMA_UP := $(COMPOSE) $(if $(WT_NAME),-p file-sorter-$(WT_NAME)) up -d ollama
RUFF := MSYS_NO_PATHCONV=1 docker run --rm -v "$(CURDIR):/io" -w /io ghcr.io/astral-sh/ruff:0.16.10
OLLAMA_MODELS := qwen3-vl:8b bge-m3   # the adult VLM is not pulled until Q-1 is decided (M5)

.PHONY: help init prune-test up down ps logs build models test test-gpu lint format

help: ## List the targets
	@grep -E '^[a-zA-Z0-9_%-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 14

init: ## Create .env and sanitize.yaml from the examples, generate secrets, enable git hooks
	@bash scripts/init_local_files.sh
	@grep -q '^DB_PASSWORD=.' .env || echo "DB_PASSWORD=$$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env
	@grep -q '^SEARXNG_SECRET=.' .env || echo "SEARXNG_SECRET=$$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env
	@grep -q '^SANITIZE_LOG_KEY=.' .env || echo "SANITIZE_LOG_KEY=$$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env   # SAN-001.D5
	@git config core.hooksPath .githooks
	@for v in file-sorter_ollama file-sorter_hf; do docker volume inspect "$$v" >/dev/null 2>&1 || docker volume create "$$v" >/dev/null; done   # RUN-005.D2
	@bash scripts/prune_test_projects.sh   # RUN-010.D5
	@echo "init done"

prune-test: ## Shut down the test projects of worktrees that no longer exist (RUN-010.D5)
	@bash scripts/prune_test_projects.sh

build: ## Build the app/test image
	$(COMPOSE) build app

up: ## Start db, ollama, searxng and app
	$(COMPOSE) up -d db ollama searxng app

down: ## Stop everything (volumes are kept)
	$(COMPOSE) --profile test --profile tools down

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Follow logs (S=<service> to pick one)
	$(COMPOSE) logs -f $(S)

models: ## Pull the Ollama tags and HF weights into volumes (~11 GB)
	$(COMPOSE) up -d ollama
	for m in $(OLLAMA_MODELS); do $(COMPOSE) exec -T ollama ollama pull "$$m"; done
	$(COMPOSE) --profile tools run --rm fetch

test: ## unit + db + integration tiers (CLAUDE.md §3)
	$(TEST)

test-gpu: ## gpu tier: real SigLIP, NSFW and Ollama (starts ollama, RUN-011)
	@$(OLLAMA_UP) >/dev/null 2>&1 || true   # RUN-013.D2: the tests then fail naming it
	$(TEST) pytest -m gpu

lint: ## ruff check + format check (container, nothing installed on the host)
	$(RUFF) check .
	$(RUFF) format --check .

format: ## ruff format in place
	$(RUFF) format .

gate-%: ## Milestone gate N, e.g. make gate-3 (starts ollama, RUN-011)
	@$(OLLAMA_UP) >/dev/null 2>&1 || true   # RUN-013.D2: the tests then fail naming it
	$(TEST) python scripts/gate_$*.py
