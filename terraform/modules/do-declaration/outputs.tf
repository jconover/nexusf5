output "declaration_id" {
  value       = bigip_do.this.id
  description = "DO resource ID. Stable across applies for the same declaration."
}

output "applied_label" {
  value       = "nexusf5-${var.device_hostname}"
  description = "Marker label embedded in the declaration; useful for cross-referencing in audit logs."
}
