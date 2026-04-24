"""iControl REST endpoint subset used by the NexusF5 upgrade runbook.

Every handler documents the upstream F5 API path it mirrors.
Reference: https://clouddocs.f5.com/api/icontrol-rest/
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from app.deps import DeviceDep
from app.models import (
    FailoverCommand,
    SoftwareImageInstallCommand,
    SoftwareVolumeCommand,
    UcsSaveCommand,
    UtilBashCommand,
    VolumePatchCommand,
)
from app.state import (
    DeviceState,
    HAState,
    OperationStatus,
    Volume,
    now,
)

# Phase 3 multiplexing: hostname is the first path segment. `get_device`
# reads it from request.path_params and resolves the per-device state.
# See docs/decisions/001-mock-topology.md.
router = APIRouter(prefix="/{hostname}/mgmt/tm")


def _reboot_guard(device: DeviceState) -> Response | None:
    """Return a 503 response if the device is mid-reboot.

    Called at the top of every iControl REST handler. Real BIG-IP returns
    connection resets during reboot; a 503 with a Retry-After header is the
    closest HTTP-layer analogue and is what clients should handle either way.
    """
    device.advance()
    if device.is_rebooting():
        return Response(
            content='{"code":503,"message":"Device is rebooting"}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "5"},
        )
    return None


def _volume_payload(device: DeviceState, v: Volume) -> dict[str, Any]:
    self_link = f"https://{device.hostname}/mgmt/tm/sys/software/volume/{v.name}"
    return {
        "kind": "tm:sys:software:volume:volumestate",
        "name": v.name,
        "version": v.version,
        "product": v.product,
        "status": v.status,
        "active": v.active,
        "selfLink": self_link,
    }


# GET /mgmt/tm/sys/version
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_version.html
@router.get("/sys/version")
def sys_version(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    entry_url = f"https://{device.hostname}/mgmt/tm/sys/version/0"
    return {
        "kind": "tm:sys:version:versionstats",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/version",
        "entries": {
            entry_url: {
                "nestedStats": {
                    "entries": {
                        "Build": {"description": device.build},
                        "Edition": {"description": device.edition},
                        "Product": {"description": device.product},
                        "Title": {"description": "Main Package"},
                        "Version": {"description": device.version},
                    }
                }
            }
        },
    }


# GET /mgmt/tm/cm/failover-status
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_cm_failover-status.html
@router.get("/cm/failover-status")
def cm_failover_status(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    if device.ha_state == HAState.ACTIVE:
        color = "green"
    elif device.ha_state == HAState.STANDBY:
        color = "yellow"
    else:
        color = "red"
    entry_url = f"https://{device.hostname}/mgmt/tm/cm/failover-status/0"
    return {
        "kind": "tm:cm:failover-status:failover-statusstats",
        "selfLink": f"https://{device.hostname}/mgmt/tm/cm/failover-status",
        "entries": {
            entry_url: {
                "nestedStats": {
                    "entries": {
                        "color": {"description": color},
                        "status": {"description": device.ha_state.value},
                        "summary": {"description": f"1/1 {device.ha_state.value.lower()}"},
                    }
                }
            }
        },
    }


# GET /mgmt/tm/cm/sync-status
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_cm_sync-status.html
@router.get("/cm/sync-status")
def cm_sync_status(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    color_map = {
        "In Sync": "green",
        "Changes Pending": "yellow",
        "Disconnected": "red",
    }
    color = color_map[device.sync_state.value]
    entry_url = f"https://{device.hostname}/mgmt/tm/cm/sync-status/0"
    return {
        "kind": "tm:cm:sync-status:sync-statusstats",
        "selfLink": f"https://{device.hostname}/mgmt/tm/cm/sync-status",
        "entries": {
            entry_url: {
                "nestedStats": {
                    "entries": {
                        "color": {"description": color},
                        "status": {"description": device.sync_state.value},
                        "mode": {"description": "high-availability"},
                    }
                }
            }
        },
    }


# GET /mgmt/tm/sys/performance/all-stats
# Abbreviated — real endpoint returns dozens of counters.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_performance_all-stats.html
@router.get("/sys/performance/all-stats")
def sys_performance_all_stats(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    base = "https://localhost/mgmt/tm/sys/performance/all-stats"
    return {
        "kind": "tm:sys:performance:all-stats:all-statsstats",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/performance/all-stats",
        "entries": {
            f"{base}/CPU%20Usage": {
                "nestedStats": {
                    "entries": {
                        "Average": {"description": f"{device.cpu_pct:.1f}"},
                        "Current": {"description": f"{device.cpu_pct:.1f}"},
                    }
                }
            },
            f"{base}/Memory%20Used": {
                "nestedStats": {
                    "entries": {
                        "Average": {"description": f"{device.mem_pct:.1f}"},
                        "Current": {"description": f"{device.mem_pct:.1f}"},
                    }
                }
            },
            f"{base}/Active%20Connections": {
                "nestedStats": {
                    "entries": {
                        "Current": {"description": str(device.connections)},
                    }
                }
            },
        },
    }


# POST /mgmt/tm/sys/ucs
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_ucs.html
@router.post("/sys/ucs")
def sys_ucs(device: DeviceDep, body: UcsSaveCommand) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    name = body.name or f"nexusf5-{int(now())}.ucs"
    device.ucs_backups.append(name)
    return {
        "kind": "tm:sys:ucs:runstate",
        "command": body.command or "save",
        "name": name,
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/ucs/{name}",
    }


# POST /mgmt/tm/sys/software/image
# Real F5 uploads ISOs via chunked PUT to cm/autodeploy; the mock treats this
# endpoint as "register that an image with this name is available" so install
# roles can drive the flow without simulating a 2GB upload.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_image.html
@router.post("/sys/software/image")
def sys_software_image(device: DeviceDep, body: SoftwareImageInstallCommand) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    name = body.name or "BIGIP-17.1.0-0.0.0.iso"
    return {
        "kind": "tm:sys:software:image:imagestate",
        "name": name,
        "fileSize": "2 GB",
        "lastModified": "Mon Apr 22 12:00:00 2026",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/software/image/{name}",
    }


# GET /mgmt/tm/sys/software/volume
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_volume.html
@router.get("/sys/software/volume")
def sys_software_volume_list(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return {
        "kind": "tm:sys:software:volume:volumecollectionstate",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/software/volume",
        "items": [_volume_payload(device, v) for v in device.volumes],
    }


# GET /mgmt/tm/sys/software/volume/{volume}
# Install polling happens here. If the most recent install op targeting this
# volume is still in progress, status="in progress"; if it completed, the
# volume carries the new version; if it failed, status="failed".
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_volume.html
@router.get("/sys/software/volume/{volume}")
def sys_software_volume_get(device: DeviceDep, volume: str) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    v = device.volume_by_name(volume)
    if v is None:
        raise HTTPException(status_code=404, detail=f"volume {volume} not found")
    payload = _volume_payload(device, v)
    # If the most recent install op targeting this volume is not complete,
    # surface its status so callers know to keep polling.
    install_ops = [op for op in device.operations if op.target_volume == volume]
    if install_ops:
        latest = install_ops[-1]
        if latest.status == OperationStatus.IN_PROGRESS:
            payload["status"] = "in progress"
        elif latest.status == OperationStatus.FAILED:
            payload["status"] = "failed"
    return payload


# POST /mgmt/tm/sys/software/volume
# Kicks off async install to the named volume. Completes after
# MOCK_INSTALL_SECONDS. If chaos.fail_next_install is set, the op transitions
# to status="failed" on completion instead of updating the volume version.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_volume.html
@router.post("/sys/software/volume")
def sys_software_volume_install(device: DeviceDep, body: SoftwareVolumeCommand) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    if not body.name or not body.version:
        raise HTTPException(
            status_code=400,
            detail="name and version are required to start an install",
        )
    v = device.volume_by_name(body.name)
    if v is None:
        raise HTTPException(status_code=404, detail=f"volume {body.name} not found")
    op = device.start_install(target_volume=body.name, target_version=body.version)
    # Return the volume snapshot with in-progress status so clients that
    # treat POST-without-polling as synchronous see a recognisable shape.
    payload = _volume_payload(device, v)
    payload["status"] = "in progress"
    payload["operationId"] = op.id
    return payload


# PATCH /mgmt/tm/sys/software/volume/{volume}
# Flip the `active` flag. Setting active=true on a volume flips every other
# volume to active=false (exactly one active volume at any time). Rollback
# uses the same endpoint to flip back — the model is symmetric.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_volume.html
@router.patch("/sys/software/volume/{volume}")
def sys_software_volume_patch(
    device: DeviceDep,
    volume: str,
    body: VolumePatchCommand,
) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    v = device.volume_by_name(volume)
    if v is None:
        raise HTTPException(status_code=404, detail=f"volume {volume} not found")
    if body.active is True:
        device.activate_volume(volume)
    elif body.active is False:
        raise HTTPException(
            status_code=400,
            detail="cannot deactivate a volume directly; activate another instead",
        )
    return _volume_payload(device, v)


# POST /mgmt/tm/util/bash
# Catches `reboot` commands and starts the reboot window. Non-reboot bash
# commands echo back so real F5 automations are no-ops against the mock.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_util_bash.html
@router.post("/util/bash")
def util_bash(device: DeviceDep, body: UtilBashCommand) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    args = body.utilCmdArgs or ""
    if "reboot" in args:
        device.start_reboot()
    return {
        "kind": "tm:util:bash:runstate",
        "command": body.command or "run",
        "utilCmdArgs": args,
        "commandResult": "",
    }


# POST /mgmt/tm/sys/failover
# Toggle HA state. Phase 2 validates idempotency via the Ansible role.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_failover.html
@router.post("/sys/failover")
def sys_failover(device: DeviceDep, body: FailoverCommand) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    device.ha_state = HAState.STANDBY if device.ha_state == HAState.ACTIVE else HAState.ACTIVE
    return {
        "kind": "tm:sys:failover:runstate",
        "command": body.command or "run",
        "apiRawValues": {"apiAnonymous": f"state={device.ha_state.value}"},
    }
