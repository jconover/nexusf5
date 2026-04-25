#!/usr/bin/env python3
"""List the devices in a wave group as JSON for a GitHub Actions matrix.

The reusable upgrade-wave workflow shells out to this to build its
device matrix from the same inventory Ansible reads, so the workflow
and the runbook can't diverge on which devices belong to a wave.

Usage:
    python tools/list_wave_devices.py --wave canary
    -> ["bigip-lab-01","bigip-lab-02","bigip-lab-03","bigip-lab-04","bigip-lab-05"]

Exit code is non-zero if the wave group is empty — an empty matrix
would silently produce a no-op job, which is exactly the "looks green,
did nothing" failure class the gate is trying to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def list_devices(inventory_path: Path, wave: str) -> list[str]:
    data = yaml.safe_load(inventory_path.read_text())
    children = data["all"]["children"]
    if wave not in children:
        raise KeyError(f"wave group '{wave}' not found in {inventory_path}")
    group = children[wave] or {}
    return list((group.get("hosts") or {}).keys())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wave", required=True)
    p.add_argument(
        "--inventory",
        default="ansible/inventory/hosts.yml",
        type=Path,
        help="Inventory YAML (default: ansible/inventory/hosts.yml from repo root).",
    )
    args = p.parse_args()

    try:
        devices = list_devices(args.inventory, args.wave)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not devices:
        print(
            f"wave '{args.wave}' has no hosts in {args.inventory}; refusing "
            "to emit an empty matrix (would silently produce a no-op wave).",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(devices))
    return 0


if __name__ == "__main__":
    sys.exit(main())
