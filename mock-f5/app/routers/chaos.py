"""Operational (health, metrics) and chaos-injection endpoints.

Chaos endpoints scope to a hostname in the URL. Phase 1 requires the hostname
to match the single device this container represents; Phase 3 will dispatch
to any multiplexed device with the same URL shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    generate_latest,
)

from app.deps import StoreDep
from app.state import DeviceState, StateStore

router = APIRouter()


@router.get("/health")
def health(store: StoreDep) -> dict[str, object]:
    return {
        "status": "ok",
        "devices": [d.hostname for d in store.all()],
    }


@router.get("/metrics")
def metrics(store: StoreDep) -> Response:
    registry = CollectorRegistry()
    device_info = Gauge(
        "nexusf5_mock_device_info",
        "Static per-device info (always 1; labels carry state)",
        labelnames=("hostname", "version", "ha_state", "sync_state"),
        registry=registry,
    )
    connections_gauge = Gauge(
        "nexusf5_mock_connections",
        "Simulated active connections",
        labelnames=("hostname",),
        registry=registry,
    )
    cpu_gauge = Gauge(
        "nexusf5_mock_cpu_pct",
        "Simulated CPU percent",
        labelnames=("hostname",),
        registry=registry,
    )
    for d in store.all():
        device_info.labels(d.hostname, d.version, d.ha_state.value, d.sync_state.value).set(1)
        connections_gauge.labels(d.hostname).set(d.connections)
        cpu_gauge.labels(d.hostname).set(d.cpu_pct)
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


def _resolve(store: StateStore, hostname: str) -> DeviceState:
    if not store.has(hostname):
        raise HTTPException(status_code=404, detail=f"unknown device: {hostname}")
    return store.get(hostname)


@router.post("/_chaos/{hostname}/fail-next-install")
def chaos_fail_next_install(hostname: str, store: StoreDep) -> dict[str, str]:
    device = _resolve(store, hostname)
    device.chaos.fail_next_install = True
    return {"hostname": hostname, "flag": "fail_next_install", "value": "true"}


@router.post("/_chaos/{hostname}/slow-reboot")
def chaos_slow_reboot(hostname: str, store: StoreDep) -> dict[str, str]:
    device = _resolve(store, hostname)
    device.chaos.slow_reboot = True
    return {"hostname": hostname, "flag": "slow_reboot", "value": "true"}


@router.post("/_chaos/{hostname}/drift-postcheck")
def chaos_drift_postcheck(hostname: str, store: StoreDep) -> dict[str, str]:
    device = _resolve(store, hostname)
    device.chaos.drift_postcheck = True
    return {"hostname": hostname, "flag": "drift_postcheck", "value": "true"}


@router.post("/_chaos/{hostname}/post-boot-unhealthy")
def chaos_post_boot_unhealthy(hostname: str, store: StoreDep) -> dict[str, str]:
    device = _resolve(store, hostname)
    device.chaos.post_boot_unhealthy = True
    return {"hostname": hostname, "flag": "post_boot_unhealthy", "value": "true"}


@router.post("/_chaos/{hostname}/reset")
def chaos_reset(hostname: str, store: StoreDep) -> dict[str, str]:
    device = _resolve(store, hostname)
    device.chaos.fail_next_install = False
    device.chaos.slow_reboot = False
    device.chaos.drift_postcheck = False
    device.chaos.post_boot_unhealthy = False
    return {"hostname": hostname, "flag": "all", "value": "false"}
