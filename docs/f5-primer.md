# F5 BIG-IP Primer — How the Devices Work and How Upgrades Are Done by Hand

Background doc for anyone working on NexusF5 who hasn't lived inside an F5 estate.
It explains what an F5 BIG-IP actually *is*, the two-layer "it's kind of Linux" reality,
how the active/standby + two-volume design makes upgrades survivable, what the manual
upgrade process looks like step by step, and which F5 products (modules) you'd actually
run into at a bank — and why NexusF5 scopes to the ones it does.

This is the "why does the runbook look like that" doc. For the orchestration design itself,
see [`ARCHITECTURE.md`](../ARCHITECTURE.md).

---

## 1. What a BIG-IP is

An F5 BIG-IP is a **full-proxy application delivery controller** — at its core a very
sophisticated load balancer that terminates client connections, makes decisions about
them (routing, health, security, identity, SSL), and opens *separate* connections to the
back-end servers. It sits in front of applications: clients talk to the BIG-IP, the
BIG-IP talks to the servers, and the two sides never touch directly.

It comes in three form factors, all running the same software:

| Form factor | What it is | Where you see it |
|---|---|---|
| **Hardware appliance** | Purpose-built box (e.g. iSeries i5800/i10800) with SSL/crypto offload ASICs | Data-center racks |
| **Chassis** | Blade chassis (VIPRION, newer VELOS/rSeries) for very high throughput | Large enterprises, carriers |
| **Virtual Edition (VE)** | The same software as a VM (ESXi, KVM, AWS, Azure) | Cloud, lab, DR, smaller sites |

NexusF5 validates against **VE** because the software is identical to hardware for upgrade
purposes — the upgrade workflow doesn't care whether TMOS is on an ASIC-accelerated box or
a VM. (Hardware-specific quirks like rSeries/VELOS partitioning are explicitly out of scope;
see [CLAUDE.md](../CLAUDE.md) → "Where not to go".)

---

## 2. "It's kind of a Linux box" — yes, but with two planes

Your instinct is right, with one important refinement. The software is called **TMOS**
(Traffic Management Operating System), and TMOS is *not* one thing — it's two cooperating
planes on one device:

```
┌──────────────────────────────────────────────────────────────┐
│                          ONE BIG-IP                            │
│                                                                │
│   CONTROL / MANAGEMENT PLANE          DATA PLANE               │
│   ┌──────────────────────────┐      ┌────────────────────┐    │
│   │  Linux host OS           │      │  TMM                │    │
│   │  (CentOS/RHEL-derived)   │◄────►│  (Traffic Mgmt     │    │
│   │                          │      │   Microkernel)     │    │
│   │  • SSH / bash / systemd  │      │                    │    │
│   │  • iControl REST (httpd) │      │  • Owns the NICs   │    │
│   │  • tmsh (the F5 CLI)     │      │  • Handles ALL     │    │
│   │  • config DB (MCPD)      │      │    client traffic  │    │
│   │  • mgmt interface        │      │  • Kernel-bypass,  │    │
│   └──────────────────────────┘      │    runs on its own │    │
│                                     │    dedicated cores │    │
│                                     └────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

- **Control/management plane** — this is the part that *feels* like a Linux server. It's a
  CentOS/RHEL-derived host OS. You can SSH in, you get a bash shell, there's `systemd`,
  there are log files in `/var/log`. This plane runs the management interface, the config
  database, the F5 CLI (`tmsh`), and — critically for us — the **iControl REST API** (an
  Apache/httpd service exposing `/mgmt/tm/...` endpoints). NexusF5 drives the device almost
  entirely through this API.

- **Data plane** — this is the part that is *not* ordinary Linux. **TMM** (Traffic
  Management Microkernel) is a separate, high-performance process that takes over the
  traffic-facing network cards and processes packets in user space, bypassing the normal
  Linux kernel network stack. TMM is what makes a BIG-IP fast. It runs on dedicated CPU
  cores and has its own memory. When you "load balance," TMM is doing the work; the Linux
  side is just there to configure and supervise it.

**Why this matters for upgrades:** an upgrade replaces *both* planes at once (a new TMOS
image is a new host OS *and* a new TMM). That's why an upgrade is a full reboot, not a
service restart — and why you can't gracefully upgrade the data plane without dropping the
traffic it's carrying. Hence the active/standby dance below.

**Key vocabulary you'll see in the playbooks:**

| Term | What it means |
|---|---|
| **TMOS** | The whole F5 operating system (control plane + TMM) |
| **TMM** | The data-plane process that actually moves traffic |
| **tmsh** | F5's CLI shell (`tmsh show /sys ...`) — the human equivalent of iControl REST |
| **iControl REST** | The HTTP API at `/mgmt/tm/...` that NexusF5 automates against |
| **MCPD** | The master config daemon / in-memory config DB; "the config" lives here |
| **UCS** | User Configuration Set — a full config backup archive (`.ucs` file) |
| **VIP / virtual server** | The address:port clients connect to; the front door of an app |
| **Pool / pool member** | The set of back-end servers behind a VIP, with health monitors |
| **iRule** | A TCL script attached to a VIP for custom traffic logic (very common, very bespoke) |

---

## 3. Two concepts people conflate: active/standby vs. active volume

This is the single most important thing to get straight, because the upgrade process uses
**both** and they sound the same but are not. Your description mixed them together — here's
the clean split.

### 3a. Active / Standby — *across two devices* (HA failover)

Production BIG-IPs are deployed as **HA pairs**: two physical/virtual devices configured as
a **device group** with a shared, floating set of traffic objects (a **traffic group**). At
any moment one device is **Active** (carrying live traffic) and the other is **Standby**
(fully configured, config continuously synced, sitting idle ready to take over).

```
        clients
           │
     ┌─────┴─────┐  floating "self" IP / VIPs live on whichever device is Active
     ▼           ▼
 ┌────────┐  ┌────────┐
 │bigip-01│  │bigip-02│
 │ ACTIVE │  │STANDBY │   ◄── config-sync keeps STANDBY identical to ACTIVE
 └────────┘  └────────┘
      └───── back-end servers ─────┘
```

If the active device fails (or you *make* it fail on purpose), the standby promotes itself
to active in seconds — a **failover**. This is the safety net that lets you take one device
completely out of service without an outage.

### 3b. Active volume / boot location — *within one device* (software slots)

Separately, **each individual device** has multiple **boot volumes** (software slots),
named like `HD1.1`, `HD1.2`. Each volume holds its own complete, independent installation
of TMOS and config. Only one volume is **active** (currently booted) at a time.

```
        ONE device (bigip-01)
   ┌──────────────────────────────┐
   │  HD1.1  TMOS 15.1.x  ◄ ACTIVE │  ← currently running
   │  HD1.2  (empty / old version) │  ← target for the new image
   └──────────────────────────────┘
```

This is exactly the "install, make active, boot into it" pattern you described. You install
a new TMOS image **onto the inactive volume** (which doesn't touch the running system at
all), then tell the device to **boot to that volume**. The device reboots into the new
version. If the new version is bad, you boot *back* to the old volume — the old install is
untouched and intact. **This is F5's native rollback**, and it's the reason design
principle #4 in CLAUDE.md says "native rollback before orchestrated rollback."

### Putting it together

An upgrade combines them: you upgrade the **standby device** by installing to its **inactive
volume** and booting it there — all while the **active device** keeps serving traffic. Then
you fail over so the freshly-upgraded device becomes active, and repeat the whole thing on
the other device. Two safety nets stacked: the HA pair protects against the device being
down, and the two-volume design protects against the new software being broken.

---

## 4. The manual upgrade process (the thing NexusF5 replaces)

This is how one HA pair gets upgraded **by hand** today — typically one engineer, one
device pair, inside a change window, taking 2–4 hours of attention per pair. Multiply by
hundreds of pairs and you get the "months, not days" problem from `ARCHITECTURE.md`.

The golden rule: **upgrade the standby, prove it, fail over, then upgrade the old active.**
Never both devices at once.

### Step-by-step (per HA pair)

1. **Change window + approvals.** Schedule a maintenance window. Get change-management
   sign-off (at a bank this is a formal CAB process). Notify app owners.

2. **Preflight checks.** Confirm the pair is healthy *before* touching it:
   - HA status is clean (one Active, one Standby — not "active/active" split-brain).
   - Config sync is **In Sync** (`GET /mgmt/tm/cm/sync-status`).
   - CPU, memory, and disk are within limits.
   - Connection counts noted so you can compare after.
   - *If preflight is bad, you stop here.* Upgrading an unhealthy pair turns one problem
     into two.

3. **Backup.** Take a **UCS** archive of both devices and copy it off-box
   (`POST /mgmt/tm/sys/ucs`). This is the "rebuild from scratch" fallback if both volumes
   somehow end up bad.

4. **Pick the standby and start with it.** Everything below happens on the **standby**
   first, so production traffic on the active device is never at risk.

5. **Download + install the image to the inactive volume.** Upload the TMOS image, then
   install it to the *inactive* volume (`POST /mgmt/tm/sys/software/image`, then a volume
   install). The running system is unaffected during install — it can take 20–40 minutes.

6. **Boot to the new volume.** Set the new volume active and reboot the standby. It comes
   back up on the new TMOS version. The active device has been carrying all traffic this
   whole time.

7. **Health-gate the upgraded standby.** Before trusting it, verify on the new version:
   config loaded, no errors, modules provisioned, licensing intact, monitors green. **This
   is a hard gate** — if it's unhealthy you do *not* proceed; you boot it back to the old
   volume (native rollback) and investigate.

8. **Fail over.** Force the upgraded (now-healthy) standby to become **Active**. Traffic
   moves to the new version. Watch closely — connection counts, error rates, app health.
   This is the moment of truth; if the new version misbehaves under real traffic, you fail
   back to the still-old other device.

9. **Upgrade the other device.** The former-active is now standby and still on the old
   version. Repeat steps 5–7 on it. Now both devices are on the new version.

10. **Postcheck + re-sync + re-apply config.** Confirm config sync is clean across the pair,
    re-apply the declarative config (DO/AS3) to confirm zero drift, compare connection/health
    metrics against the preflight baseline, and document the result.

11. **Rollback path (if needed).** Because each device kept its old volume, rollback is
    "boot to the previous volume + fail over" — not a restore-from-backup marathon. UCS
    restore is the last resort, not the first move.

### Why this is painful at fleet scale

Every one of those steps is a place a human waits, watches, types a command, reads output,
and decides. It's careful work that doesn't *parallelize* when one engineer owns one pair.
The steps are also **identical and deterministic across devices** — which is exactly why
they automate well. NexusF5 turns this manual checklist into Ansible roles (one role per
step: `f5_preflight`, `f5_backup`, `f5_image_install`, `f5_boot_switch`, `f5_health_gate`,
`f5_failover`, `f5_postcheck`) and runs many pairs at once in waves. The *sequence is the
contract* — the automation does exactly what the careful engineer does, just in parallel
and with hard, non-skippable health gates.

---

## 5. F5 products (modules) you'd run into at a bank

A BIG-IP is a platform. **LTM is the foundation** — it's the load-balancing core, and every
other module is licensed and provisioned *on top of* LTM on the same device. A bank rarely
runs "just a load balancer"; they stack several modules. Here's the realistic lineup, in
rough order of how much you'd see them in a financial-services estate.

| Module | Full name | What it does | Why a bank has it |
|---|---|---|---|
| **LTM** | Local Traffic Manager | Core load balancing, full-proxy, SSL termination, health monitoring, iRules | The foundation. Fronts online banking, mobile-app APIs, core banking apps, internal services. Everything else rides on it. |
| **Advanced WAF / ASM** | Application Security Manager | Web Application Firewall — blocks OWASP Top 10, bot defense, API security, credential stuffing | **PCI-DSS requires a WAF** in front of cardholder-data apps. Protecting online/mobile banking from attack is non-negotiable. Usually one of the biggest modules at a bank. |
| **APM** | Access Policy Manager | Identity-aware access proxy — SSL VPN, SSO, MFA integration, per-app access policies | Employee and third-party remote access, SSO into internal apps, step-up MFA. Heavy use post-pandemic for workforce access. |
| **DNS / GTM** | (BIG-IP DNS, formerly Global Traffic Manager) | Global server load balancing — DNS-based traffic steering and failover *between data centers* | Banks run active/active or active/DR across multiple data centers; GTM/DNS decides which site a user lands on and handles site failover for DR/BCP. |
| **AFM** | Advanced Firewall Manager | Network (L3/L4) firewall + DDoS protection at the edge | Edge firewalling and volumetric DDoS defense in front of the application tier. |
| **SSLO** | SSL Orchestrator | Decrypt → steer through inspection tools (IDS/DLP/AV) → re-encrypt | Banks must inspect encrypted traffic for data loss and threats; SSLO orchestrates the decrypt/inspect/re-encrypt chain so security tools can see inside TLS. |

Plus the things that aren't separate licenses but are everywhere:

- **iRules** — TCL scripts bolted onto virtual servers for custom logic (header rewrites,
  redirects, routing tricks, security shims). Banks accumulate *thousands* of these over the
  years, and they're the bespoke, fragile part of any estate — the reason every upgrade
  needs a postcheck that the apps still behave.
- **iApps / DO / AS3** — templated/declarative ways to define application config. NexusF5
  treats **DO** (base system config) and **AS3** (application delivery config) as the
  declarative source of truth and re-applies them after every upgrade to prove zero drift.

### A realistic "what's in the rack" picture for a bank

- A few hundred **HA pairs** of BIG-IP (mix of hardware in core data centers + VE in cloud/DR).
- **LTM everywhere**, with **Advanced WAF/ASM** in front of every internet-facing app
  (online banking, mobile API gateways, public sites).
- **APM** clusters for remote access and SSO.
- **GTM/DNS** pairs at each data center for cross-site steering and DR failover.
- **AFM** and **SSLO** at the security edge.
- Multiple TMOS versions in the wild simultaneously (the whole reason an upgrade program
  exists), with strict change control, audit trails, and rollback requirements on every move.

### How this scopes NexusF5

NexusF5 deliberately focuses on the **LTM upgrade path** and treats the other modules as
context, not scope. Per [CLAUDE.md](../CLAUDE.md) → "Where not to go": no AFM/ASM *policy*
migration, no BIG-IQ management plane, no actual tenant migration. The reason is that the
**upgrade mechanics — preflight, install-to-inactive-volume, boot-switch, health-gate,
failover, postcheck — are the same regardless of which modules are provisioned.** Nail the
LTM-based upgrade workflow at fleet scale and you've demonstrated the hard part; the extra
modules change *what you health-check after boot*, not *how the upgrade flows*. That's the
honest, defensible scope for a portfolio system, and it's why the runbook looks the way it
does.

---

## 6. TL;DR

- A BIG-IP is a full-proxy load balancer running **TMOS** — a CentOS-derived **Linux
  control plane** (where the API and CLI live) plus a kernel-bypass **data plane (TMM)**
  that actually moves traffic. "Kind of a Linux box" is right for the management side.
- **Active/Standby** = two devices in an **HA pair** (failover protects against a device
  going down). **Active volume** = software slots **within one device** (boot-switch
  protects against bad software). Upgrades use **both**.
- The manual upgrade is: preflight → backup → install to inactive volume on the **standby**
  → boot to it → health-gate → fail over → repeat on the other device → postcheck/re-sync.
  Native rollback = boot back to the old volume.
- A bank stacks **LTM (foundation) + Advanced WAF/ASM + APM + DNS/GTM + AFM + SSLO** on top
  of hundreds of HA pairs, plus thousands of bespoke iRules.
- NexusF5 automates the **LTM upgrade sequence** at fleet scale because the upgrade
  mechanics are module-independent — the careful manual checklist becomes parallel,
  wave-gated, hard-health-gated automation.
