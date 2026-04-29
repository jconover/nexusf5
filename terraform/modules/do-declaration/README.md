# do-declaration

Renders a minimal valid F5 Declarative Onboarding (DO) declaration from
HCL variables and applies it via the `bigip_do` resource.

## Usage

```hcl
module "do_bigip_lab_01" {
  source = "../../modules/do-declaration"

  providers = {
    bigip = bigip.bigip_lab_01
  }

  device_hostname = "bigip-lab-01.local"
  dns_servers     = ["10.0.0.2"]
  ntp_servers     = ["10.0.0.3"]
  timezone        = "UTC"
}
```

## What the rendered declaration covers

- System hostname and `autoPhonehome=false` (no callbacks to F5 from a lab)
- DNS resolvers
- NTP servers + timezone
- Optional VLANs in the `Common` tenant

The declaration is intentionally small. The Phase 4 goal is round-tripping
through the provider against the mock and (in PR 2) a real AWS BIG-IP VE,
not representing a production estate.

## Inputs

| Variable          | Type            | Required | Notes                                                  |
|-------------------|-----------------|----------|--------------------------------------------------------|
| `device_hostname` | string          | yes      | FQDN; also surfaces in `outputs.applied_label`         |
| `mgmt_ip`         | string          | no       | Default `127.0.0.1` (lab proxy adapter)                |
| `dns_servers`     | list(string)    | no       | Default `["10.0.0.2"]`                                 |
| `ntp_servers`     | list(string)    | no       | Default `["10.0.0.3"]`                                 |
| `timezone`        | string          | no       | Default `UTC`                                          |
| `vlans`           | list(object)    | no       | Empty by default                                       |
| `admin_password`  | string (sens.)  | no       | Reserved for real-VE work in PR 2                      |

## Outputs

- `declaration_id` — `bigip_do` resource ID
- `applied_label` — the `nexusf5-<hostname>` label embedded in the declaration
