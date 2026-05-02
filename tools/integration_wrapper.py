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
  2. wait for iControl REST  (BIG-IP cloud-init runs f5-bigip-runtime-init,
                              which waits for mcpd then posts a DO
                              declaration setting admin password +
                              hostname; budget 25 min per VE)
  3. ansible preflight       (per-device version + HA + sync checks)
  4. diagnostic capture      (only on failure; SSH-fetches runtime-init
                              and iControl REST logs from both VEs to
                              build/integration/runs/{run_id}/{host}/.
                              Isolated try/except — its own failure
                              must not block destroy.)
  5. terraform destroy       (always)
  6. nuclear teardown        (only if step 5 returned non-zero)

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
import shlex
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
VE_READY_TIMEOUT = int(os.environ.get("INTEGRATION_VE_READY_TIMEOUT", str(25 * 60)))
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


def terraform_admin_password() -> str:
    """Read the per-run admin password from terraform's sensitive output.
    Threaded through `terraform output -json` rather than as a CLI arg so
    it never appears in process listings or shell history. Same password
    for both VEs (single random_password resource in main.tf)."""
    proc = run(
        ["terraform", "output", "-raw", "admin_password"],
        cwd=TERRAFORM_ENV, capture=True,
    )
    return proc.stdout.strip()


def tcp_probe(host: str, port: int, connect_timeout: float = 5.0) -> str | None:
    """One-shot TCP connect. Returns None on success, error string on failure."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=connect_timeout):
            return None
    except (OSError, socket.timeout) as e:
        return type(e).__name__


def fetch_console_output(instance_id: str) -> str:
    """Pull the EC2 console output as a diagnostic on a wedged VE. F5 BIG-IP
    VE writes its boot progress (and cloud-init failures) to the serial
    console, which AWS captures and exposes via this API. Truncated to keep
    the wrapper log readable."""
    proc = run(
        ["aws", "ec2", "get-console-output",
         "--region", AWS_REGION,
         "--instance-id", instance_id,
         "--query", "Output",
         "--output", "text"],
        capture=True,
        check=False,
    )
    if proc.returncode != 0:
        return f"(get-console-output failed: rc={proc.returncode})"
    return proc.stdout.strip() or "(empty)"


def wait_for_icontrol(host: str, instance_id: str, password: str, timeout: int,
                      mgmt_https_port: int,
                      ssh_key: Path | None = None,
                      hostname: str | None = None,
                      early_fetch_dir: Path | None = None) -> None:
    """Poll iControl REST until 200. Three-layered diagnostic so a failure
    points clearly at host-down vs port-closed vs auth/version-up problems:
      1. TCP connect to port 22 — instance is alive at all
      2. TCP connect to mgmt_https_port — iControl REST listener is up
         (BIG-IP 17.1.x default 8443; older releases used 443)
      3. HTTP GET /mgmt/tm/sys/version — fully ready

    F5 VE first boot can take 15-20 min on cold start; the default
    VE_READY_TIMEOUT is 25 min to accommodate the slow tail. The TCP probes
    use 5s connect timeout so a closed port surfaces as "ConnectionRefused"
    not "URLError" and a host-unreachable surfaces as "ENETUNREACH" etc.
    Useful when diagnosing "did the instance ever come up?"."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    creds = base64.b64encode(f"admin:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}"}

    url = f"https://{host}:{mgmt_https_port}/mgmt/tm/sys/version"
    deadline = time.time() + timeout
    last_err: str = "no probe yet"
    last_phase: str = "init"
    ssh_seen = False
    https_seen = False
    early_fetch_done = False
    sleep_seconds = 10

    while time.time() < deadline:
        elapsed = int(time.time() - (deadline - timeout))

        # Phase 1: TCP/22 probe — confirms the instance has booted enough
        # that sshd is listening. Logged on first success only.
        ssh_err = tcp_probe(host, 22)
        if ssh_err is None and not ssh_seen:
            ssh_seen = True
            log(f"  {host}: tcp/22 reachable at +{elapsed}s")
        elif ssh_err is not None:
            last_err = f"tcp/22 {ssh_err}"
            last_phase = "ssh-tcp"

        # Phase 2: tcp/{mgmt_https_port} probe — confirms iControl REST
        # listener up. Port is BIG-IP 17.1.x default 8443 (configurable
        # via the ve-instance module's mgmt_https_port variable).
        https_err = tcp_probe(host, mgmt_https_port)
        if https_err is None and not https_seen:
            https_seen = True
            log(f"  {host}: tcp/{mgmt_https_port} reachable at +{elapsed}s")
        elif https_err is not None:
            last_err = f"tcp/{mgmt_https_port} {https_err}"
            last_phase = "https-tcp"
            time.sleep(sleep_seconds)
            sleep_seconds = min(sleep_seconds + 5, 30)
            continue

        # Early diagnostic fetch: triggered the first time both ssh and
        # https probes have succeeded. Goal is to capture runtime-init's
        # working logs while the VE is in the stable mcpd-up-but-still-
        # bootstrapping window — independent of whether iControl REST
        # eventually returns 200. Iter 4 showed that late-fetch (post-
        # timeout) can break in non-obvious ways (tmsh `run /util bash`
        # rejected as "invalid arguments") while iter 3's late-fetch
        # against a quiescent post-failure VE worked fine. Hypothesis:
        # SSH-escape reliability is state-dependent. Early fetch tests
        # the more-stable window before runtime-init does heavy work.
        if (ssh_seen and https_seen and not early_fetch_done
                and ssh_key is not None and hostname is not None
                and early_fetch_dir is not None):
            early_fetch_done = True
            log(f"  {hostname}: early diagnostic fetch at +{elapsed}s")
            if SKIP_DESTROY:
                log( "  [automated SSH-fetch will likely fail in SKIP_DESTROY mode —")
                log( "   manual SSH is the diagnostic path; ignore the rc=1 output below]")
            try:
                ssh_fetch_diagnostics(
                    ssh_key,
                    {hostname: {"mgmt_public_ip": host}},
                    early_fetch_dir,
                )
            except Exception as e:
                log(f"  early fetch raised (non-fatal): {type(e).__name__}: {e}")

        # Phase 3: HTTP probe on /mgmt/tm/sys/version
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                if resp.status == 200:
                    log(f"  {host}: iControl REST ready at +{elapsed}s")
                    return
                last_err = f"HTTP {resp.status}"
                last_phase = "http"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            last_phase = "http"
            if e.code == 401:
                last_err += " (admin password not set yet — cloud-init may still be running)"
        except (urllib.error.URLError, ConnectionResetError, OSError, ssl.SSLError) as e:
            last_err = f"{type(e).__name__}: {e}"
            last_phase = "http"
        time.sleep(sleep_seconds)
        sleep_seconds = min(sleep_seconds + 5, 30)

    log(f"  {host}: timeout. ssh_seen={ssh_seen} https_seen={https_seen} last_phase={last_phase} last_err={last_err}")
    log(f"  {host}: capturing EC2 console output for diagnostics...")
    console = fetch_console_output(instance_id)
    log(f"  {host}: ----- console output ({len(console)} chars) -----")
    for line in console.splitlines()[-80:]:  # last 80 lines is usually enough
        log(f"    {line}")
    log(f"  {host}: ----- end console output -----")

    raise RuntimeError(f"{host} did not become ready within {timeout}s (last: {last_err}, phase: {last_phase})")


def wait_for_all_ves(ve_endpoints: dict[str, dict[str, Any]], admin_password: str,
                     ssh_key: Path | None = None,
                     early_fetch_dir: Path | None = None) -> None:
    """ve_endpoints[hostname] must include mgmt_https_port (sourced from the
    ve-instance module output). Phase-2 TCP probe and phase-3 HTTP probe
    both use it. Don't hard-code 443 here — BIG-IP 17.1.x's default is
    8443 and our SG opens that port."""
    """Both VEs share the run's admin password (set on first boot by
    f5-bigip-runtime-init via the DO declaration's User class). The probe
    cannot succeed before runtime-init's bigip_ready_enabled phase posts
    that declaration, which is the whole point of switching off the
    instance-id-as-password approach.

    When ssh_key + early_fetch_dir are provided, each VE triggers a
    one-time SSH diagnostic fetch the first time both tcp/22 and tcp/443
    are reachable — gives us logs from the stable bootstrap window even
    if iControl REST never returns 200."""
    log(f"waiting up to {VE_READY_TIMEOUT}s per VE for iControl REST")
    for hostname, info in ve_endpoints.items():
        wait_for_icontrol(
            info["mgmt_public_ip"], info["instance_id"], admin_password,
            VE_READY_TIMEOUT,
            int(info["mgmt_https_port"]),
            ssh_key=ssh_key,
            hostname=hostname,
            early_fetch_dir=early_fetch_dir,
        )


def run_preflight() -> None:
    env = aws_env()
    # No F5_API_PASSWORD env var — the inventory has per-host passwords
    # (= EC2 instance IDs) baked in by terraform's local_sensitive_file.
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
    """Run `terraform destroy`. Caller (the finally-block in main) is
    responsible for deciding whether to invoke this — when SKIP_DESTROY
    is set, the caller skips the entire teardown sequence (this fn,
    nuclear, and key cleanup) and the operator runs the manual destroy
    command printed by print_skip_destroy_reminder."""
    proc = run(
        ["terraform", "destroy", "-auto-approve", "-input=false", "-no-color"],
        cwd=TERRAFORM_ENV,
        check=False,
    )
    return proc.returncode == 0


def print_skip_destroy_reminder() -> None:
    """When INTEGRATION_SKIP_DESTROY=1 leaves resources up, print the
    exact command to destroy them — full path, concrete AWS_PROFILE and
    AWS_REGION values, no shell-var indirection — so a copy-paste from
    terminal scrollback into a fresh shell works without setup. The
    wrapper has deliberately overridden its primary contract (no
    resources stranded) for the inner-loop debug workflow; this message
    is the explicit handoff back to the operator."""
    if not SKIP_DESTROY:
        return
    log("")
    log("    !!! RESOURCES STILL RUNNING — INTEGRATION_SKIP_DESTROY=1 was set !!!")
    log("    EC2 instances, EIPs, VPC, security groups all preserved.")
    log("    They are accruing cost until you run the destroy command below.")
    log("    Recommended: bound diagnostic-debug sessions to under 90 minutes.")
    log("")
    log("    SSH key preserved at:")
    log(f"        {BUILD_DIR / 'ssh_key'}")
    log("    Inventory preserved at:")
    log(f"        {BUILD_DIR / 'inventory.yml'}")
    log("")
    log("    Manual destroy (paste into a fresh shell when done):")
    log("")
    log(f"        cd {TERRAFORM_ENV} && \\")
    log(f"          AWS_PROFILE={AWS_PROFILE} AWS_REGION={AWS_REGION} \\")
    log( "          terraform destroy -auto-approve -input=false")
    log("")
    log("    If terraform destroy fails, fall back to nuclear teardown:")
    log("")
    log(f"        cd {REPO_ROOT} && \\")
    log(f"          AWS_PROFILE={AWS_PROFILE} AWS_REGION={AWS_REGION} \\")
    log( "          python3 -c \"from tools.integration_wrapper import nuclear_teardown; nuclear_teardown()\"")
    log("")


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


SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "LogLevel=ERROR",
]


def ssh_fetch_one(ssh_key: Path, host: str, bash_cmd: str, local_path: Path,
                  ssh_timeout: int = 60) -> tuple[bool, str]:
    """Run a single bash command on the BIG-IP via SSH, capture stdout to
    local_path. Returns (ok, summary) where summary is one short status
    line for the log.

    Important: SSH'ing as admin@bigip lands in **tmsh**, not bash, on
    PAYG VEs where the DO declaration hasn't yet flipped admin's shell
    (which is exactly the failure mode we're diagnosing — admin still has
    shell=tmsh, so direct `ssh ... 'cat /path'` returns "Syntax Error:
    unexpected argument cat" from tmsh's own command parser).

    The escape hatch is tmsh's documented `run /util bash -c '...'`
    subcommand (F5 KB K1126932 / TMSH Reference, "run util" section)
    which delegates to bash. Wrap every fetch in that. Don't tidy this
    back to plain `ssh ... 'cat ...'` — admin's shell will still be tmsh
    on every fresh PAYG VE before runtime-init has done its job, which
    is precisely when we need these diagnostics.

    Wrapped to never raise — diagnostic capture must not block destroy.
    """
    tmsh_wrapped = f"run /util bash -c {shlex.quote(bash_cmd)}"
    try:
        proc = subprocess.run(
            ["ssh", "-i", str(ssh_key), *SSH_OPTS, f"admin@{host}", tmsh_wrapped],
            capture_output=True, text=True, timeout=ssh_timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "ssh timeout"
    except OSError as e:
        return False, f"ssh exec error: {e}"
    if proc.returncode != 0:
        snippet = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        return False, f"rc={proc.returncode} {snippet[0][:120]}"
    try:
        local_path.write_text(proc.stdout)
    except OSError as e:
        return False, f"write error: {e}"
    return True, f"{len(proc.stdout)} bytes"


def ssh_fetch_diagnostics(ssh_key: Path, ve_endpoints: dict[str, dict[str, Any]],
                          run_dir: Path) -> None:
    """Best-effort post-mortem log retrieval. Runs from BOTH VEs even if only
    one timed out — the side-by-side comparison is informative.

    Per-VE captures, all into run_dir/{hostname}/:
      bigIpRuntimeInit.log  — runtime-init's own log; tells you which phase
                              ran and where it stopped
      startup-script.log    — our user_data shell wrapper output
      restjavad.0.log       — iControl REST daemon log; decisive for the
                              "httpd up then died" failure mode
      journalctl.log        — last 1000 systemd journal entries

    All failures here are logged and swallowed. The contract this function
    must honour: NEVER raise. The caller's destroy phase runs after this
    one regardless of what happens in here.
    """
    if not ssh_key.exists():
        log(f"  ssh_key not found at {ssh_key} — skipping diagnostic capture")
        return

    files = [
        ("bigIpRuntimeInit.log", "cat /var/log/cloud/bigIpRuntimeInit.log 2>&1"),
        ("startup-script.log", "cat /var/log/cloud/startup-script.log 2>&1"),
        ("restjavad.0.log", "cat /var/log/restjavad.0.log 2>&1"),
        ("journalctl.log", "journalctl --no-pager -n 1000 2>&1"),
    ]

    for hostname, info in ve_endpoints.items():
        host = info.get("mgmt_public_ip")
        if not host:
            log(f"  {hostname}: no mgmt_public_ip in endpoints — skipping")
            continue
        host_dir = run_dir / hostname
        try:
            host_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log(f"  {hostname}: cannot create {host_dir}: {e}")
            continue
        log(f"  {hostname} ({host}): fetching diagnostics")
        for label, cmd in files:
            ok, summary = ssh_fetch_one(ssh_key, host, cmd, host_dir / label)
            log(f"    {label}: {'ok' if ok else 'FAILED'} ({summary})")


def cleanup_local_secrets() -> None:
    """Remove the chmod-600 ssh key and rendered inventory. Wrapper
    deliberately doesn't blow away build/integration/ wholesale —
    terraform's local state and plan files live there too and may help
    diagnose the next run. The inventory contains per-host EC2 instance
    IDs as F5 admin passwords, hence chmod 600 + cleanup."""
    for path in (BUILD_DIR / "ssh_key",
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
    # Hoisted so the finally-block diagnostic capture can see it even if
    # apply succeeds but a later phase raises before everything wires up.
    ve_endpoints: dict[str, dict[str, Any]] = {}

    # Hoisted: the early-diagnostic-fetch path needs the run dir before
    # wait_for_all_ves runs, and the late-fetch path uses the same dir.
    run_dir = REPO_ROOT / "build" / "integration" / "runs" / run_id
    ssh_key = BUILD_DIR / "ssh_key"

    try:
        terraform_apply(run_id)
        outputs = terraform_outputs()
        ve_endpoints = outputs["ve_endpoints"]["value"]
        admin_password = terraform_admin_password()

        log(f"VEs provisioned: {list(ve_endpoints.keys())}")
        for h, info in ve_endpoints.items():
            log(f"  {h}: {info['mgmt_public_ip']} (ami {info['ami_name']})")

        run_dir.mkdir(parents=True, exist_ok=True)
        wait_for_all_ves(
            ve_endpoints, admin_password,
            ssh_key=ssh_key,
            early_fetch_dir=run_dir / "early",
        )
        run_preflight()

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

        # Diagnostic capture is a separate phase from destroy. Order is
        # strict: failure detected → SSH-fetch → save logs → destroy.
        # Its try/except is isolated so a fetch failure (key wrong, VE
        # actually dead, network) cannot interfere with destroy. Primary
        # contract: no resources stranded. Diagnostic capture is secondary.
        # Late fetch lands in run_dir/late/{hostname}/; the early fetch
        # (during wait_for_all_ves) lives in run_dir/early/{hostname}/.
        # Comparing the two diagnoses state-dependent SSH-escape failures
        # like the iter 3 vs iter 4 delta.
        if failed and ve_endpoints:
            log("=== diagnostic capture (late) ===")
            if SKIP_DESTROY:
                log("  [automated SSH-fetch will likely fail in SKIP_DESTROY mode —")
                log("   manual SSH is the diagnostic path; ignore the rc=1 output below]")
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                ssh_fetch_diagnostics(ssh_key, ve_endpoints, run_dir / "late")
                log(f"diagnostics saved to {run_dir.relative_to(REPO_ROOT)}/")
            except Exception as e:
                log(f"diagnostic capture raised (non-fatal): {type(e).__name__}: {e}")

        # Teardown branches on SKIP_DESTROY. Default path (no flag) keeps
        # the no-resources-stranded contract: planned destroy → nuclear
        # safety net if destroy fails → key/inventory cleanup. SKIP_DESTROY
        # path skips ALL of those — no destroy, no nuclear, no key wipe —
        # so the operator can SSH in for diagnostic inspection. The loud
        # warning + paste-ready manual destroy command come from
        # print_skip_destroy_reminder() called below the finally block.
        if SKIP_DESTROY:
            log("=== teardown SKIPPED (INTEGRATION_SKIP_DESTROY=1) ===")
        else:
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

    print_skip_destroy_reminder()

    if failed:
        log(f"=== integration FAILED ({failure_reason}) ===")
        return 1
    log("=== integration PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
