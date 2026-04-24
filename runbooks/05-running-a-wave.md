# Running a wave

Operator guide for driving a fleet upgrade end-to-end using the
Phase 3 GitHub Actions workflows. The workflows enforce the mechanics
(gating, concurrency, artifact schema); this runbook covers the
pieces GitHub itself owns — environments, required reviewers, secrets
— because those can't be committed to the repo.

## One-time GitHub setup

These steps configure the repository once. Skip if already done.

### 1. Create the four protected environments

Settings → Environments → New environment. Create each of:

- `canary`
- `wave_1`
- `wave_2`
- `wave_3`

For each environment:

- **Required reviewers**: add the people who must approve a promotion
  into that wave. Canary typically needs 1 reviewer; later waves more.
  This is the human-in-the-loop checkpoint.
- **Wait timer**: optional. Some teams add 5–15 minutes between waves
  for soak.
- **Deployment branches**: restrict to `main` so a feature branch
  can't kick a real wave.

Each job in the reusable workflow sets `environment: <wave_name>`, so
the matrix blocks on approval for that specific environment before
any device starts upgrading.

### 2. Configure the Pushgateway secret (optional)

If you have a Pushgateway deployed:

- Settings → Secrets and variables → Actions → New repository secret
- Name: `PUSHGATEWAY_URL`
- Value: the base URL, e.g. `http://pushgateway.internal:9091`

Without this secret, the `push-metrics` job logs "PUSHGATEWAY_URL not
set; skipping push" and passes. The wave still runs; the dashboard
just doesn't get metrics.

### 3. Confirm the `gh` CLI works locally

```bash
gh auth status
```

The operator needs `gh` to look up the canary run ID the wave_1 promoter
expects as input.

## Running canary → wave_1

1. **Kick canary.**
   ```bash
   gh workflow run upgrade-canary.yml \
     -f target_version=17.1.0 \
     -f target_image_name=BIGIP-17.1.0-0.0.3.iso
   ```
   Watch: `gh run watch` or the Actions tab. Canary runs serially over
   the 5 devices in the `canary` inventory group. The `canary` environment
   asks for reviewer approval before the matrix starts.

2. **Wait for canary to finish green.**
   All 5 devices must come back `status: success` in their artifacts.
   Any `failed` breaks the gate below.

3. **Capture the canary run ID.**
   ```bash
   gh run list --workflow=upgrade-canary.yml --limit 1 --json databaseId,conclusion
   ```
   Use the `databaseId` from the most recent successful run.

4. **Kick wave_1.**
   ```bash
   gh workflow run upgrade-wave.yml \
     -f wave_name=wave_1 \
     -f prior_wave=canary \
     -f prior_wave_run_id=<canary-run-id> \
     -f target_version=17.1.0 \
     -f target_image_name=BIGIP-17.1.0-0.0.3.iso
   ```
   The `gate` job runs first: downloads the canary artifacts, runs
   `python -m observability.ingest.gate` against them, exits 0 if
   every device succeeded. Exit 1 blocks the matrix. This is not an
   honor system — it's a workflow job with an exit code.

5. **Approve wave_1.**
   The `wave_1` environment's required reviewers approve before the
   matrix fans out. Parallelism defaults to 10; the first 10 devices
   start upgrading, the rest queue.

6. **Watch the wave.**
   ```bash
   gh run watch
   ```
   Individual device failures don't stop the wave (`fail-fast: false`);
   they just show up as `failed` in that device's artifact. The
   aggregate success rate is evaluated by the next wave's gate.

## If the gate fails

The gate exits 1 with a message like:

```
[gate-fail] wave=canary: success rate 4/5 (80.0%) below threshold 100.0%. Failed devices: bigip-lab-03.
```

or

```
[gate-fail] wave=canary: prior-wave artifacts directory not found: .../prior-artifacts. Gate fails closed — re-run the prior wave before promoting.
```

or

```
[gate-fail] wave=canary: schema violation in bigip-lab-02.json: status: Input should be 'success' or 'failed'.
```

Recovery:

- **Below-threshold**: investigate the named failed devices with
  `runbooks/03-post-boot-unhealthy.md` (or 02 if the install itself
  failed). Roll them back with `gh workflow run rollback.yml -f
  device=<name>`. Re-run canary once they're healthy; re-kick wave_1
  with the new run ID.
- **Missing artifacts**: the prior wave didn't run or its artifacts
  failed to upload. Re-run the prior wave; don't lower the threshold
  to bypass.
- **Schema violation**: `observability/ingest` may have been updated
  without the workflow catching up (or vice versa). Check the named
  file, match the output to the Pydantic model in
  `observability/ingest/schema.py`, fix the writer. Never silently
  drop the bad artifact and retry — the gate is right to refuse.

## Concurrency behavior

The reusable workflow sets:

```yaml
concurrency:
  group: upgrade-wave-${{ inputs.wave_name }}
  cancel-in-progress: false
```

- **Same wave twice**: the second run queues until the first finishes.
  Nothing gets double-upgraded.
- **Different waves simultaneously**: wave_1 and wave_3 have different
  concurrency groups, so they can run in parallel. That's intentional —
  the fleet's real constraint is the gate chain, not a blanket lock.
- **Rollback is serialized per device** via a device-scoped
  concurrency group in `rollback.yml`. Two operators hitting rollback
  on the same device at the same time queue instead of racing.

## Rolling back a single device

```bash
gh workflow run rollback.yml -f device=bigip-lab-07
```

No gate, no artifact, no wave. The rollback playbook flips the active
volume back to the prior version and reboots; BIG-IP's two-volume
boot model is the actual safety net. See
`runbooks/04-rollback.md` for the playbook-level detail.

## Phase 3 scope caveat

In Phase 3 the inventory populates canary (5) and wave_1 (45) only;
`wave_2` and `wave_3` are empty placeholders. Running
`upgrade-wave.yml` with `wave_name=wave_2` currently fails the
`discover` job with "empty matrix" — that's the correct Phase 3
behaviour. Populating wave_2 / wave_3 is a Phase 5 scale-target task.
