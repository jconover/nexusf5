locals {
  as3_payload = templatefile("${path.module}/templates/as3.json.tftpl", {
    device_hostname  = var.device_hostname
    tenant_name      = var.tenant_name
    app_name         = var.app_name
    vip_address      = var.vip_address
    pool_members     = var.pool_members
    monitor_interval = var.monitor_interval
  })
}

# bigip_as3 POSTs to /mgmt/shared/appsvcs/declare/{tenant}?async=true and polls
# /mgmt/shared/appsvcs/task/{id} until results[0].code == 200. The provider
# crashes if the POST response is missing an `id` field — the mock guarantees
# it; see app/routers/extensions.py.
resource "bigip_as3" "this" {
  as3_json    = local.as3_payload
  tenant_name = var.tenant_name
}
