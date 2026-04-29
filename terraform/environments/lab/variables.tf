variable "canary_devices" {
  type = list(object({
    hostname = string
    port     = number
  }))
  description = "5 canary devices addressed via the proxy adapter (mock-f5/proxy). Source of truth: mock-f5/manifests/canary.json. Order is significant: provider aliases below are wired by index."
}

variable "f5_username" {
  type        = string
  description = "BIG-IP admin user. Mock accepts anything."
  default     = "admin"
}

variable "f5_password" {
  type        = string
  description = "BIG-IP admin password. Mock accepts anything; real environments override via TF_VAR_f5_password from a secrets backend."
  sensitive   = true
  default     = "admin_pass"
}
