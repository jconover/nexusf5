# mock-f5 proxy adapter

Per-device nginx sidecar that gives each canary mock device a dedicated port
and rewrites `/mgmt/...` to the multiplexed `/<hostname>/mgmt/...` form the
mock expects.

## Why this exists

The F5 Terraform provider (`F5Networks/terraform-provider-bigip`) treats the
`address` argument as a bare host. Internally it passes that string to
`go-bigip`'s `NewSession`, which builds every URL by concatenation:
`https://<address>:<port>/mgmt/...`. There is no `path_prefix` argument, no
transport-level URL rewriting, and no Host-header override. Putting a path
in `address` produces malformed requests.

Sources (verified for PR 1 of Phase 4):
- `F5Networks/terraform-provider-bigip/bigip/provider.go` (~line 139): the
  `address` from the provider block is passed unmodified into the go-bigip
  session constructor.
- `scottdware/go-bigip/bigip.go` (~line 109): `NewSession` formats every URL
  as `fmt.Sprintf("https://%s:%s/mgmt/...", host, port)` — prefix in `host`
  yields `https://<host>/<prefix>:<port>/...`, which is invalid.

The mock-f5 server multiplexes 50 devices behind a single port, keyed by the
first URL path segment (`/{hostname}/mgmt/tm/...`; see ADR 001). That works
fine for `curl` and the Ansible roles (which template the prefix into
`f5_api_base_url`), but it cannot work for the F5 provider as-is.

This sidecar bridges the two: the provider points at `127.0.0.1:8101`, the
sidecar listens there, and it proxies to `mock-f5:8080/bigip-lab-01/...`.

This is **dev-only infra**. Real F5 environments have one DNS or VIP per
device; the provider points at it directly and no sidecar is needed.

## Port allocation

| Port | Device          |
|------|-----------------|
| 8101 | bigip-lab-01    |
| 8102 | bigip-lab-02    |
| 8103 | bigip-lab-03    |
| 8104 | bigip-lab-04    |
| 8105 | bigip-lab-05    |

Source of truth: [`mock-f5/manifests/canary.json`](../manifests/canary.json).

## How the render works

`render_nginx_conf.py` runs at container start (no rebuild required to add
or rename devices). It reads `/manifests/canary.json`, validates that no
two devices share a port, and emits `/etc/nginx/conf.d/devices.conf` with
one `server { listen <port> ssl; ... }` block per device. The proxy_pass
target is `http://mock-f5:8080/<hostname>/mgmt/` — the trailing slashes are
load bearing and the rendered conf documents why inline.

Override `MANIFEST_PATH` / `OUTPUT_PATH` / `UPSTREAM` env vars to render
against a different manifest or upstream during testing.

## TLS

The F5 provider hardcodes `https://` URLs (it has no `scheme` argument and
no plaintext fallback). The Dockerfile generates a self-signed certificate
at build time so the adapter can terminate TLS on every device port. The
Terraform provider blocks set `validate_certs = false` to accept it; this
is dev-only infra and the cert never leaves the laptop.

## Running

The sidecar is wired into `mock-f5/docker-compose.yml` as the `mock-f5-proxy`
service. `make mock-up` brings it up alongside the multiplexed mock.
