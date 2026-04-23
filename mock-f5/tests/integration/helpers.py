"""Helpers shared by integration tests.

Kept separate from conftest.py so test files can import without reaching
into pytest's fixture discovery internals.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSIBLE_DIR = REPO_ROOT / "ansible"

DEVICE_PORTS = {
    "bigip-lab-01": 8101,
    "bigip-lab-02": 8102,
    "bigip-lab-03": 8103,
    "bigip-lab-04": 8104,
    "bigip-lab-05": 8105,
}


def mock_base(hostname: str) -> str:
    return f"http://localhost:{DEVICE_PORTS[hostname]}"


def mock_reachable() -> bool:
    try:
        r = httpx.get("http://localhost:8101/health", timeout=2.0)
    except (httpx.HTTPError, OSError):
        return False
    return r.status_code == 200


def reset_device(hostname: str) -> None:
    url = f"{mock_base(hostname)}/_chaos/{hostname}/reset-device"
    r = httpx.post(url, timeout=5.0)
    r.raise_for_status()


def inject_chaos(hostname: str, scenario: str) -> None:
    url = f"{mock_base(hostname)}/_chaos/{hostname}/{scenario}"
    r = httpx.post(url, timeout=5.0)
    r.raise_for_status()


def running_version(hostname: str) -> str:
    r = httpx.get(f"{mock_base(hostname)}/mgmt/tm/sys/version", timeout=5.0)
    r.raise_for_status()
    entry = next(iter(r.json()["entries"].values()))
    description: str = entry["nestedStats"]["entries"]["Version"]["description"]
    return description


def run_playbook(
    playbook: str,
    host: str,
    extra_vars: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ansible-playbook",
        "-i",
        "inventory/hosts.yml",
        f"playbooks/{playbook}",
        "--limit",
        host,
    ]
    for k, v in (extra_vars or {}).items():
        cmd.extend(["-e", f"{k}={v}"])
    return subprocess.run(
        cmd,
        cwd=ANSIBLE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
