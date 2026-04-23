# f5_backup

Saves a UCS backup to the BIG-IP's local UCS store via iControl REST.

## What it does
- POST `/mgmt/tm/sys/ucs` with `{command: save, name: ...}` per
  https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_ucs.html
- Generates the UCS name from `nexusf5-<host>-<YYYYMMDDTHHMMSS>.ucs` unless
  `f5_backup_ucs_name` is supplied.

## Scope
Phase 2 only writes to the device's local UCS store. Remote-destination
offload (S3) arrives in Phase 4 alongside the AWS integration lane.

## Facts set
- `f5_backup_ucs_name` — final UCS filename used on the device.

## Tags
`backup`, `always` (for the filename derivation).
