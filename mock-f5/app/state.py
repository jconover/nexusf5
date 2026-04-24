"""Stateful device model for the mock iControl REST server.

Phase 3 multiplexes: one StateStore holds many DeviceState instances keyed
by hostname, and the routing layer dispatches by the first URL path segment
(`/{hostname}/mgmt/tm/...`). See docs/decisions/001-mock-topology.md.

Phase 2 added:
- Time-based transitions (install progress, reboot window) settled lazily
  via `DeviceState.advance()` at the top of every handler. No background
  threads — tests control time by tuning MOCK_INSTALL_SECONDS and
  MOCK_REBOOT_SECONDS to 0 (instant) or large values (timeout scenarios).
- `active` flag on Volume is the source of truth for "which volume boots
  next." On reboot completion, the active volume's version becomes the
  device's running version.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Timings read lazily so tests can set MOCK_*_SECONDS with monkeypatch.setenv
# and get instant effect without re-importing this module.


def install_seconds() -> float:
    return float(os.environ.get("MOCK_INSTALL_SECONDS", "30"))


def reboot_seconds() -> float:
    return float(os.environ.get("MOCK_REBOOT_SECONDS", "60"))


def slow_reboot_multiplier() -> float:
    """Multiplier applied to reboot duration when slow_reboot chaos is set."""
    return float(os.environ.get("MOCK_SLOW_REBOOT_MULTIPLIER", "10"))


class HAState(StrEnum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    FORCED_OFFLINE = "FORCED OFFLINE"


class SyncState(StrEnum):
    IN_SYNC = "In Sync"
    CHANGES_PENDING = "Changes Pending"
    DISCONNECTED = "Disconnected"


class OperationStatus(StrEnum):
    IN_PROGRESS = "in progress"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Volume:
    name: str
    active: bool
    version: str
    status: str = "complete"
    product: str = "BIG-IP"


@dataclass
class Operation:
    id: str
    kind: str
    status: OperationStatus
    started_at: float
    completes_at: float
    target_volume: str
    target_version: str
    will_fail: bool = False


@dataclass
class ChaosFlags:
    fail_next_install: bool = False
    slow_reboot: bool = False
    drift_postcheck: bool = False
    post_boot_unhealthy: bool = False


@dataclass
class DeviceState:
    hostname: str
    version: str = "16.1.3"
    build: str = "0.0.3"
    product: str = "BIG-IP"
    edition: str = "Point Release 3"
    ha_state: HAState = HAState.ACTIVE
    sync_state: SyncState = SyncState.IN_SYNC
    volumes: list[Volume] = field(default_factory=list)
    connections: int = 1024
    cpu_pct: float = 12.5
    mem_pct: float = 34.0
    operations: list[Operation] = field(default_factory=list)
    ucs_backups: list[str] = field(default_factory=list)
    chaos: ChaosFlags = field(default_factory=ChaosFlags)
    rebooting_until: float | None = None

    @classmethod
    def fresh(cls, hostname: str, version: str = "16.1.3") -> DeviceState:
        return cls(
            hostname=hostname,
            version=version,
            volumes=[
                Volume(name="HD1.1", active=True, version=version),
                Volume(name="HD1.2", active=False, version="16.1.2"),
            ],
        )

    def active_volume(self) -> Volume:
        for v in self.volumes:
            if v.active:
                return v
        raise RuntimeError(f"{self.hostname}: no active volume")

    def inactive_volume(self) -> Volume:
        for v in self.volumes:
            if not v.active:
                return v
        raise RuntimeError(f"{self.hostname}: no inactive volume")

    def volume_by_name(self, name: str) -> Volume | None:
        return next((v for v in self.volumes if v.name == name), None)

    def activate_volume(self, name: str) -> Volume:
        """Flip `active` so only the named volume is active. Rollback flows
        call this same path — the model is symmetric by design.
        """
        target = self.volume_by_name(name)
        if target is None:
            raise KeyError(name)
        for v in self.volumes:
            v.active = v.name == name
        return target

    def is_rebooting(self) -> bool:
        return self.rebooting_until is not None and now() < self.rebooting_until

    def start_install(self, target_volume: str, target_version: str) -> Operation:
        duration = install_seconds()
        op = Operation(
            id=str(uuid.uuid4()),
            kind="image-install",
            status=OperationStatus.IN_PROGRESS,
            started_at=now(),
            completes_at=now() + duration,
            target_volume=target_volume,
            target_version=target_version,
            will_fail=self.chaos.fail_next_install,
        )
        # Chaos is one-shot, consumed at install kickoff.
        self.chaos.fail_next_install = False
        self.operations.append(op)
        return op

    def start_reboot(self) -> None:
        duration = reboot_seconds()
        if self.chaos.slow_reboot:
            duration *= slow_reboot_multiplier()
            # Slow-reboot chaos is one-shot too; a second reboot during the
            # same test sequence uses the normal timing unless re-enabled.
            self.chaos.slow_reboot = False
        self.rebooting_until = now() + duration

    def advance(self) -> None:
        """Settle any pending time-based transitions to "now".

        Called at the top of every iControl REST handler so state is always
        current when a response is built. This keeps the mock deterministic
        (no background threads, no timing jitter) and makes MOCK_*_SECONDS=0
        produce instant completion for fast tests.
        """
        current = now()
        for op in self.operations:
            if op.status != OperationStatus.IN_PROGRESS:
                continue
            if current >= op.completes_at:
                if op.will_fail:
                    op.status = OperationStatus.FAILED
                else:
                    op.status = OperationStatus.COMPLETE
                    vol = self.volume_by_name(op.target_volume)
                    if vol is not None:
                        vol.version = op.target_version
                        vol.status = "complete"
        if self.rebooting_until is not None and current >= self.rebooting_until:
            self.rebooting_until = None
            self.version = self.active_volume().version
            if self.chaos.post_boot_unhealthy:
                self.ha_state = HAState.FORCED_OFFLINE
                self.sync_state = SyncState.DISCONNECTED
                # Single-shot: a subsequent healthy reboot (e.g. during
                # rollback) will clear the offline state below.
                self.chaos.post_boot_unhealthy = False
            else:
                # Healthy reboot clears transient HA/sync faults. Approximates
                # the real-world behaviour where a fresh boot to a known-good
                # volume recovers peer sync and failover state. Rollback
                # depends on this to return the device to ACTIVE.
                self.ha_state = HAState.ACTIVE
                self.sync_state = SyncState.IN_SYNC


class StateStore:
    """Multi-device state store keyed by hostname."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceState] = {}

    def register(self, device: DeviceState) -> None:
        self._devices[device.hostname] = device

    def get(self, hostname: str) -> DeviceState:
        return self._devices[hostname]

    def has(self, hostname: str) -> bool:
        return hostname in self._devices

    def all(self) -> list[DeviceState]:
        return list(self._devices.values())


def build_store_from_env() -> StateStore:
    """Single-device bootstrap: read hostname/version from env.

    Used by the in-process unit tests (the `client` fixture boots the app
    with no manifest set, so this runs) and as a fallback when the
    container is started without `MOCK_F5_MANIFEST`. Production docker
    compose uses `build_store_from_manifest` instead.
    """
    hostname = os.environ.get("MOCK_F5_HOSTNAME", "bigip-lab-01")
    version = os.environ.get("MOCK_F5_VERSION", "16.1.3")
    store = StateStore()
    store.register(DeviceState.fresh(hostname=hostname, version=version))
    return store


def build_store_from_manifest(path: str | Path) -> StateStore:
    """Multi-device bootstrap: read a JSON manifest listing devices.

    Manifest shape:
        {
          "devices": [
            {"hostname": "bigip-lab-01", "version": "16.1.3"},
            ...
          ]
        }

    `version` is optional and defaults to 16.1.3 to match fresh-device
    behaviour. Duplicate hostnames raise ValueError so misconfigured
    manifests fail fast on startup rather than producing a half-populated
    store.
    """
    data = json.loads(Path(path).read_text())
    devices = data.get("devices", [])
    if not devices:
        raise ValueError(f"manifest {path} has no devices")
    store = StateStore()
    seen: set[str] = set()
    for entry in devices:
        hostname = entry["hostname"]
        if hostname in seen:
            raise ValueError(f"manifest {path} has duplicate hostname: {hostname}")
        seen.add(hostname)
        version = entry.get("version", "16.1.3")
        store.register(DeviceState.fresh(hostname=hostname, version=version))
    return store


def now() -> float:
    return time.time()
