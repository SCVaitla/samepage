# SamePage — every command a judge or teammate needs. Run `make help`.
.DEFAULT_GOAL := help
UV ?= uv

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install deps (locked), git hooks, and create .env from the example
	$(UV) sync --frozen
	$(UV) run pre-commit install || true
	@test -f .env || (cp .env.example .env && echo "Created .env; fill in the Switch and GitHub values.")

up: ## Run the engine API in Docker (http://localhost:8080/healthz)
	docker compose up --build -d engine
	@echo "Engine: http://localhost:8080/healthz"

arbiter: ## Join Switch as the SamePage Arbiter (needs .env filled in)
	$(UV) run samepage arbiter

seed: ## Show what the engine sees in the docs corpus (sources, owners, ignored lines)
	$(UV) run samepage check-corpus

lint: ## ruff lint + format check + mypy --strict
	$(UV) run ruff check samepage tests
	$(UV) run ruff format --check samepage tests
	$(UV) run mypy samepage

test: ## Unit, property and integration tests with coverage (no live services)
	$(UV) run pytest --cov=samepage --cov-report=term-missing

security: ## bandit + pip-audit (gitleaks runs in CI and pre-commit)
	$(UV) run bandit -q -r samepage -c pyproject.toml
	$(UV) export --frozen --no-dev --no-hashes --no-emit-project -o .audit-requirements.txt -q
	$(UV) run pip-audit -r .audit-requirements.txt --strict; status=$$?; rm -f .audit-requirements.txt; exit $$status

check: lint test security ## Everything CI runs

eval: ## Score the latest recorded patrol (reports/answers-*.jsonl) + question matching
	$(UV) run samepage eval

eval-holdout: ## Score held-out case H1 (record it first: see docs/RUNBOOK.md)
	$(UV) run samepage eval --holdout

demo-reset: ## Copy the drifted corpus into your docs clone (DOCS=path), ready to commit and push
	@test -n "$(DOCS)" || (echo "usage: make demo-reset DOCS=~/juniper-desk-docs" && exit 1)
	rsync -a --delete --exclude .git corpus/ "$(DOCS)/"
	git -C "$(DOCS)" status --short
	@echo "Review, then: git -C $(DOCS) commit -am 'demo: restore drifted docs' && git -C $(DOCS) push"

.PHONY: help setup up arbiter seed lint test security check eval eval-holdout demo-reset
