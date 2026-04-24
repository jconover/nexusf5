# f5_preflight

Collects BIG-IP pre-upgrade health state via iControl REST and hard-asserts
readiness. There is no `ignore_errors: true` here — health gates are gates,
per CLAUDE.md non-negotiables.

## What it checks
- TMOS version (`GET /mgmt/tm/sys/version`)
- HA failover status and color (`GET /mgmt/tm/cm/failover-status`)
- Config sync status (`GET /mgmt/tm/cm/sync-status`)
- CPU, memory, active connections (`GET /mgmt/tm/sys/performance/all-stats`)

## Facts set
- `f5_fact_version`
- `f5_fact_ha_status`, `f5_fact_ha_color`
- `f5_fact_sync_status`, `f5_fact_sync_color`
- `f5_fact_cpu_pct`, `f5_fact_mem_pct`, `f5_fact_connections`

## Required host/group vars
- `f5_api_base_url` — e.g. `http://localhost:8100/{{ inventory_hostname }}` (Phase 3 multiplexed mock) or `https://bigip-dc1-042.example.net` (real F5)
- `f5_api_user`, `f5_api_password`
- `f5_validate_certs`

## Tuneables (see `defaults/main.yml` and `inventory/group_vars/all.yml`)
- `f5_preflight_fail_on_red` (default `true`)
- `f5_preflight_cpu_max_pct` (default `80`)
- `f5_preflight_mem_max_pct` (default `85`)
- `f5_preflight_connections_max` (default `500000`)

## Tags
`preflight`, `always`.

## Failure handling
Every assertion failure references `runbooks/01-preflight-failure.md`.

## Raw iControl REST usage
Phase 1 uses `ansible.builtin.uri` for every call. Each task is flagged
`# raw-icontrol-rest` and cites its upstream endpoint. Phase 2 revisits
whether `f5networks.f5_bigip` modules are a better fit once the mock's
response surface grows.
