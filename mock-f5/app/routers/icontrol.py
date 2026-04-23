"""iControl REST endpoint subset used by the NexusF5 upgrade runbook.

Every handler documents the upstream F5 API path it mirrors.
Reference: https://clouddocs.f5.com/api/icontrol-rest/
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.deps import DeviceDep
from app.models import (
    FailoverCommand,
    SoftwareImageInstallCommand,
    SoftwareVolumeCommand,
    UcsSaveCommand,
)
from app.state import HAState, Operation, now

router = APIRouter(prefix="/mgmt/tm")


# GET /mgmt/tm/sys/version
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_version.html
@router.get("/sys/version")
def sys_version(device: DeviceDep) -> dict[str, Any]:
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
def cm_failover_status(device: DeviceDep) -> dict[str, Any]:
    color = "green" if device.ha_state == HAState.ACTIVE else "yellow"
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
def cm_sync_status(device: DeviceDep) -> dict[str, Any]:
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
def sys_performance_all_stats(device: DeviceDep) -> dict[str, Any]:
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
def sys_ucs(device: DeviceDep, body: UcsSaveCommand) -> dict[str, Any]:
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
# endpoint as "register that an image with this name is available" so Phase 2
# install roles can drive the flow without simulating a 2GB upload.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_image.html
@router.post("/sys/software/image")
def sys_software_image(
    device: DeviceDep,
    body: SoftwareImageInstallCommand,
) -> dict[str, Any]:
    name = body.name or "BIGIP-17.1.0-0.0.0.iso"
    return {
        "kind": "tm:sys:software:image:imagestate",
        "name": name,
        "fileSize": "2 GB",
        "lastModified": "Mon Apr 22 12:00:00 2026",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/software/image/{name}",
    }


# POST /mgmt/tm/sys/software/volume
# Phase 1: records an in-progress op, then marks it complete synchronously so
# the scaffolding works. Phase 2 introduces configurable async timing and
# consumes `chaos.fail_next_install` to simulate install failures (wired here
# already so the hook is in place).
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_software_volume.html
@router.post("/sys/software/volume")
def sys_software_volume(
    device: DeviceDep,
    body: SoftwareVolumeCommand,
) -> dict[str, Any]:
    if device.chaos.fail_next_install:
        device.chaos.fail_next_install = False
        raise HTTPException(status_code=500, detail="mock: image install failed (chaos)")

    op = Operation(
        id=str(uuid.uuid4()),
        kind="image-install",
        status="complete",
        started_at=now(),
        completes_at=now(),
        target_volume=body.name,
    )
    device.in_progress_ops.append(op)

    if body.version and body.name:
        for v in device.volumes:
            if v.name == body.name:
                v.version = body.version
                v.status = "complete"
                break

    return {
        "kind": "tm:sys:software:volume:volumestate",
        "name": body.name,
        "version": body.version,
        "status": "complete",
        "selfLink": f"https://{device.hostname}/mgmt/tm/sys/software/volume/{body.name}",
    }


# POST /mgmt/tm/sys/failover
# Phase 1: toggle HA state. Phase 2 will model peer-aware transitions.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_sys_failover.html
@router.post("/sys/failover")
def sys_failover(device: DeviceDep, body: FailoverCommand) -> dict[str, Any]:
    device.ha_state = HAState.STANDBY if device.ha_state == HAState.ACTIVE else HAState.ACTIVE
    return {
        "kind": "tm:sys:failover:runstate",
        "command": body.command or "run",
        "apiRawValues": {"apiAnonymous": f"state={device.ha_state.value}"},
    }
