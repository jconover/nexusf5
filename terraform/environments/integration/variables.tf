variable "aws_profile" {
  type        = string
  description = "Named AWS profile. Pinned to 'outlook' for the same reason as shared/ — defense against AWS_PROFILE pollution in the operator's shell."
  default     = "outlook"
}

variable "aws_region" {
  type        = string
  description = "Region. Single-region by design. PR 2 doesn't model multi-region disaster recovery."
  default     = "us-east-2"
}

variable "aws_account_id" {
  type        = string
  description = "Expected AWS account ID. Required (no default) — must be set in terraform.tfvars (gitignored). Same rationale as shared/: keeps the account ID out of source control."
}

variable "run_id" {
  type        = string
  description = "Per-run identifier baked into the CreatedAt tag and EC2 Name tags. Set by the integration wrapper to a sortable timestamp; falls back to a random string if applied directly."
  default     = ""
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR. 10.99.0.0/16 by default — chosen to not overlap with anything plausibly real in the same account, since the VPC is created and destroyed per run and never peered."
  default     = "10.99.0.0/16"
}

variable "subnet_cidr" {
  type        = string
  description = "Public subnet CIDR within vpc_cidr. The single ENI per VE attaches here."
  default     = "10.99.1.0/24"
}

variable "availability_zone" {
  type        = string
  description = "AZ for the public subnet. Pinned so reapplies don't churn on AZ reordering. us-east-2a has stable EC2 capacity for the m5 family."
  default     = "us-east-2a"
}

variable "f5_version_pattern" {
  type        = string
  description = "Glob for the F5 BIG-IP VE PAYG AMI name. Threaded through both ve-instance module invocations so canary and standby boot the same AMI."
  default     = "F5 BIGIP-17.1.*"
}

variable "f5_license_tier" {
  type        = string
  description = "PAYG license tier (Good/Better/Best). Default Good — cheapest, sufficient for upgrade-pipeline tests."
  default     = "Good"
}

variable "f5_throughput_tier" {
  type        = string
  description = "PAYG throughput tier. 1Gbps is the cheapest tier that boots a usable VE on m5.large."
  default     = "1Gbps"
}

variable "ve_instance_type" {
  type        = string
  description = "EC2 instance type for both VEs. m5.large is F5's minimum and what PR 2 cost-targets against."
  default     = "m5.large"
}

variable "explicit_mgmt_cidrs" {
  type        = list(string)
  description = "Optional override for the management ingress CIDRs. Empty list means 'detect runner egress IP via icanhazip and use a /32 of that'. Set explicitly when running from a known fixed network — never to 0.0.0.0/0."
  default     = []
}
