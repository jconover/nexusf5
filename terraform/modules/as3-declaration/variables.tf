variable "device_hostname" {
  type        = string
  description = "BIG-IP hostname this declaration targets. Surfaces in the AS3 label and helps audit logs."
}

variable "tenant_name" {
  type        = string
  description = "AS3 tenant name. Becomes a key under the ADC declaration and the URL segment for the read endpoint."
  default     = "nexusf5_lab"
}

variable "app_name" {
  type        = string
  description = "Application name within the tenant."
  default     = "lab_app"
}

variable "vip_address" {
  type        = string
  description = "Virtual IP for the Service_HTTP. Use RFC1918 only (CLAUDE.md rule)."
  default     = "10.10.0.10"
}

variable "pool_members" {
  type = list(object({
    ip   = string
    port = number
  }))
  description = "Pool members for the lab app. Two members give the monitor something to mark up."
  default = [
    { ip = "10.10.1.10", port = 80 },
    { ip = "10.10.1.11", port = 80 },
  ]
}

variable "monitor_interval" {
  type        = number
  description = "HTTP monitor poll interval in seconds."
  default     = 5
}
