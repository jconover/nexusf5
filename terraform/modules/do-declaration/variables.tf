variable "device_hostname" {
  type        = string
  description = "BIG-IP hostname (FQDN). Used as the System hostname in the DO declaration and in the rendered selfLinks."
}

variable "mgmt_ip" {
  type        = string
  description = "Management IP for the device. Lab default is the loopback the proxy adapter listens on."
  default     = "127.0.0.1"
}

variable "dns_servers" {
  type        = list(string)
  description = "DNS resolvers for the device's management plane. RFC1918-friendly defaults for lab use."
  default     = ["10.0.0.2"]
}

variable "ntp_servers" {
  type        = list(string)
  description = "NTP servers for clock sync."
  default     = ["10.0.0.3"]
}

variable "timezone" {
  type        = string
  description = "Timezone in Olson form (e.g. UTC, America/New_York). Default UTC keeps logs predictable."
  default     = "UTC"
}

variable "vlans" {
  type = list(object({
    name      = string
    tag       = number
    interface = string
  }))
  description = "Optional VLANs to declare in the Common tenant. Empty by default; lab does not need any."
  default     = []
}

variable "admin_password" {
  type        = string
  description = "Admin user password applied via DO. Sensitive; never log."
  sensitive   = true
  default     = "admin_pass"
}
