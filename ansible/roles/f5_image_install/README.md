# f5_image_install

Installs the target TMOS image to the BIG-IP's currently-inactive volume.

## Sequence
1. List volumes (`GET /mgmt/tm/sys/software/volume`) to pick the inactive one.
2. Register the image (`POST /mgmt/tm/sys/software/image`).
3. Kick off async install (`POST /mgmt/tm/sys/software/volume` with
   `command=install`).
4. Poll the specific volume (`GET /mgmt/tm/sys/software/volume/{volume}`)
   until status is `complete` or `failed`.
5. Hard-assert `status == complete`. On failure, point at
   `runbooks/02-image-install-stuck.md`.

## Required vars
- `f5_target_version` — e.g. `17.1.0`
- `f5_target_image_name` — e.g. `BIGIP-17.1.0-0.0.3.iso`
- Credentials from `group_vars/all.yml`.

## Tuneables (see `defaults/main.yml`)
- `f5_image_install_poll_retries` (default 60)
- `f5_image_install_poll_delay` seconds (default 10)

## Facts set
- `f5_image_install_target_volume` — the volume name installed to (picked as the
  currently-inactive one).

## Tags
`install`.
