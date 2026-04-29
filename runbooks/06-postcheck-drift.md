# 06 — Postcheck DO/AS3 drift

## Symptom

`f5_postcheck` fails with one of:

```
DO/AS3 drift detected (terraform plan exit 2).
See runbooks/06-postcheck-drift.md for diagnosis.
```

```
DO/AS3 drift detected (terraform plan exit 1).
See runbooks/06-postcheck-drift.md for diagnosis.
```

Exit code semantics for `terraform plan -detailed-exitcode`:

- `0` — no changes; gate passes
- `1` — provider or terraform error; the plan didn't run cleanly
- `2` — drift detected; the device's live config diverged from the declaration

## Likely causes

- **Manual change on the device** — someone tmsh'd a config edit during the
  wave. Most common in mixed-fleet environments.
- **Partial UCS restore** — a rollback that loaded a UCS from before the
  declaration was last applied; restored config is now older than terraform
  state.
- **Failed DO or AS3 apply that left mixed state** — the upgrade reboot
  interrupted a declaration apply mid-flight; the device booted to a
  half-applied config.
- **Terraform state corrupt or stale** (exit 1 only) — `init` was run
  against a different backend, or state was hand-edited.

## Diagnostics

Capture the plan output for the runbook record:

```bash
cd terraform/environments/lab
terraform plan -no-color -refresh=true > /tmp/drift.txt 2>&1
echo "exit=$?"
head -60 /tmp/drift.txt
```

Identify which device(s) the drift attaches to:

```bash
grep -E '^(  # module\.|  ~ |  - |  \+ )' /tmp/drift.txt | head -40
```

If the drift is on `bigip_do.this` for one device, narrow the diff:

```bash
terraform plan -target=module.do_bigip_lab_01 -no-color > /tmp/drift_do.txt
```

If the drift is on `bigip_as3.this` for one tenant:

```bash
terraform plan -target=module.as3_bigip_lab_01 -no-color > /tmp/drift_as3.txt
```

## Resolution

1. **Read the diff.** Decide whether the live config or the declaration is
   correct. The declaration is the source of truth in steady state — if
   live config has drifted, re-apply terraform fixes it. If the declaration
   is stale (e.g. operator added a vlan via change ticket and terraform
   wasn't updated), update the declaration first.
2. **Re-apply against the affected device(s) only:**
   ```bash
   terraform apply -target=module.do_bigip_lab_01 -target=module.as3_bigip_lab_01
   ```
3. **Re-run the postcheck** for the affected host(s):
   ```bash
   ansible-playbook playbooks/upgrade.yml --tags postcheck --limit bigip-lab-01
   ```
4. **If drift persists** after re-apply, escalate. Possible causes: clock
   skew between provider and device, AS3 schema-version mismatch with
   installed iApps LX, or a custom iControl REST extension that mutates
   declarations server-side.

**Do not `terraform apply` blind during a wave.** A wave may be partway
through staged changes; an unscoped apply can stomp on devices currently
mid-upgrade. Always `-target` the specific device modules.

## Rollback decision tree

- **Drift discovered after a successful upgrade** (version gate passed,
  drift gate failed): the upgrade itself is fine. Re-apply terraform; do
  NOT roll back the upgrade.
- **Drift discovered during canary**, multiple devices affected, root cause
  unclear: stop the wave (`upgrade-wave.yml` cancellation). Investigate.
  Rolling back is acceptable only if drift correlates with the upgrade
  itself (e.g. the new TMOS version changed how a DO field gets normalized).
- **Drift consistently appears immediately after reboot**: file an issue
  against the upgrade flow — the boot path may be losing config that DO had
  applied. Until fixed, document the workaround in this runbook.

## Related

- `runbooks/04-rollback.md` — when to invoke the volume-flip rollback
- `terraform/environments/lab/README.md` — how the lab env is wired
- `docs/decisions/002-terraform-scope.md` — why Terraform owns config and
  not the upgrade flow
