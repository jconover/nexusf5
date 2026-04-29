#!/usr/bin/env python3
"""Integration test wrapper for `make integration`.

Hard 45-minute wall-clock timeout. Teardown runs unconditionally — success,
failure, timeout, SIGINT — via a try/finally that calls `terraform destroy`
and falls back to a tag-filtered EC2 terminate-instances if destroy itself
fails. The wrapper is in Python rather than bash because bash trap reliability
under signal interactions (especially SIGALRM compounding with subprocess
waits) is fragile, and a wedged integration run leaving live VEs costs real
money.

Phases (each one's failure short-circuits to teardown):
  1. terraform init + apply  (creates the VE pair, EIPs, SG, key pair)
  2. wait for iControl REST  (cloud-init runs tmsh on first boot; ~3-6 min)
  3. ansible preflight       (per-device version + HA + sync checks)
  4. terraform destroy       (always)
  5. nuclear teardown        (only if step 4 returned non-zero)

Configuration via environment variables (all optional, defaults for laptop runs):
  AWS_PROFILE       default "outlook"
  AWS_REGION        default "us-east-2"
  INTEGRATION_TIMEOUT_SECONDS   default 2700 (45 minutes)
  INTEGRATION_VE_READY_TIMEOUT  default 900  (15 minutes per VE)
  INTEGRATION_SKIP_DESTROY      set to "1" to leave the VE pair running for
                                 manual debugging. The nuclear teardown
                                 still runs at process exit; this only
                                 skips the planned destroy. Use sparingly.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TERRAFORM_ENV = REPO_ROOT / "terraform" / "environments" / "integration"
ANSIBLE_DIR = REPO_ROOT / "ansible"
BUILD_DIR = REPO_ROOT / "build" / "integration"

AWS_PROFILE = os.environ.get("AWS_PROFILE", "outlook")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
TIMEOUT_SECONDS = int(os.environ.get("INTEGRATION_TIMEOUT_SECONDS", str(45 * 60)))
VE_READY_TIMEOUT = int(os.environ.get("INTEGRATION_VE_READY_TIMEOUT", str(15 * 60)))
SKIP_DESTROY = os.environ.get("INTEGRATION_SKIP_DESTROY") == "1"


class IntegrationTimeout(Exception):
    """Raised when the wall-clock hard timeout fires."""


def log(msg: str) -> None:
    """Single-line stamped output. Stays readable when interleaved with
    subprocess streams."""
    print(f"[wrapper {datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def aws_env() -> dict[str, str]:
    env = os.environ.copy()
    env["AWS_PROFILE"] = AWS_PROFILE
    env["AWS_REGION"] = AWS_REGION
    return env


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None,
        check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env or aws_env(),
        capture_output=capture,
        text=True,
    )
    if check and proc.returncode != 0:
        if capture:
            sys.stderr.write(proc.stdout or "")
            sys.stderr.write(proc.stderr or "")
        raise RuntimeError(f"command failed (exit {proc.returncode}): {' '.join(cmd)}")
    return proc


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")


def terraform_apply(run_id: str) -> None:
    env = aws_env()
    env["TF_VAR_run_id"] = run_id
    run(["terraform", "init", "-input=false"], cwd=TERRAFORM_ENV, env=env)
    run(["terraform", "apply", "-auto-approve", "-input=false", "-no-color"],
        cwd=TERRAFORM_ENV, env=env)


def terraform_outputs() -> dict[str, Any]:
    proc = run(["terraform", "output", "-json"], cwd=TERRAFORM_ENV, capture=True)
    return json.loads(proc.stdout)


def wait_for_icontrol(host: str, password: str, timeout: int) -> None:
    """Poll the version endpoint until 200. F5 VE cloud-init takes 3-6 minutes
    to bring iControl REST up; we accept ~15 min before giving up."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    creds = base64.b64encode(f"admin:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}

    url = f"https://{host}/mgmt/tm/sys/version"
    deadline = time.time() + timeout
    last_err: str = ""
    sleep_seconds = 10

    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                if resp.status == 200:
                    log(f"  {host}: iControl REST ready")
                    return
                last_err = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code == 401:
                last_err += " (admin password not set yet — cloud-init may still be running)"
        except (urllib.error.URLError, ConnectionResetError, OSError, ssl.SSLError) as e:
            last_err = type(e).__name__
        time.sleep(sleep_seconds)
        # Exponential-ish backoff capped at 30s.
        sleep_seconds = min(sleep_seconds + 5, 30)

    raise RuntimeError(f"{host} did not become ready within {timeout}s (last: {last_err})")


def wait_for_all_ves(ve_endpoints: dict[str, dict[str, Any]], password: str) -> None:
    log(f"waiting up to {VE_READY_TIMEOUT}s per VE for iControl REST")
    for hostname, info in ve_endpoints.items():
        wait_for_icontrol(info["mgmt_public_ip"], password, VE_READY_TIMEOUT)


def run_preflight(password: str) -> None:
    env = aws_env()
    env["F5_API_PASSWORD"] = password
    # ANSIBLE_LOCALHOST_WARNING and INTERPRETER_PYTHON_FALLBACK_OK silence
    # the noise when the inventory uses ansible_connection=local.
    env["ANSIBLE_LOCALHOST_WARNING"] = "False"
    env["ANSIBLE_INTERPRETER_PYTHON"] = "auto_silent"
    inventory = BUILD_DIR / "inventory.yml"
    run(
        [
            "ansible-playbook",
            "-i", str(inventory),
            "playbooks/preflight.yml",
            "--limit", "integration",
        ],
        cwd=ANSIBLE_DIR,
        env=env,
    )


def terraform_destroy() -> bool:
    if SKIP_DESTROY:
        log("INTEGRATION_SKIP_DESTROY=1 — skipping planned destroy (nuclear teardown still runs at exit)")
        return False
    proc = run(
        ["terraform", "destroy", "-auto-approve", "-input=false", "-no-color"],
        cwd=TERRAFORM_ENV,
        check=False,
    )
    return proc.returncode == 0


def nuclear_teardown() -> None:
    """Tag-filtered EC2 terminate fallback. Runs when terraform destroy
    failed or was skipped. Idempotent — terminates whatever's tagged
    Project=nexusf5 + AutoDestroy=true in non-terminal state, regardless
    of which run created it."""
    log("nuclear teardown: scanning for AutoDestroy=true instances")
    desc = run(
        [
            "aws", "ec2", "describe-instances",
            "--region", AWS_REGION,
            "--filters",
            "Name=tag:Project,Values=nexusf5",
            "Name=tag:AutoDestroy,Values=true",
            "Name=instance-state-name,Values=pending,running,stopping,stopped",
            "--query", "Reservations[].Instances[].InstanceId",
            "--output", "text",
        ],
        capture=True,
        check=False,
    )
    instance_ids = desc.stdout.split() if desc.returncode == 0 else []
    if not instance_ids:
        log("  no instances to terminate")
        return
    log(f"  terminating {len(instance_ids)} instance(s): {' '.join(instance_ids)}")
    run(
        ["aws", "ec2", "terminate-instances", "--region", AWS_REGION,
         "--instance-ids", *instance_ids],
        check=False,
    )


def cleanup_local_secrets() -> None:
    """Remove the chmod-600 password file, ssh key, and rendered inventory.
    Wrapper deliberately doesn't blow away build/integration/ wholesale —
    terraform's local state and plan files live there too and may help
    diagnose the next run."""
    for path in (BUILD_DIR / "admin_password",
                 BUILD_DIR / "ssh_key",
                 BUILD_DIR / "inventory.yml"):
        try:
            if path.exists():
                path.unlink()
                log(f"  removed {path.relative_to(REPO_ROOT)}")
        except OSError as e:
            log(f"  could not remove {path}: {e}")


def install_alarm() -> None:
    """SIGALRM-based hard timeout. Linux-only; Windows isn't supported and
    isn't a target — the integration env runs on the GHA Linux runner and
    on Linux laptops."""
    def handler(signum: int, _frame: Any) -> None:
        raise IntegrationTimeout(
            f"{TIMEOUT_SECONDS}s wall-clock timeout reached")
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(TIMEOUT_SECONDS)


def main() -> int:
    run_id = make_run_id()
    log(f"=== nexusf5 integration run {run_id} ===")
    log(f"timeout {TIMEOUT_SECONDS}s, profile={AWS_PROFILE}, region={AWS_REGION}")

    install_alarm()

    failed = False
    failure_reason = ""

    try:
        terraform_apply(run_id)
        outputs = terraform_outputs()
        ve_endpoints = outputs["ve_endpoints"]["value"]
        admin_password = (BUILD_DIR / "admin_password").read_text().strip()

        log(f"VEs provisioned: {list(ve_endpoints.keys())}")
        for h, info in ve_endpoints.items():
            log(f"  {h}: {info['mgmt_public_ip']} (ami {info['ami_name']})")

        wait_for_all_ves(ve_endpoints, admin_password)
        run_preflight(admin_password)

    except IntegrationTimeout as e:
        failed = True
        failure_reason = str(e)
        log(f"!!! TIMEOUT: {failure_reason}")
    except KeyboardInterrupt:
        failed = True
        failure_reason = "SIGINT"
        log("!!! interrupted by user")
    except Exception as e:
        failed = True
        failure_reason = f"{type(e).__name__}: {e}"
        log(f"!!! integration test failed: {failure_reason}")
    finally:
        signal.alarm(0)  # cancel the apply-phase timeout
        log("=== teardown ===")
        try:
            destroyed = terraform_destroy()
        except Exception as e:
            log(f"terraform destroy raised: {e}")
            destroyed = False
        if not destroyed:
            try:
                nuclear_teardown()
            except Exception as e:
                log(f"nuclear teardown raised: {e}")
        cleanup_local_secrets()

    if failed:
        log(f"=== integration FAILED ({failure_reason}) ===")
        return 1
    log("=== integration PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
