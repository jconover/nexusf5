.PHONY: help install-deps lint test integration mock-up mock-down mock-logs mock-build clean

MOCK_COMPOSE := docker compose -f mock-f5/docker-compose.yml

help: ## Show this help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install-deps: ## Install Python + Ansible collection dependencies
	cd mock-f5 && uv sync
	ansible-galaxy collection install -r ansible/collections/requirements.yml --force

lint: ## Run all linters (ruff, mypy, yamllint, ansible-lint)
	cd mock-f5 && uv run ruff check app tests
	cd mock-f5 && uv run ruff format --check app tests
	cd mock-f5 && uv run mypy app
	yamllint .
	cd ansible && ANSIBLE_ROLES_PATH=$(PWD)/ansible/roles ansible-lint playbooks/ roles/

mock-build: ## Build the mock F5 docker image
	$(MOCK_COMPOSE) build

mock-up: ## Start the 5-device mock F5 compose stack
	$(MOCK_COMPOSE) up -d --wait
	@echo "==> Mock F5 devices up: bigip-lab-01..05 on localhost:8101..8105"

mock-down: ## Stop and remove the mock F5 stack
	$(MOCK_COMPOSE) down -v

mock-logs: ## Tail mock-f5 logs
	$(MOCK_COMPOSE) logs -f

test-unit: ## Fast in-process pytest run (no Docker, no ansible)
	cd mock-f5 && uv run pytest -q --ignore=tests/integration

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
