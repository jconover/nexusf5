"""End-to-end upgrade + rollback tests driving ansible-playbook against the
live mock stack.

Coverage targets one device per scenario so tests don't share state:
  - bigip-lab-02: happy path
  - bigip-lab-03: fail_next_install chaos
  - bigip-lab-04: slow_reboot chaos (upgrade times out at boot-switch wait)
  - bigip-lab-05: post_boot_unhealthy chaos (upgrade fails at health gate)
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.integration.helpers import (
    inject_chaos,
    run_playbook,
    running_version,
)

TARGET_VERSION = "17.1.0"
TARGET_IMAGE = "BIGIP-17.1.0-0.0.3.iso"
UPGRADE_VARS = {
    "f5_target_version": TARGET_VERSION,
    "f5_target_image_name": TARGET_IMAGE,
}


def test_happy_upgrade_then_rollback_round_trip(
    reset_device_fixture: Callable[[str], None],
) -> None:
    host = "bigip-lab-02"
    reset_device_fixture(host)
    assert running_version(host) == "16.1.3"

    r = run_playbook("upgrade.yml", host, UPGRADE_VARS)
    assert r.returncode == 0, f"upgrade failed:\n{r.stdout}\n{r.stderr}"
    assert running_version(host) == TARGET_VERSION

    r = run_playbook("rollback.yml", host)
    assert r.returncode == 0, f"rollback failed:\n{r.stdout}\n{r.stderr}"
    assert running_version(host) == "16.1.3"


def test_chaos_fail_next_install_aborts_upgrade_before_reboot(
    reset_device_fixture: Callable[[str], None],
) -> None:
    host = "bigip-lab-03"
    reset_device_fixture(host)
    inject_chaos(host, "fail-next-install")

    r = run_playbook("upgrade.yml", host, UPGRADE_VARS)
    assert r.returncode != 0, "upgrade should have failed at image_install"
    # The install role raises its assertion pointing at runbook 02.
    assert "runbooks/02-image-install-stuck.md" in r.stdout

    # No reboot happened — version must still be the pre-upgrade one, and
    # rollback is therefore a no-op (already on prior version).
    assert running_version(host) == "16.1.3"


def test_chaos_slow_reboot_aborts_upgrade_at_boot_switch(
    reset_device_fixture: Callable[[str], None],
) -> None:
    host = "bigip-lab-04"
    reset_device_fixture(host)
    inject_chaos(host, "slow-reboot")

    # Tight poll budget — with MOCK_REBOOT_SECONDS=5 and multiplier=10
    # (from docker-compose + mock defaults), the slow reboot runs for 50s
    # while ansible waits at most ~3s before giving up.
    slow_vars = {
        **UPGRADE_VARS,
        "f5_boot_switch_poll_retries": "3",
        "f5_boot_switch_poll_delay": "1",
    }
    r = run_playbook("upgrade.yml", host, slow_vars, timeout=60.0)
    assert r.returncode != 0, "upgrade should have failed at boot_switch wait"
    # The assert-version task fires after exhaustion with runbook 03.
    assert "runbooks/03-post-boot-unhealthy.md" in r.stdout

    # reset-device clears rebooting_until so this device is immediately
    # reusable (otherwise the 50s window would block subsequent tests on
    # this hostname).


def test_chaos_post_boot_unhealthy_aborts_upgrade_at_health_gate(
    reset_device_fixture: Callable[[str], None],
) -> None:
    host = "bigip-lab-05"
    reset_device_fixture(host)
    inject_chaos(host, "post-boot-unhealthy")

    r = run_playbook("upgrade.yml", host, UPGRADE_VARS)
    assert r.returncode != 0, "upgrade should have failed at health_gate"
    # Device reaches target version (boot switch succeeded), but HA is red.
    assert running_version(host) == TARGET_VERSION
    assert "runbooks/03-post-boot-unhealthy.md" in r.stdout

    # Rollback restores the device to 16.1.3 with HA healthy (reset during
    # the rollback's own reboot — the chaos flag already consumed itself).
    r = run_playbook("rollback.yml", host)
    assert r.returncode == 0, f"rollback after unhealthy boot failed:\n{r.stdout}\n{r.stderr}"
    assert running_version(host) == "16.1.3"


@pytest.mark.parametrize(
    "host",
    ["bigip-lab-02", "bigip-lab-03", "bigip-lab-04", "bigip-lab-05"],
)
def test_reset_device_leaves_clean_state(
    host: str, reset_device_fixture: Callable[[str], None]
) -> None:
    # Not a chaos scenario — just confirms the between-test cleanup does
    # what it claims so the other three tests can rely on it.
    reset_device_fixture(host)
    assert running_version(host) == "16.1.3"
