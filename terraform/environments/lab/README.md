# lab environment

Configures the 5 canary mock devices (`bigip-lab-01` .. `bigip-lab-05`) with
DO and AS3 declarations via the F5 Terraform provider.

## Prerequisites

The provider talks to the devices through the nginx adapter sidecar in
`mock-f5/proxy/`. Bring up the full stack first:

```bash
make mock-up    # mock-f5 (port 8100) + mock-f5-proxy (ports 8101–8105)
```

## Apply workflow

```bash
make lab-up      # terraform init + apply
make lab-down    # terraform destroy
```

Or by hand:

```bash
cd terraform/environments/lab
terraform init
terraform apply
```

## Why this lab uses a local backend

The remote-state pattern (S3 + DynamoDB lock) documented in `CLAUDE.md`
applies to stage and prod. The lab state is throwaway — every contributor's
laptop is its own truth — and forcing a remote backend here would gate the
quickstart on AWS credentials. PR 2 introduces `terraform/environments/stage/`
with the remote backend.

## Why one provider block per device

Terraform's `provider` blocks cannot use `for_each`. Aliases must be static
at parse time so the dependency graph can be built before any expression
evaluates. Five devices means five provider blocks and five module
invocations apiece for DO and AS3. The repetition is structural, not a
copy-paste smell — see the comment block at the top of `main.tf`.

## Drift workflow (Phase 4 PR 1 acceptance criterion)

```bash
# Apply once.
terraform apply

# Should be a no-op the second time.
terraform plan -detailed-exitcode    # exits 0

# Inject drift on a single device.
curl -X POST http://localhost:8100/_chaos/bigip-lab-01/drift-postcheck

# Plan now reports drift on the do_get / as3_get reads.
terraform plan -detailed-exitcode    # exits 2

# Clear chaos and the read goes back to the applied state.
curl -X POST http://localhost:8100/_chaos/bigip-lab-01/reset
terraform plan -detailed-exitcode    # exits 0
```

The Ansible `f5_postcheck` role runs the same `terraform plan
-detailed-exitcode` as its drift gate.
