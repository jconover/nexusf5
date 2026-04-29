# as3-declaration

Renders a minimal valid F5 Application Services 3 (AS3) declaration and
applies it via `bigip_as3`. One tenant, one application: a `Service_HTTP`
VIP backed by a two-member pool with an HTTP monitor.

## Usage

```hcl
module "as3_bigip_lab_01" {
  source = "../../modules/as3-declaration"

  providers = {
    bigip = bigip.bigip_lab_01
  }

  device_hostname = "bigip-lab-01.local"
  tenant_name     = "nexusf5_lab_01"
  app_name        = "lab_app"
  vip_address     = "10.10.0.11"
  pool_members = [
    { ip = "10.10.1.10", port = 80 },
    { ip = "10.10.1.11", port = 80 },
  ]
}
```

## Why this stays minimal

The Phase 4 acceptance criterion is round-trip through the provider against
the mock (and against a real AWS BIG-IP VE in PR 2). Production realism on
the declaration is out of scope and would obscure the drift-detection signal
the postcheck role keys on.

## Inputs

| Variable           | Type           | Default                          |
|--------------------|----------------|----------------------------------|
| `device_hostname`  | string         | required                         |
| `tenant_name`      | string         | `nexusf5_lab`                    |
| `app_name`         | string         | `lab_app`                        |
| `vip_address`      | string         | `10.10.0.10`                     |
| `pool_members`     | list(object)   | two RFC1918 members on port 80   |
| `monitor_interval` | number         | `5`                              |

## Outputs

- `tenant_name` — same value passed in; convenience for the caller's read step
- `declaration_id` — `bigip_as3` resource ID
