# integration environment

Ephemeral AWS BIG-IP VE pair for `make integration`. Spun up at the start
of every run, torn down at the end (success or failure), never long-lived.

| Resource | Lifetime | Cost shape |
|---|---|---|
| VPC + subnet + IGW + route table | per run | $0 — no NAT gateway, no peering |
| EC2 key pair (TLS-generated) | per run | $0 |
| 2× F5 BIG-IP VE PAYG (Good 1Gbps, m5.large) | per run, ≤ 45 min | ~$0.30/hr per VE → ≤$0.45/run |
| 2× EIP | per run | $0.005/hr while in use |

Nothing in this env survives a teardown. The integration wrapper handles
both planned destroy (`terraform destroy` in a `try/finally`) and
nuclear-option teardown (`aws ec2 terminate-instances --filters
Name=tag:AutoDestroy,Values=true`) for the case where the wrapper itself
crashed before destroy ran.

## Direct apply

You usually invoke this through `make integration`, not directly. For
manual debugging:

```bash
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # set aws_account_id

cd terraform/environments/integration
terraform init
terraform apply
# ... interact with the VEs ...
terraform destroy  # don't forget — running VEs cost money
```

## What gets rendered

After apply, three files appear under `<repo>/build/integration/`
(gitignored, regenerated each run):

- `inventory.yml` — ansible inventory pointing at the two VEs over
  iControl REST. References `F5_API_PASSWORD` from the environment, so
  the password is never on disk in the inventory.
- `admin_password` — chmod 600. Read by the wrapper, exported as
  `F5_API_PASSWORD` before invoking ansible.
- `ssh_key` — chmod 600 RSA private key for ad-hoc SSH access. Used
  only for tmsh debugging on a wedged VE; not part of the upgrade
  pipeline.

## Mgmt ingress

By default the env auto-detects the runner's public IP via
`api.ipify.org` at plan time and locks SG ingress to that `/32`.
Override via `explicit_mgmt_cidrs` only when running from a known
fixed network (e.g. office VPN); never set it to `0.0.0.0/0`.

The detection happens at every plan, so reapplying from a different
network surfaces as a CIDR diff in the plan output — review before
approving.

## Tags applied

Every resource carries:

```
Project     = nexusf5
ManagedBy   = terraform
Environment = integration
AutoDestroy = true
CreatedAt   = <run_id>            # set by wrapper or random_id at apply
Name        = nexusf5-integration-<run_id>-<role>
```

The nuclear-option teardown is:

```bash
AWS_PROFILE=outlook aws ec2 terminate-instances \
  --filters Name=tag:Project,Values=nexusf5 Name=tag:AutoDestroy,Values=true \
  --query 'TerminatingInstances[].InstanceId' --output text \
  --region us-east-2
```

It runs unconditionally at the end of `make integration` if the wrapper
detects any leftover instances after `terraform destroy` claims success.

## Out of scope

- HA-sync configuration. Both VEs are independent. The mock-f5 50-device
  topology is where HA-sync logic gets exercised at zero cost.
- Three-NIC topology (mgmt + internal + external). Single-NIC for the
  upgrade-pipeline integration test.
- BYOL license management. PAYG only.
- Stage and prod environments. Those land separately, with the S3 +
  DynamoDB remote-state pattern.
