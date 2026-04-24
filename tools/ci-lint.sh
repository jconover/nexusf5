#!/usr/bin/env bash
#
# CI-parity lint. Runs the same steps as .github/workflows/lint.yml, from
# the same base image (python:3.12-slim), with the same pinned uv version
# (.tool-versions) and the same install path for ansible-lint (pip, not
# the system package). Intended as the authoritative pre-push check.
#
# Invoked by `make lint-ci`, which wraps this in a docker run so host
# tooling cannot leak in.

set -euo pipefail

UV_VERSION="${UV_VERSION:?UV_VERSION must be set — read from .tool-versions via the Makefile}"

echo "::group::install system deps"
apt-get update -qq
apt-get install -y --no-install-recommends curl ca-certificates >/dev/null
rm -rf /var/lib/apt/lists/*
echo "::endgroup::"

echo "::group::install uv ${UV_VERSION}"
curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
export PATH="/root/.local/bin:${PATH}"
uv --version
echo "::endgroup::"

echo "::group::mock-f5: uv sync + ruff + mypy + pytest"
cd mock-f5
uv sync
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest -q   # integration tests auto-skip when mock stack isn't up
cd ..
echo "::endgroup::"

echo "::group::yamllint (whole repo)"
pip install --quiet yamllint
yamllint .
echo "::endgroup::"

echo "::group::ansible-lint (fresh pip install, same as CI)"
pip install --quiet 'ansible-core>=2.17' ansible-lint
ansible-galaxy collection install -r ansible/collections/requirements.yml >/dev/null
cd ansible
ANSIBLE_ROLES_PATH="$(pwd)/roles" ansible-lint playbooks/ roles/
echo "::endgroup::"

echo "==> make lint-ci: all checks passed"
