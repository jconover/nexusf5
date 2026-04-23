# 02 — Image install stuck or failed

Referenced from `f5_image_install`. The role either saw the install poll
return `status: failed` or exhausted its retry budget.

## Diagnose

1. **Check the install poll's last response** (task output in the ansible
   log). Real F5 reports `status: "install failure"` or similar rather than
   the mock's `failed`; either means the install did not write the image
   cleanly.
2. **Confirm the image is present and not corrupt:**
   ```bash
   curl -sk -u admin:<pw> https://<host>/mgmt/tm/sys/software/image \
     | jq '.items[] | select(.name=="BIGIP-17.1.0-0.0.3.iso")'
   ```
   Cross-reference SHA256 against the image registry.
3. **Check the target volume:**
   ```bash
   curl -sk -u admin:<pw> https://<host>/mgmt/tm/sys/software/volume/HD1.2
   ```
4. **Look at mgmt plane memory.** Image install spikes memory on the
   management CPUs; a stuck install often correlates with
   `/var/log/liveinstall.log` showing a `mke2fs` or `dd` OOM.

## Recover

- If the image is bad: pull it out of the image registry, re-upload known-good.
- If the volume is corrupt: recreate it via
  `tmsh create sys software volume HD1.2 create-volume` then rerun install.
- If the device looks otherwise healthy and no bad state was committed:
  rerun `upgrade.yml` on the single host. It is idempotent.

## Do not

- Delete the volume in-flight if the install process is still holding a
  lock. Kill the install first.
- Rerun the wave-wide playbook to "force" one bad device through —
  rerun scoped to that host.

## If canary surfaces this

Pull the image out of the registry and block wave 1 approval. A single
canary install failure is exactly what the canary wave is meant to catch;
it is not a reason to push harder.
