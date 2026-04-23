# 04 — Rollback

The rollback playbook is the primary recovery action for post-boot
unhealthy devices (see runbook 03) and for operator-driven aborts. It is
first-class — not an afterthought, not a bolt-on script.

## What it does

1. Lists software volumes on the device.
2. Picks the currently-inactive volume as the rollback target. On a
   just-failed upgrade that volume carries the prior version.
3. Flips the active flag to the rollback target
   (`PATCH /mgmt/tm/sys/software/volume/{volume}` with `active: true`).
4. Reboots via `POST /mgmt/tm/util/bash` with `tmsh save sys config; reboot`.
5. Polls `GET /mgmt/tm/sys/version` until the device returns at the
   rollback version.
6. Runs the health gate against the rolled-back version.

The BIG-IP two-volume boot model is the safety net. The playbook does not
reconstruct state — it just tells the device which volume to boot.

## Running

**Single host** (post-failure of a single device in a wave):
```bash
ansible-playbook playbooks/rollback.yml --limit bigip-dc1-042
```

**Whole wave** (canary surfaced a bad image and wave 1 already partially
ran before the approval was blocked):
```bash
ansible-playbook playbooks/rollback.yml --limit wave_1
```

Rollback is idempotent — a device already on the prior version (because the
upgrade never progressed past preflight or install) is still safe to invoke
rollback against; the active volume is already correct and the reboot is
the only real-world operation.

## When not to use

- **The upgrade actually succeeded** and you are second-guessing the version
  bump. Rolling back a healthy upgraded device re-introduces the old
  vulnerabilities; do not do this without change-management sign-off.
- **The device is hardware-faulted** (drive failure). Rollback cannot help
  — escalate to hardware replacement.

## What to check after rollback

- `runbooks/03-post-boot-unhealthy.md` diagnostics, against the rollback
  target this time. If rollback also lands unhealthy, the device was
  unhealthy before the upgrade — the upgrade is not at fault.
- UCS backup from `f5_backup` is available on local store (`/var/local/ucs/`)
  as an additional recovery artifact.

## Phase note

Phase 2 covers volume-flip rollback. Phase 4 adds the UCS-restore branch
(`action=load`) as an operator-triggered option when drift is detected
after the rollback reboot.
