locals {
  do_payload = templatefile("${path.module}/templates/do.json.tftpl", {
    device_hostname = var.device_hostname
    dns_servers     = var.dns_servers
    ntp_servers     = var.ntp_servers
    timezone        = var.timezone
    vlans           = var.vlans
  })
}

# bigip_do submits the rendered declaration to /mgmt/shared/declarative-onboarding
# and polls the task endpoint until completion. Async semantics live in the
# provider — see app/routers/extensions.py for the contract this module relies on.
resource "bigip_do" "this" {
  do_json = local.do_payload
  timeout = 10
}
