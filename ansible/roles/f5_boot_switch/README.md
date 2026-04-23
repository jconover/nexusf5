# f5_boot_switch

Flips the BIG-IP's active volume to the requested one, reboots, and waits
for the device to return at the target version.

## Symmetry
Used by both upgrade and rollback flows — caller sets:
- `f5_boot_switch_target_volume` (e.g. `HD1.2` for upgrade, `HD1.1` for rollback)
- `f5_boot_switch_target_version` (e.g. `17.1.0` for upgrade, `16.1.3` for rollback)

## Sequence
1. `PATCH /mgmt/tm/sys/software/volume/{volume}` with `active: true`.
2. `POST /mgmt/tm/util/bash` with `tmsh save sys config; reboot`.
3. Poll `GET /mgmt/tm/sys/version` (accepting 503 during reboot window)
   until the returned version matches `f5_boot_switch_target_version`.
4. Assert version match — otherwise points at
   `runbooks/03-post-boot-unhealthy.md`.

## Tuneables
- `f5_boot_switch_poll_retries` (default 60)
- `f5_boot_switch_poll_delay` seconds (default 10)

## Tags
`reboot`.
