# Integration test diagnostics: reading the logs

When `make integration` fails, the wrapper SSHes into each provisioned VE
before destroy and saves logs to
`build/integration/runs/{run_id}/{hostname}/`. This runbook is the map for
those logs — what each one tells you and how to read them in order.

The wrapper captures from **both** VEs even if only one timed out. If
bigip-aws-01 failed and bigip-aws-02 didn't, the diff between their logs is
often the diagnostic. Always compare side-by-side first.

## Files captured per VE

### `bigIpRuntimeInit.log`

Source: `/var/log/cloud/bigIpRuntimeInit.log` on the VE.
Author: f5-bigip-runtime-init itself (path set by `controls.logFilename`
in `terraform/modules/ve-instance/runtime-init-userdata.sh.tftpl`).

What you learn here:

- **Whether runtime-init started at all.** If the file is missing or empty,
  runtime-init never ran or never got far enough to open its log file.
  Cross-check with `startup-script.log`.
- **Which phase reached.** Runtime-init logs phase entries for
  `pre_onboard_enabled`, `bigip_ready_enabled`, `extension_packages`, and
  `extension_services`. The last successful phase tells you where the
  process stopped.
- **mcpd-ready barrier.** A log line indicating `bigip_ready_enabled`
  completed proves the mcpd-ready wait succeeded. Absence means runtime-init
  is still waiting (or gave up) on mcpd.
- **Extension RPM install results.** The `extension_packages` phase
  reports per-extension install status, version, and hash verification.
- **DO declaration submission.** The `extension_services` phase logs the
  iControl REST POST, the returned task ID, and the async polling loop.
  Search for the task ID in `restjavad.0.log` to see what happened on the
  iControl side.

### `startup-script.log`

Source: `/var/log/cloud/startup-script.log` on the VE.
Author: our user_data shell wrapper (`exec > >(tee -a ...)` in
`runtime-init-userdata.sh.tftpl`).

What you learn here:

- **Whether BIG-IP cloud-init ran our user_data.** If the file is absent,
  cloud-init never executed our user_data. Suspect AMI / cloud-init issues,
  not runtime-init.
- **Where the bash wrapper stopped.** With `set -euxo pipefail`, every
  command is traced and the script exits at the first failure. The last
  `+ <cmd>` line is the last thing attempted.
- **Installer download status.** `curl` exit, `sha256sum -c` verify pass/fail.
- **Installer extraction.** `bash /tmp/...gz.run -- '--cloud aws'` output.
- **Reaching the runtime-init invocation.** A `[runtime-init-userdata] done`
  echo at the bottom proves the wrapper completed cleanly. Its absence is
  diagnostic by itself.

### `restjavad.0.log`

Source: `/var/log/restjavad.0.log` on the VE.
Author: BIG-IP's iControl REST daemon.

What you learn here:

- **iControl REST events from the VE side.** This log is decisive when the
  failure mode is "httpd up then died" or "iControl REST returned but the
  task hung." restjavad logs the events that may have triggered the death
  (e.g. a misformed DO declaration, a restjavad worker crash loop, a
  process restart).
- **DO RPM install events on the iControl LX side.** The DO RPM is an
  iControl LX node app; restjavad logs when it loads, registers, and starts
  serving requests.
- **DO async task progression.** Find the task ID from
  `bigIpRuntimeInit.log`, search restjavad for that ID, and you'll see the
  task's state transitions.
- **httpd reload events.** Any non-zero return from an httpd reload shows
  up here.

### `journalctl.log`

Source: `journalctl --no-pager -n 1000` from the VE.

What you learn here:

- **Systemd-level events** that might have preceded a service crash —
  unit start/stop/fail messages, oom-kills, restart loops.
- **cloud-init phases.** systemd shows when `cloud-init.service`,
  `cloud-config.service`, and `cloud-final.service` ran and finished.
  Our user_data runs during `cloud-final`.
- **F5 services.** mcpd, restjavad, restnoded, httpd, tmm — their lifecycle
  events appear here when systemd intervenes.

## Reading order on failure

Always start with the VE that failed; only diff against the other once you
have a hypothesis.

1. **Did `startup-script.log` exist?**
   - No → cloud-init didn't run our user_data. Suspect AMI/cloud-init,
     not runtime-init. Look at `journalctl.log` for cloud-init unit status.
   - Yes → continue.
2. **Did `startup-script.log` reach the `done` echo?**
   - No → see where the trace stopped. Common stop points: curl
     (network/CDN), sha256sum (wrong hash, F5 rotated artifact), installer
     extraction (out of disk), runtime-init invocation (binary missing).
   - Yes → wrapper completed; runtime-init's own behaviour is the next layer.
3. **Did `bigIpRuntimeInit.log` exist?**
   - No → runtime-init binary never wrote a log line despite startup-script
     claiming to invoke it. Rare. Check the runtime-init binary actually
     installed (the installer extraction step in `startup-script.log`).
   - Yes → continue.
4. **Read `bigIpRuntimeInit.log` from the start.** Look for the last
   successful phase. If a phase failed, the immediate next lines describe
   why.
5. **If runtime-init reached `extension_services`,** find the DO task ID and
   cross-reference `restjavad.0.log`. The DO task may be hung, may have
   raised an exception during commit, or may have tripped a restjavad
   worker restart that took httpd with it.
6. **Diff against the second VE.** If one VE succeeded and the other
   failed, the first divergent log line is the diagnostic.

## "tcp/443 ConnectionRefused after first boot" is normal in 17.1.x

If you see the integration wrapper time out with
`last_phase=https-tcp last_err=tcp/443 ConnectionRefusedError`, the most
likely cause is **port mismatch, not service failure.** BIG-IP 17.1.x
defaults `sys httpd ssl-port` to **8443**, not 443. Older releases (≤
13.x) defaulted to 443; the change was made to free port 443 for
data-plane VIPs in real deployments, and we follow F5's direction-of-
travel rather than overriding it back.

How to verify (post-bootstrap, on the VE):

```bash
ssh -i build/integration/ssh_key admin@<ip> 'bash -c "tmsh list sys httpd"'
# expect:
#   sys httpd {
#       ssl-port 8443
#   }

ssh -i build/integration/ssh_key admin@<ip> 'bash -c "ss -tlnp | grep 8443"'
# expect httpd LISTENing on :::8443
```

External liveness probe:

```bash
curl -sk -u "admin:$PASSWORD" https://<ip>:8443/mgmt/tm/sys/version
# expect HTTP 200 with version JSON
```

The port lives in **one place** in this repo: the ve-instance module's
`mgmt_https_port` variable (default 8443). The SG ingress rule, the
wrapper's TCP/HTTP probes, and the rendered ansible inventory's
`f5_api_base_url` all read from it. If F5 ships another default change
in a future TMOS release, the fix is one variable edit.

## When the logs themselves are silent

Sometimes the SSH fetch fails: VE wedged, key doesn't authenticate, network
gone. The wrapper logs each `FAILED` per file and continues to destroy.
Evidence then reduces to:

- The wrapper's TCP/HTTP probe timeline (in the run's stdout log).
- The (possibly stale) EC2 console output the wrapper captured at timeout.

If iteration N also fails this way, the next iteration needs an in-band
diagnostic — runtime-init's `post_hook` webhook posting status to a
collector, or an SSM-Run-Command sidecar that captures logs while runtime-init
is still mid-flight rather than after.

## Where logs live

```
build/integration/runs/{run_id}/
├── bigip-aws-01/
│   ├── bigIpRuntimeInit.log
│   ├── startup-script.log
│   ├── restjavad.0.log
│   └── journalctl.log
└── bigip-aws-02/
    ├── bigIpRuntimeInit.log
    ├── startup-script.log
    ├── restjavad.0.log
    └── journalctl.log
```

`run_id` is the wrapper's UTC timestamp (`YYYYMMDDtHHMMSSz`). Old runs are
not auto-cleaned; tidy `build/integration/runs/` periodically.
