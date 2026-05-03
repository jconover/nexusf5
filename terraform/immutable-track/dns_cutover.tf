# DNS cutover stub.
#
# This file is *deliberately* a stub. The immutable track demonstrates the
# shape of a DNS-based cutover (provision new at target → validate → flip
# DNS → drain old → destroy old) without wiring real DNS. Half-finished
# Route 53 integration is worse than no integration: it would obscure the
# fact that this is a demonstration and add real-world failure modes (TTL
# propagation, account boundaries, missing IAM permissions) that aren't
# the point of the demonstration.
#
# Where real DNS plugs in, in three concrete extension shapes:
#
# 1. AWS Route 53 (most common):
#
#      resource "aws_route53_record" "vip" {
#        zone_id = data.aws_route53_zone.target.zone_id
#        name    = var.dns_cutover_record_name
#        type    = "A"
#        ttl     = 60
#        records = [module.bigip_aws_new.mgmt_public_ip]
#        # On apply: the record is updated atomically from old-VE EIP to
#        # new-VE EIP. Drain window starts when the old VE's TTL expires,
#        # not when terraform apply returns — the playbook accounts for
#        # this with var.drain_window_seconds (see ADR 004).
#      }
#
# 2. External provider (Cloudflare, NS1, GoDaddy, etc.):
#    Same shape, different resource type. The immutable track does not
#    care which provider; the stub exists so a future implementer drops
#    in their resource block here, leaves dns_cutover_record_name as the
#    input, and gets the same drain-window semantics.
#
# 3. Manual cutover (rare, bridges the demo gap when DNS is owned by a
#    different team): replace this null_resource with a documented
#    operator handoff — e.g. Slack notification + checklist link.
#
# The stub itself is a null_resource keyed off var.dns_cutover_record_name
# and the new VE's EIP. It surfaces in plan output ("would cut over
# vip.example.invalid → 10.0.0.42") so the demonstration is visible
# without doing anything dangerous. It does not call any DNS provider.
# Apply is a no-op after the first run unless the EIP changes, which only
# happens on VE replacement.

resource "null_resource" "dns_cutover_stub" {
  triggers = {
    record_name  = var.dns_cutover_record_name
    new_vip_ip   = module.bigip_aws_new.mgmt_public_ip
    new_vip_dns  = module.bigip_aws_new.mgmt_public_dns
    drain_window = var.drain_window_seconds
  }

  provisioner "local-exec" {
    command = "printf '[dns_cutover_stub] would flip %s -> %s (no real DNS change in this demonstration; drain window %d seconds)\\n' '${var.dns_cutover_record_name}' '${module.bigip_aws_new.mgmt_public_ip}' ${var.drain_window_seconds}"
  }
}
