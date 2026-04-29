# ve-instance

Provisions a single F5 BIG-IP VE on AWS from the PAYG marketplace AMI.
Used by `terraform/environments/integration/` to spin up an HA pair
(two independent module invocations) for `make integration`.

## Scope (deliberately minimal)

- **Single ENI** sharing mgmt and data plane. Production-shape three-NIC
  topologies (mgmt + internal + external) are out of scope; the upgrade
  pipeline integration test only exercises the iControl REST mgmt
  surface, which one NIC handles fine.
- **No HA sync.** Two ve-instance invocations in the integration env are
  independent VEs; the test exercises per-device upgrade flow, not
  active/standby failover. Real HA-sync logic is demonstrated against
  the mock-f5 50-device topology where it doesn't cost anything.
- **PAYG only**, no BYOL license management. AMI lookup picks the most
  recent version matching the `f5_version_pattern` glob; pin the
  pattern in the integration env's tfvars if reproducibility matters
  more than tracking F5's point releases.
- **No long-running resources.** No NAT gateway (the most expensive
  accidental leak at $30+/mo); the VE has direct public-subnet
  ingress via EIP. If the future integration env needs to reach
  private-subnet workloads, a VPC endpoint for S3 is the
  cost-conscious alternative.

## Cost shape

Per-VE per-hour, region us-east-2 (verify current pricing in marketplace):

| License | Throughput | Software | EC2 (m5.large) | Total |
|---------|------------|----------|----------------|-------|
| Good    | 1Gbps      | ~$0.20   | $0.096         | ~$0.30 |
| Better  | 1Gbps      | ~$0.50   | $0.096         | ~$0.60 |
| Best    | 1Gbps      | ~$1.30   | $0.096         | ~$1.40 |

Defaults are Good/1Gbps because the integration test exercises iControl
REST, not paid LTM features. HA pair (2 VEs) at Good/1Gbps for a 45-min
run lands at ~$0.45 — well within the $5–15 PR 2 budget for full
end-to-end iteration.

## Required tags

The integration env passes `Project=nexusf5`, `AutoDestroy=true`, and a
per-run `CreatedAt={timestamp}` tag through `var.tags`. The
nuclear-option teardown (`aws ec2 terminate-instances --filters
Name=tag:AutoDestroy,Values=true`) relies on the AutoDestroy tag being
present on every resource the module creates — security group rules,
EIPs, root volumes, the instance itself.

## Marketplace subscription prerequisite

F5 BIG-IP VE PAYG AMIs require a one-time per-account marketplace
subscription before EC2 can launch them. See
`terraform/environments/shared/README.md` for the activation procedure.
This module's apply will fail with `OptInRequired` if the subscription
hasn't been accepted.

## Inputs

| Variable             | Default       | Notes                                                    |
|----------------------|---------------|----------------------------------------------------------|
| `name`               | required      | EC2 Name tag, ansible inventory hostname                 |
| `subnet_id`          | required      | Subnet for the single ENI                                |
| `vpc_id`             | required      | VPC the SG attaches to                                   |
| `instance_type`      | `m5.large`    | F5 minimum for VE                                        |
| `ssh_key_name`       | required      | Existing EC2 key pair name                               |
| `f5_version_pattern` | `F5 BIGIP-17.1.*` | AMI name glob                                        |
| `f5_license_tier`    | `Good`        | One of Good/Better/Best                                  |
| `f5_throughput_tier` | `1Gbps`       | PAYG throughput cap                                      |
| `admin_password`     | required (sensitive) | Set on first boot via cloud-init; replaced by DO   |
| `allowed_mgmt_cidrs` | `[]`          | CIDRs allowed to reach 22/443 — must be set, not 0.0.0.0/0 |
| `tags`               | `{}`          | Merged onto every resource (Project, AutoDestroy, CreatedAt) |

## Outputs

`instance_id`, `mgmt_public_ip`, `mgmt_public_dns`, `private_ip`,
`ami_id`, `ami_name`, `security_group_id`.

`mgmt_public_ip` is the address ansible's inventory points at.
`ami_id`/`ami_name` are surfaced for run-log diagnosability when F5
publishes a point release between runs.
