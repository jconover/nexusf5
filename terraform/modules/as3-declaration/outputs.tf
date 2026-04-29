output "tenant_name" {
  value       = var.tenant_name
  description = "Echoed back so callers can drive the read endpoint without re-deriving the value."
}

output "declaration_id" {
  value       = bigip_as3.this.id
  description = "AS3 resource ID."
}
