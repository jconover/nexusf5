"""Stateful device model for the mock iControl REST server.

Designed for Phase 3 multiplexing: StateStore is a multi-device map keyed by
hostname. Phase 1 registers exactly one device per container via
MOCK_F5_HOSTNAME, but the contract of this module does not change when
Phase 3 routing switches to Host-header dispatch.

See docs/decisions/001-mock-topology.md.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum


class HAState(StrEnum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    FORCED_OFFLINE = "FORCED OFFLINE"


class SyncState(StrEnum):
    IN_SYNC = "In Sync"
    CHANGES_PENDING = "Changes Pending"
    DISCONNECTED = "Disconnected"


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
    status: str
    started_at: float
    completes_at: float
    target_volume: str | None = None


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
    in_progress_ops: list[Operation] = field(default_factory=list)
    ucs_backups: list[str] = field(default_factory=list)
    chaos: ChaosFlags = field(default_factory=ChaosFlags)

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


class StateStore:
    """Multi-device state store.

    Phase 1 registers exactly one device per container. Phase 3 will register
    many devices into a single container and route by Host header; this class
    does not change.
    """

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

    def primary(self) -> DeviceState:
        """Phase 1 convenience: return the single registered device.

        Phase 3 routing dependency must use Host-header lookup instead.
        """
        devices = self.all()
        if len(devices) != 1:
            raise RuntimeError(
                f"StateStore.primary() assumes exactly one device; found {len(devices)}"
            )
        return devices[0]


def build_store_from_env() -> StateStore:
    """Phase 1 bootstrap: read hostname/version from env, register one device."""
    hostname = os.environ.get("MOCK_F5_HOSTNAME", "bigip-lab-01")
    version = os.environ.get("MOCK_F5_VERSION", "16.1.3")
    store = StateStore()
    store.register(DeviceState.fresh(hostname=hostname, version=version))
    return store


def now() -> float:
    return time.time()
