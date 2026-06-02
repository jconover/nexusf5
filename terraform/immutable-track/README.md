# immutable-track

End-to-end demonstration of the **immutable upgrade track**: provision a new
BIG-IP VE at the target version, apply the same DO/AS3 declarations the
hybrid track applies (proving declaration portability), simulate a DNS
cutover, drain the (conceptual) old VE, and tear everything down.

This is the secondary upgrade track. The primary track is hybrid in-place
upgrade against existing HA pairs (see `terraform/environments/lab` and
the Phase 2/3 wave orchestration). The immutable track exists as a
**modernization shape** — for environments where you would rather replace
than upgrade. ADR 003 names concrete workload categories that fit each
side of the line; ADR 004 covers the cutover-safety mechanics.

## What gets provisioned

| Resource                                      | Why                                                                |
|-----------------------------------------------|--------------------------------------------------------------------|
| 1× F5 BIG-IP VE PAYG (Good 1Gbps, m5.large)   | The new VE at target version                                       |
| 1× EIP                                        | Static mgmt address                                                |
| VPC + public subnet + IGW + route table       | Minimal network — same shape as `environments/integration`         |
| Security group                                | mgmt/8443 + ssh/22 from a runner-/32, egress all                   |
| TLS keypair + EC2 key pair                    | Per-run SSH key; deleted on destroy                                |
| `random_password` (admin)                     | Per-run admin password; threaded into runtime-init + DO            |
| `bigip_do` (DO declaration via `do-declaration` module) | Onboarding config — applied via the bigip provider, not runtime-init |
| `bigip_as3` (AS3 declaration via `as3-declaration` module) | Application services — same modules as the lab env, unchanged |
| `null_resource.dns_cutover_stub`              | The stub described in ADR 004 — *no real DNS change*               |
| `local_sensitive_file` ×2                     | Rendered ansible inventory + ssh key (chmod 600)                   |

## Two-phase apply

The bigip provider talks to the new VE's iControl REST endpoint, which
only answers after `f5-bigip-runtime-init` has finished its
`bigip_ready_enabled` phase and posted the bootstrap DO declaration
(admin user + hostname). That window is 15–25 minutes after the EC2
instance starts. A single `terraform apply` from cold cannot drive the
`bigip_do` and `bigip_as3` resources directly — the provider tries to
authenticate at apply time, before user_data has finished running.

The integration wrapper splits this into two phases:

```bash
# Phase 1 — provision the VE, render inventory + ssh key. -target stops
# the apply at the resources that don't need iControl REST.
terraform apply \
  -target=module.bigip_aws_new \
  -target=local_sensitive_file.inventory \
  -target=local_sensitive_file.ssh_private_key

# Wait for /mgmt/tm/sys/version → 200 (the wrapper does this for you;
# manual apply: poll yourself or sleep 25m).

# Phase 2 — full apply. bigip_do, bigip_as3, and the dns_cutover_stub
# null_resource pick up automatically.
terraform apply
```

`make integration-immutable` runs the wrapper end-to-end. Direct
`terraform apply` from a laptop must follow the same two-phase recipe.

## Direct apply

You usually invoke this through `make integration-immutable`, not
directly. For manual debugging:

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # set aws_account_id

cd terraform/immutable-track
terraform init

# Phase 1
terraform apply \
  -target=module.bigip_aws_new \
  -target=local_sensitive_file.inventory \
  -target=local_sensitive_file.ssh_private_key

# Wait for the new VE to answer iControl REST. The runner's mgmt CIDR
# was set to your /32 at plan time; mgmt URL is in the rendered inventory.
sleep 1500
curl -k -u admin:$(terraform output -raw admin_password) \
  https://$(terraform output -json ve_endpoints | jq -r '."bigip-aws-new".mgmt_public_ip'):8443/mgmt/tm/sys/version

# Phase 2
terraform apply

# Run the cutover playbook (validate + DNS stub + drain window).
ansible-playbook -i $(terraform output -raw inventory_path) \
  ../../ansible/playbooks/immutable-cutover.yml

# Don't forget — running VEs cost money. See "Teardown" below for the
# repo-level make targets that also sweep for orphans.
terraform destroy
```

## Teardown

Running VEs and their EIPs bill by the hour, so tear them down when a run
is finished. From the repo root:

```bash
# Destroy just this stack (init + destroy -auto-approve).
make immutable-down

# Or destroy ALL billable AWS infra at once — this stack + the
# integration env — then sweep us-east-2 for anything Terraform doesn't
# track. Leaves the shared env (IAM/budget) and lab (device config) alone.
make destroy-all

# Read-only inventory of us-east-2 — confirm nothing was left behind.
# Lists EC2, EIP, EBS volumes/snapshots, AMIs, key pairs, VPCs, SGs,
# NAT gateways, RDS, and EFS. Deletes nothing.
make aws-sweep
```

`make destroy-all` is safe to re-run: if the stacks are already empty the
`destroy` is a no-op and it goes straight to the sweep. The sweep does not
cover Marketplace AMI subscriptions (the paid BIG-IP VE images) — cancel
those under *AWS Marketplace → Manage subscriptions* if you no longer need
the image.

## What gets rendered

After phase 1, two files appear under
`<repo>/build/integration-immutable/` (gitignored, regenerated each run):

- `inventory.yml` — ansible inventory pointing at the new VE over
  iControl REST. Per-host `f5_api_password` is the per-run
  `random_password.admin` value.
- `ssh_key` — chmod-600 RSA private key for ad-hoc SSH access. Used
  only for tmsh debugging on a wedged VE.

## Mgmt ingress

By default the env auto-detects the runner's public IP via
`api.ipify.org` at plan time and locks SG ingress to that `/32`.
Override via `explicit_mgmt_cidrs` only when running from a known
fixed network (e.g. office VPN); never set it to `0.0.0.0/0`.

## Tags applied

Every resource carries:

```
Project     = nexusf5
ManagedBy   = terraform
Environment = immutable-track
AutoDestroy = true
CreatedAt   = <run_id>            # set by wrapper or random_id at apply
Name        = nexusf5-immutable-<run_id>-<role>
```

The same nuclear-option teardown the integration env relies on works
here:

```bash
AWS_PROFILE=outlook aws ec2 terminate-instances \
  --filters Name=tag:Project,Values=nexusf5 Name=tag:AutoDestroy,Values=true \
  --query 'TerminatingInstances[].InstanceId' --output text \
  --region us-east-2
```

## What this proves

- DO/AS3 modules from PR 1 apply unchanged against a freshly-provisioned
  VE. If `terraform plan -detailed-exitcode` returns 0 immediately after
  apply, the declaration was applied successfully — same gate as drift
  detection (see `ansible/roles/f5_postcheck/README.md`).
- The cutover shape (validate → DNS stub → drain → destroy) round-trips
  cleanly. No leaked AWS resources after `make integration-immutable`.
- Spend ceiling: ≤$5/run (one Good 1Gbps PAYG VE for ≤45 min, one EIP,
  no NAT gateway, no peering).

## Out of scope

- HA-sync between old and new sides. The cutover model is DNS-flip, not
  cluster-rebuild.
- Real DNS provider integration (Route 53, Cloudflare, etc.). The stub
  in `dns_cutover.tf` documents where that plugs in (ADR 004).
- BYOL license management. PAYG only.
- Cross-region cutover. Single region by design.
