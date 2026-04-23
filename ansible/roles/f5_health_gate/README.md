# f5_health_gate

Hard post-reboot gate. Asserts:
- Running version matches `f5_target_version`
- HA color not red AND HA status not `FORCED OFFLINE`
- Sync color not red AND status not `Disconnected`

Failures point at `runbooks/03-post-boot-unhealthy.md`. There is no
`ignore_errors` in this role — health gates are gates.

## Required vars
- `f5_target_version`

## Tags
`healthgate`.
