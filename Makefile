.PHONY: help install-deps lint lint-ci test test-unit integration mock-up mock-down mock-logs mock-build clean

# Single source of truth for the uv version. The workflow reads the same
# file via setup-uv's version-file input; the Dockerfile takes it as a
# build arg so the runtime image and the CI lint env never drift apart.
UV_VERSION := $(shell awk '$$1 == "uv" {print $$2}' .tool-versions)
export UV_VERSION

MOCK_COMPOSE := docker compose -f mock-f5/docker-compose.yml

help: ## Show this help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install-deps: ## Install Python + Ansible collection dependencies
	cd mock-f5 && uv sync
	ansible-galaxy collection install -r ansible/collections/requirements.yml --force

lint: ## Run all linters against host tooling — fast, for iteration
	cd mock-f5 && uv run ruff check app tests
	cd mock-f5 && uv run ruff format --check app tests
	cd mock-f5 && uv run mypy app
	cd observability/ingest && uv run ruff check .
	cd observability/ingest && uv run ruff format --check .
	cd observability/ingest && uv run mypy
	yamllint .
	cd ansible && ANSIBLE_ROLES_PATH=$(PWD)/ansible/roles ansible-lint playbooks/ roles/

lint-ci: ## Run lint exactly as CI does (containerized) — authoritative pre-push check
	@echo "==> CI-parity lint in python:3.12-slim with uv=$(UV_VERSION)"
	# --user maps host UID:GID so the container doesn't root-own the
	# generated .venv directories. HOME/USER keep uv/pip happy with
	# a nonzero UID. Discovered after `make lint-ci` on an earlier
	# pass left root-owned .venv dirs that blocked `make lint`.
	docker run --rm \
	  --user $(shell id -u):$(shell id -g) \
	  -e HOME=/tmp -e USER=ci \
	  -v "$(PWD):/repo" -w /repo \
	  -e UV_VERSION=$(UV_VERSION) \
	  python:3.12-slim \
	  bash /repo/tools/ci-lint.sh

mock-build: ## Build the mock F5 docker image
	$(MOCK_COMPOSE) build

mock-up: ## Start the 50-device multiplexed mock F5 stack
	$(MOCK_COMPOSE) up -d --wait
	@echo "==> Mock F5 up: 50 devices behind http://localhost:8100/<hostname>"

mock-down: ## Stop and remove the mock F5 stack
	$(MOCK_COMPOSE) down -v

mock-logs: ## Tail mock-f5 logs
	$(MOCK_COMPOSE) logs -f

test-unit: ## Fast in-process pytest run (no Docker, no ansible)
	cd mock-f5 && uv run pytest -q --ignore=tests/integration
	cd observability/ingest && uv run pytest -q

test: mock-up ## Full suite: unit + integration (drives ansible-playbook) + preflight
	cd mock-f5 && uv run pytest -q
	cd ansible && ansible-playbook -i inventory/hosts.yml playbooks/preflight.yml --limit lab
	@echo "==> Test suite green. Mock is still up — run 'make mock-down' when done."

integration: ## (Phase 4) AWS BIG-IP VE round-trip integration test
	@echo "Phase 4: AWS VE integration is not implemented yet."
	@exit 1

clean: ## Remove caches, virtualenvs, and transient artifacts
	rm -rf mock-f5/.venv mock-f5/.pytest_cache mock-f5/.ruff_cache mock-f5/.mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.retry' -delete 2>/dev/null || true
