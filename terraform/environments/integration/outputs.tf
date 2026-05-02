output "run_id" {
  value       = local.run_id
  description = "The CreatedAt tag value applied to every resource. Wrapper logs this for cross-referencing run logs to AWS resources."
}

output "vpc_id" {
  value       = aws_vpc.integration.id
  description = "Per-run VPC ID. Useful when grepping CloudTrail for everything one run touched."
}

output "ve_endpoints" {
  value = {
    "bigip-aws-01" = {
      instance_id     = module.bigip_aws_01.instance_id
      mgmt_public_ip  = module.bigip_aws_01.mgmt_public_ip
      mgmt_https_port = module.bigip_aws_01.mgmt_https_port
      ami_id          = module.bigip_aws_01.ami_id
      ami_name        = module.bigip_aws_01.ami_name
    }
    "bigip-aws-02" = {
      instance_id     = module.bigip_aws_02.instance_id
      mgmt_public_ip  = module.bigip_aws_02.mgmt_public_ip
      mgmt_https_port = module.bigip_aws_02.mgmt_https_port
      ami_id          = module.bigip_aws_02.ami_id
      ami_name        = module.bigip_aws_02.ami_name
    }
  }
  description = "Per-VE metadata. Wrapper polls (mgmt_public_ip, mgmt_https_port) for iControl REST readiness; AMI fields surface for diagnosability when F5 publishes a point release."
}

output "inventory_path" {
  value       = local_sensitive_file.inventory.filename
  description = "Absolute path to the rendered ansible inventory (chmod 600). Wrapper passes this to `ansible-playbook -i`. Inventory contains per-host f5_api_password (= EC2 instance ID) so it's chmod-600 even though the password isn't a long-lived secret."
}

output "ssh_key_path" {
  value       = local_sensitive_file.ssh_private_key.filename
  description = "Absolute path to the chmod-600 SSH private key. Used only for ad-hoc tmsh debugging."
}

output "effective_mgmt_cidrs" {
  value       = local.effective_mgmt_cidrs
  description = "CIDRs the VE security groups accept mgmt traffic from. Sanity-check this is a /32 of your runner IP, never 0.0.0.0/0."
}

output "admin_password" {
  value       = random_password.admin.result
  sensitive   = true
  description = "The BIG-IP admin user password for this run. Set on first boot by f5-bigip-runtime-init. Wrapper reads this via `terraform output -json` to authenticate iControl REST readiness probes; ansible reads it from the rendered inventory. Same value for both bigip-aws-01 and bigip-aws-02."
}
