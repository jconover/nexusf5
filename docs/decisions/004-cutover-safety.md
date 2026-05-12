# ADR 004 — Cutover safety: drain windows, rollback triggers, DNS-based cutover

- Date: 2026-05-03
- Status: Accepted

## Context

The immutable track (ADR 003) replaces an existing BIG-IP VE with a new VE
at the target version, then flips traffic from old to new. That flip
introduces three concrete risk classes the hybrid track does not have:

1. **Mid-flight session loss.** The old VE has live TCP connections,
   active TLS sessions, and persistence-profile state. A naïve "delete
   old, start new" leaves all of that on the floor.
2. **DNS propagation lag.** Different resolvers honour TTLs differently;
   some clients (especially long-lived JVMs and connection pools) cache
   DNS for hours regardless of TTL. The cutover is *not atomic* even when
   the DNS provider's record update is.
3. **Rollback ambiguity.** The hybrid track has BIG-IP's two-volume
   native rollback — flip the active volume back, reboot, gate. The
   immutable track has no such mechanism: the old VE either still exists
   (rollback is "flip DNS back") or it doesn't (rollback requires
   re-provisioning). The window during which rollback is cheap must be
   defined.

This ADR codifies the immutable track's answer to all three.

## Decision

The immutable track's cutover follows a fixed shape:

1. **Apply phase.** New VE provisioned at target version, declarations
   applied, drift gate passes. Old VE remains active and serving traffic.
2. **Cutover phase.** DNS record flips from old-VE EIP to new-VE EIP.
   Atomic at the DNS provider; non-atomic at the client population.
3. **Drain window.** The old VE remains available, accepting traffic
   from any client that still has the old DNS answer cached. Default
   30 minutes (`drain_window_seconds = 1800`). Configurable.
4. **Drain-complete signal.** Wave orchestration emits a "old VE may be
   destroyed" event. Operator confirmation OR pre-approved policy
   decides whether to proceed automatically.
5. **Old-VE destroy.** `terraform destroy -target=...` removes the old
   VE. The immutable track exits with no stranded resources.

Each phase has explicit rollback triggers (below).

## Why DNS-based cutover (vs. proxy-based or VIP-takeover)

Three cutover shapes were on the table. DNS won.

### DNS flip (chosen)

DNS A/AAAA record points at old VE; flip to new VE; clients with the new
answer reach new VE; clients with the cached old answer continue to
reach old VE until their TTL expires.

**Pros**

- **Provider-agnostic.** Route 53, Cloudflare, NS1, GoDaddy, internal
  BIND — the cutover shape is identical. ADR 003's "matches existing
  IaC culture" argument applies: the team's existing DNS-as-code wiring
  is reused.
- **No traffic-plane appliance to introduce.** The immutable track does
  not require a *third* device (a proxy that fronts both old and new)
  to do the cutover. That third device would itself need upgrading,
  monitoring, and operator training.
- **Drain semantics are visible and tunable.** The drain window is
  explicit (`drain_window_seconds`) and aligned with the DNS TTL the
  operator controls. There's no hidden state inside an upstream proxy.
- **Rollback is symmetric.** Flip the DNS record back. Same operation,
  same TTL, same drain window in reverse.

**Cons**

- **Long-lived JVM / connection-pool clients ignore TTLs.** A drain
  window long enough to bound this risk has to be measured against
  the worst-offender client's behaviour, which is sometimes "until
  the JVM restarts." Workloads with this client population should
  use hybrid (ADR 003's #4) instead.
- **Not truly atomic at the client.** Some clients see old; some
  clients see new; both populations are served correctly during the
  drain window, but a request that traverses *two* DNS resolutions
  (e.g. a redirect chain) can land on different VEs for different
  hops. Stateless workloads tolerate this; stateful workloads should
  use hybrid.

### Proxy-based cutover (rejected)

A third device (HAProxy, NGINX, F5 GTM) sits in front of both old and
new and shifts traffic on a configured weight. Drain by ramping new
weight 0% → 100% over time.

Rejected because:

- Requires the proxy to itself be highly-available, monitored,
  operated, and upgraded — a third operational surface.
- The Phase 5 modernization track already uses NGINX as a *replacement*
  for BIG-IP LTM, not as a cutover proxy in front of it. Mixing these
  roles is confusing.
- Drain semantics are buried in the proxy's internal state machine —
  harder to reason about and rollback than DNS TTL.

### VIP takeover (rejected)

The new VE assumes the same VIP IP as the old VE; cutover is an L2/L3
gratuitous-ARP takeover. Used in some HA-cluster designs.

Rejected because:

- Requires both VEs to share an L2 segment (or BGP anycast). The AWS
  immutable track demonstration runs both VEs in a public subnet
  *but* the production shape would put new VE in a different VPC —
  L2 takeover doesn't span VPCs.
- Cross-VPC takeover requires BGP, which most teams don't run for VIPs.
- Atomic cutover means *all* in-flight TCP connections die at the same
  instant. No drain window. Worse for stateful workloads than DNS.

## Drain window semantics

`drain_window_seconds` (terraform variable on `terraform/immutable-track`,
honoured by the cutover playbook) governs three things:

1. **How long the old VE remains accepting traffic.** Default 30 minutes.
   Long enough to outlast most client DNS caches; short enough to bound
   the spend on a duplicate VE.
2. **How long the wave waits before destroying old VE.** The cutover
   playbook sleeps for this duration after the DNS stub fires. Real
   wirings should have the DNS provider's record update propagate
   *before* the sleep starts, not as the first action — so that drain
   time is measured from the moment clients can see the new answer,
   not the moment the API call is made.
3. **Lower bound on rollback responsiveness.** While the drain window
   is open, rollback is cheap: flip DNS back, old VE is still alive,
   no re-provisioning needed. After the window closes and old VE is
   destroyed, rollback requires a new immutable-track run from
   scratch.

The integration test wrapper sets `INTEGRATION_DRAIN_WINDOW_SECONDS=30`
by default so the 45-minute round-trip stays inside its wall clock.
That value is *not* a recommendation for production — it's the smallest
value that exercises the round-trip shape. Production-shape callers
should pick a value bounded by:

- *Lower bound*: 2× the longest plausible client DNS cache TTL (most
  clients honour TTL; a small-multiple safety factor catches the
  outliers).
- *Upper bound*: cost ceiling for running duplicate VEs and the team's
  tolerance for "two VEs serving the same workload" complexity in
  monitoring.

`1800 s` (30 min) is the default for environments without specific
constraints either direction.

## Rollback triggers

Rollback during the drain window is cheap (DNS flip back). Rollback
*after* the drain window closes is expensive (re-provision old version).
The trigger list reflects this asymmetry — anything that fires *during
the drain window* triggers rollback aggressively; failures *after the
window closes* trigger an upgrade incident, not a rollback.

### Triggers during the drain window (DNS flip back, abort destroy)

- Synthetic monitor against the new VE returns non-2xx for >60s.
- New VE's iControl REST returns 5xx for any management call.
- TCP connection rate to the new VE drops by >80% relative to old VE
  pre-cutover (clients are not following the DNS change correctly).
- Operator initiates rollback via the wave UI (manual override).
- The drift gate (`terraform plan -detailed-exitcode`) reports drift
  on the new VE. Drift mid-cutover means something else applied
  config to the device; abort before traffic settles.

### Non-triggers during the drain window (continue cutover)

- Old VE shows residual traffic. Expected. Drain.
- DNS query volume to old VE is non-zero. Expected. Drain.
- Client retry counters increment. Often expected (single-DNS-resolution
  retries land on old; multi-resolution retries can land on new). Treat
  as a normal-operation signal unless paired with a synthetic monitor
  failure.

### Post-drain (drain window closed, old VE destroyed)

Rollback requires a new immutable-track run with the old version pinned
in the AMI selector. This is an upgrade incident, not a routine
rollback. Page the on-call; do not auto-trigger.

## Why default drain window is 30 minutes (not 5 minutes, not 4 hours)

5 minutes is shorter than the DNS-TTL-ignoring JVM client population
will wait. 4 hours doubles the cost ceiling for the immutable track
without buying meaningful safety. 30 minutes is the smallest value that
plausibly outlasts cache-respecting clients without burning duplicate-VE
spend, and matches the order of magnitude of "the operator-on-call
window" (i.e. an operator who started a cutover can plausibly stay at
the keyboard for the drain).

## Consequences

- **The drain window is a *budget*, not a *promise*.** Workloads that
  need stronger guarantees (every connection drains gracefully, no
  duplicate traffic ever) should use hybrid (ADR 003's #4 / #5).
- **Rollback responsiveness degrades over the drain window's lifetime.**
  Operators should know that the rollback window has a hard close.
- **Spend during the drain window is duplicate.** Two VEs running for
  the drain window. PR 3's $10/run cost ceiling is sized for a 30-second
  test drain; production-shape 30-minute drains add ~$0.30/run per VE.
- **DNS provider integration is out of scope for PR 3.** The stub in
  `terraform/immutable-track/dns_cutover.tf` documents three concrete
  extension shapes (Route 53, third-party, manual). Picking and wiring
  one is a follow-on per-environment task.
- **The "after destroy, rollback is an incident" boundary is bright,
  not soft.** Wave orchestration should refuse to auto-destroy if any
  rollback trigger fired during the drain window, even if the trigger
  was resolved before window close. Resolution-during-drain is fine
  for continuing the cutover; it should still cancel auto-destroy and
  force operator confirmation.

## Alternatives considered

- **No drain window (destroy old immediately on cutover).** Rejected.
  Mid-flight connections die; cache-respecting clients lose service for
  one TTL. This is essentially the proxy-cutover shape's atomicity
  problem reintroduced into the DNS-cutover shape.
- **Drain window measured from "all client DNS caches expired" rather
  than from "DNS update issued".** Rejected as unmeasurable. Worst-case
  client cache time is unbounded (some clients ignore TTLs). The 30-
  minute window is a best-effort budget against a representative client
  population, not a guarantee.
- **Auto-rollback on any monitor blip.** Rejected as too aggressive.
  Production monitors flap; rolling back on every flap turns the
  immutable track into a thrash loop. The trigger list above is
  intentionally narrow.

## Related

- `docs/decisions/003-hybrid-vs-immutable.md` — workload categories on
  each side of the line. ADR 003 picks the track; ADR 004 covers how
  the immutable track manages the cutover.
- `terraform/immutable-track/dns_cutover.tf` — the DNS cutover stub
  with three concrete extension shapes (Route 53, third-party, manual).
- `ansible/playbooks/immutable-cutover.yml` — operator-facing playbook
  that implements the synthetic validation → DNS stub → drain window →
  drain-complete sequence.
- `terraform/immutable-track/variables.tf` — `drain_window_seconds`
  and `dns_cutover_record_name` variable definitions.
