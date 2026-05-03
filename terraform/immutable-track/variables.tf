variable "aws_profile" {
  type        = string
  description = "Named AWS profile. Pinned to 'outlook' for the same reason as shared/integration — defense against AWS_PROFILE pollution in the operator's shell."
  default     = "outlook"
}

variable "aws_region" {
  type        = string
  description = "Region. Single-region by design."
  default     = "us-east-2"
}

variable "aws_account_id" {
  type        = string
  description = "Expected AWS account ID. Required (no default) — must be set in terraform.tfvars (gitignored). Same rationale as integration/: keeps the account ID out of source control."
}

variable "run_id" {
  type        = string
  description = "Per-run identifier baked into the CreatedAt tag and EC2 Name tags. Set by the integration wrapper to a sortable timestamp; falls back to a random string if applied directly."
  default     = ""
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR. 10.98.0.0/16 by default — different from the integration env's 10.99.0.0/16 so a leaked integration VPC and a leaked immutable-track VPC don't share a CIDR if both happen to be lying around in the account."
  default     = "10.98.0.0/16"
}

variable "subnet_cidr" {
  type        = string
  description = "Public subnet CIDR within vpc_cidr. The single ENI on the new VE attaches here."
  default     = "10.98.1.0/24"
}

variable "availability_zone" {
  type        = string
  description = "AZ for the public subnet. Pinned so reapplies don't churn on AZ reordering."
  default     = "us-east-2a"
}

variable "f5_version_pattern" {
  type        = string
  description = "Glob for the F5 BIG-IP VE PAYG AMI name. The immutable track provisions at the *target* version — the whole point of the modernization shape is that the new VE comes up directly at the version the fleet is moving to."
  default     = "F5 BIGIP-17.1.*"
}

variable "f5_license_tier" {
  type        = string
  description = "PAYG license tier. Default Good — cheapest, sufficient for declaration-portability validation."
  default     = "Good"
}

variable "f5_throughput_tier" {
  type        = string
  description = "PAYG throughput tier. 1Gbps is the cheapest tier that boots a usable VE on m5.large."
  default     = "1Gbps"
}

variable "ve_instance_type" {
  type        = string
  description = "EC2 instance type for the new VE. m5.large is F5's minimum."
  default     = "m5.large"
}

variable "explicit_mgmt_cidrs" {
  type        = list(string)
  description = "Optional override for the management ingress CIDRs. Empty list means 'detect runner egress IP via api.ipify.org and use a /32 of that'. Set explicitly when running from a known fixed network — never to 0.0.0.0/0."
  default     = []
}

variable "drain_window_seconds" {
  type        = number
  description = "Seconds the cutover playbook pauses after the DNS cutover stub fires, before signalling that the (conceptual) old VE may be destroyed. Default 1800 (30 min) matches ADR 004's recommendation; the integration test wrapper sets this to a small value (default 30 s) so the round-trip stays inside the 45-min wall clock. The variable lives in terraform — not as a magic number in the playbook — so a future operator wiring this up against a real fleet edits one place."
  default     = 1800

  validation {
    condition     = var.drain_window_seconds >= 0 && var.drain_window_seconds <= 86400
    error_message = "drain_window_seconds must be between 0 (skip drain) and 86400 (24 h)."
  }
}

variable "dns_cutover_record_name" {
  type        = string
  description = "FQDN that, in a real DNS-cutover deployment, would be flipped from old-VE EIP to new-VE EIP. The stub in dns_cutover.tf records this value as a null_resource trigger so the immutable-track plan output documents what the cutover *would* affect, even though no real DNS change happens. Override per environment when wiring real Route 53 — the variable is read by the future provider integration."
  default     = "vip.example.invalid"
}
