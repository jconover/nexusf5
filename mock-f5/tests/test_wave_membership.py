"""Wave membership invariants for ansible/inventory/hosts.yml.

Phase 3 drives waves from the inventory structure. Any of these failure
modes would silently skip or double-upgrade devices in production:

- A hostname accidentally lands in two waves.
- The merged wave set doesn't cover every device in `lab`.
- A "wave" group exists in hosts.yml but isn't one of the expected four.

Each is cheap to prevent and expensive to debug mid-rollout, so they are
asserted here and enforced in `make test-unit`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "ansible" / "inventory" / "hosts.yml"

WAVE_GROUPS = ("canary", "wave_1", "wave_2", "wave_3")
EXPECTED_DEVICE_COUNT = 50


def _load_inventory() -> dict:
    with INVENTORY.open() as f:
        return yaml.safe_load(f)


def _hosts_in(group: dict | None) -> set[str]:
    if not group:
        return set()
    return set((group.get("hosts") or {}).keys())


@pytest.fixture(scope="module")
def inventory() -> dict:
    return _load_inventory()


@pytest.fixture(scope="module")
def groups(inventory: dict) -> dict[str, dict]:
    return inventory["all"]["children"]


def test_all_four_wave_groups_exist(groups: dict[str, dict]) -> None:
    missing = [g for g in WAVE_GROUPS if g not in groups]
    assert not missing, f"missing wave groups in hosts.yml: {missing}"


def test_no_device_appears_in_two_waves(groups: dict[str, dict]) -> None:
    # Build hostname -> list of waves it appears in.
    membership: dict[str, list[str]] = {}
    for wave in WAVE_GROUPS:
        for host in _hosts_in(groups.get(wave)):
            membership.setdefault(host, []).append(wave)
    overlaps = {h: w for h, w in membership.items() if len(w) > 1}
    assert not overlaps, f"devices in multiple waves (would be upgraded twice): {overlaps}"


def test_every_lab_device_is_in_exactly_one_wave(groups: dict[str, dict]) -> None:
    # `lab` is a parent group composed of the four wave children; its
    # effective host set is the union of the wave host sets.
    union: set[str] = set()
    for wave in WAVE_GROUPS:
        union |= _hosts_in(groups.get(wave))
    assert len(union) == EXPECTED_DEVICE_COUNT, (
        f"expected {EXPECTED_DEVICE_COUNT} devices across all waves, got {len(union)}"
    )


def test_wave_sizes_match_phase_3_plan(groups: dict[str, dict]) -> None:
    # Phase 3 split per TODO.md: canary (5) + wave_1 (45), with wave_2 /
    # wave_3 as empty placeholders for the 500-device scale target. The
    # size check catches drift — if someone adds a device to wave_1 without
    # growing canary, or populates wave_2 without a TODO update, this
    # test flags it so the plan and the inventory stay in sync.
    sizes = {wave: len(_hosts_in(groups.get(wave))) for wave in WAVE_GROUPS}
    assert sizes["canary"] == 5, f"canary should be 5 devices, got {sizes['canary']}"
    assert sizes["wave_1"] == 45, f"wave_1 should be 45 devices, got {sizes['wave_1']}"
    assert sizes["wave_2"] == 0, f"wave_2 should be empty in Phase 3, got {sizes['wave_2']}"
    assert sizes["wave_3"] == 0, f"wave_3 should be empty in Phase 3, got {sizes['wave_3']}"
    assert sum(sizes.values()) == EXPECTED_DEVICE_COUNT, f"total wave population mismatch: {sizes}"


def test_hostnames_follow_bigip_lab_nn_convention(groups: dict[str, dict]) -> None:
    # CLAUDE.md non-negotiable: device names follow `bigip-{site}-{number}`.
    bad: list[str] = []
    for wave in WAVE_GROUPS:
        for host in _hosts_in(groups.get(wave)):
            prefix, _, suffix = host.rpartition("-")
            if prefix != "bigip-lab" or not (suffix.isdigit() and len(suffix) == 2):
                bad.append(host)
    assert not bad, f"hostnames violating bigip-lab-NN convention: {bad}"
