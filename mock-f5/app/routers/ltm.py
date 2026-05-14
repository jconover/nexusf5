"""LTM (Local Traffic Manager) read endpoints used by the brownfield
config-discovery extractor (per ADR 007).

These endpoints serve the iControl REST GET responses an extractor walks
to construct AS3 declarations from existing device state. Response shapes
are sourced from F5 clouddocs and ACC v1.24.0 mapping tables; per-endpoint
citations live in `app/fixtures/ltm/`.

This router is read-only — no mutation, no chaos hooks (yet). Each handler
delegates to the fixture module for the response body and substitutes the
device hostname into selfLinks. Per-device customization is intentionally
deferred (YAGNI for Checkpoint 1 of the brownfield-extractor work).

Reference: https://clouddocs.f5.com/api/icontrol-rest/
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.deps import DeviceDep
from app.fixtures.ltm import (
    monitor_http,
    persistence_cookie,
    pool,
    pool_members,
    profile_clientssl,
    rule,
    virtual,
)
from app.state import DeviceState

router = APIRouter(prefix="/{hostname}/mgmt/tm/ltm")


def _reboot_guard(device: DeviceState) -> Response | None:
    """Return a 503 if the device is mid-reboot.

    Duplicated from `app.routers.icontrol._reboot_guard` rather than imported
    — both routers are siblings under `app.routers` and the cross-import
    would be the only coupling between them. Same rationale as
    `app.routers.extensions._reboot_guard`.
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


# GET /mgmt/tm/ltm/virtual
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_virtual.html
@router.get("/virtual")
def ltm_virtual(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return virtual.response(device.hostname)


# GET /mgmt/tm/ltm/pool
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_pool.html
@router.get("/pool")
def ltm_pool(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return pool.response(device.hostname)


# GET /mgmt/tm/ltm/pool/{name}/members
# Subcollection under pool. Real F5 returns members via either explicit GET
# on this path OR via `?expandSubcollections=true` on the pool list — we serve
# the explicit GET path here; expand-subcollections is deferred until the
# extractor needs it.
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_pool.html
@router.get("/pool/{name}/members")
def ltm_pool_members(device: DeviceDep, name: str) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    # Single-pool fixture: any pool name returns the same members. Future
    # work multiplexes by pool name when more than one pool is fixtured.
    _ = name
    return pool_members.response(device.hostname)


# GET /mgmt/tm/ltm/monitor/http
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_monitor_http.html
@router.get("/monitor/http")
def ltm_monitor_http(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return monitor_http.response(device.hostname)


# GET /mgmt/tm/ltm/profile/client-ssl
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_profile_client-ssl.html
@router.get("/profile/client-ssl")
def ltm_profile_clientssl(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return profile_clientssl.response(device.hostname)


# GET /mgmt/tm/ltm/persistence/cookie
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_persistence_cookie.html
@router.get("/persistence/cookie")
def ltm_persistence_cookie(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return persistence_cookie.response(device.hostname)


# GET /mgmt/tm/ltm/rule
# https://clouddocs.f5.com/api/icontrol-rest/APIRef_tm_ltm_rule.html
@router.get("/rule")
def ltm_rule(device: DeviceDep) -> Any:
    if (blocked := _reboot_guard(device)) is not None:
        return blocked
    return rule.response(device.hostname)
