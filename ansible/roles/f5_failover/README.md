# f5_failover

Triggers HA failover idempotently.

- `GET /mgmt/tm/cm/failover-status` — read current state
- `POST /mgmt/tm/sys/failover` — only if currently `ACTIVE`
- No-op on a device already in `STANDBY`

Safe to re-run mid-wave. Tags: `failover`.
