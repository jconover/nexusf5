# 03 — Post-boot health gate failure

Referenced from `f5_boot_switch` (version mismatch) and `f5_health_gate`
(HA red, sync disconnected, version mismatch). The device rebooted but did
not come back healthy.

## Diagnose

1. **Running version vs. expected:**
   ```bash
   curl -sk -u admin:<pw> https://<host>/mgmt/tm/sys/version | jq .
   ```
   If the version matches the prior (inactive-at-upgrade) volume, the boot
   target never flipped — likely a PATCH failure on the `active` property.
2. **HA status red / FORCED OFFLINE:** device is intentionally not taking
   traffic. Common causes: licensing expired, peer unreachable post-reboot,
   failsafe tripped on an interface.
3. **Sync disconnected:** the peer no longer trusts this unit — often after
   a master-key or device-group-membership mismatch survives the image
   cross-over.

## Recover

**Default response: roll back.** The two-volume model makes rollback cheap
and fast:
```bash
ansible-playbook playbooks/rollback.yml --limit <host>
```
Rollback flips the active volume to the prior one and reboots; the device
comes back at the pre-upgrade version, which is the known-good state for
that device.

**Only after rollback is in place**, investigate the unhealthy state on the
(now-inactive) target volume at leisure.

## Do not

- Loop the health gate "just a few more times" hoping it clears. The gate
  is a gate; if it failed, roll back and investigate.
- Re-apply DO/AS3 before the device is healthy. You will paper over the
  underlying problem.

## If canary surfaces this

Same blocker as runbook 02: canary failure blocks wave 1 approval.
