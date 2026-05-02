variable "name" {
  type        = string
  description = "Hostname-like identifier for this VE. Becomes the EC2 Name tag, the iControl REST hostname after DO bootstrap, and the ansible inventory hostname. Use the bigip-{site}-{number} convention from CLAUDE.md (e.g. bigip-aws-01)."
}

variable "subnet_id" {
  type        = string
  description = "Subnet to launch the VE in. PR 2 uses a single ENI shared by management and data plane; production-shape three-NIC topologies are out of scope here."
}

variable "vpc_id" {
  type        = string
  description = "VPC the security group attaches to. Must contain subnet_id."
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type. m5.large is F5's minimum for VE; m5.xlarge is recommended for production. Good 1Gbps PAYG runs fine on m5.large for upgrade-pipeline tests."
  default     = "m5.large"
}

variable "ssh_key_name" {
  type        = string
  description = "EC2 key pair name. Must already exist in the region. The integration env generates one and surfaces the name through this variable."
}

variable "f5_version_pattern" {
  type        = string
  description = "Glob pattern for the F5 BIG-IP VE PAYG AMI name. The data source in main.tf picks the most recent match, so '17.1.*' is enough to track the current point release."
  default     = "F5 BIGIP-17.1.*"
}

variable "f5_license_tier" {
  type        = string
  description = "PAYG license tier. 'Good' is the cheapest and is sufficient for the upgrade-pipeline integration test (the test exercises iControl REST, not paid LTM features). 'Better' adds AFM/AWAF; 'Best' adds APM. Cost scales roughly 1x/2x/4x."
  default     = "Good"

  validation {
    condition     = contains(["Good", "Better", "Best"], var.f5_license_tier)
    error_message = "f5_license_tier must be one of: Good, Better, Best."
  }
}

variable "f5_throughput_tier" {
  type        = string
  description = "PAYG throughput tier. '25Mbps' is the cheapest; '1Gbps' is typical for testing. Higher tiers (3Gbps, 5Gbps) are wasted on integration tests."
  default     = "1Gbps"
}

variable "allowed_mgmt_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the VE management plane (TCP 443 + 22). Default is empty — must be set by the caller. Integration env passes the runner's egress IP; never use 0.0.0.0/0."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every resource the module creates. The integration env uses this to thread CreatedAt={timestamp} through every VE so the nuclear-option teardown can age-filter."
  default     = {}
}

variable "admin_password" {
  type        = string
  description = "Password to assign to the BIG-IP 'admin' user during first-boot bootstrap. Threaded into the f5-bigip-runtime-init YAML as a static runtime_parameter (ADMIN_PASSWORD) and rendered into the DO declaration via the {{{ADMIN_PASSWORD}}} mustache substitution. Caller is responsible for generating something unguessable (e.g. random_password); this module just transports it. Same trust boundary as the EC2 user_data — anyone with ec2:DescribeInstanceAttribute can read it, which is the existing posture for instance_id-as-password."
  sensitive   = true
}

variable "hostname_dns_suffix" {
  type        = string
  description = "DNS suffix appended to var.name to form the BIG-IP system hostname (e.g. 'nexusf5.local' → 'bigip-aws-01.nexusf5.local'). F5 DO's /Common/system.hostname constraint requires an FQDN — bare short names get rejected with 422 / 01070903:3 'hostname must be a fully qualified DNS name', which rolls back the whole declaration including admin password and shell. The suffix does not need to resolve; it just needs to make the hostname dot-containing. Override per environment when there's a real domain."
  default     = "nexusf5.local"
}

variable "mgmt_https_port" {
  type        = number
  description = "TCP port for BIG-IP iControl REST + mgmt GUI. Default 8443 matches BIG-IP 17.1.x's `sys httpd ssl-port` factory value (changed from 443 in older releases to free port 443 for data-plane VIPs in production deployments). The SG ingress rule, the wrapper's readiness probe, and the rendered ansible inventory's f5_api_base_url all read from this single variable so a future TMOS bump that shifts the default again is one edit, not five. F5 ref: BIG-IP 17.1 sys httpd manual / K-article on default mgmt ports."
  default     = 8443
}
