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
      instance_id    = module.bigip_aws_01.instance_id
      mgmt_public_ip = module.bigip_aws_01.mgmt_public_ip
      ami_id         = module.bigip_aws_01.ami_id
      ami_name       = module.bigip_aws_01.ami_name
    }
    "bigip-aws-02" = {
      instance_id    = module.bigip_aws_02.instance_id
      mgmt_public_ip = module.bigip_aws_02.mgmt_public_ip
      ami_id         = module.bigip_aws_02.ami_id
      ami_name       = module.bigip_aws_02.ami_name
    }
  }
  description = "Per-VE metadata. Wrapper polls mgmt_public_ip for iControl REST readiness; AMI fields surface for diagnosability when F5 publishes a point release."
}

output "inventory_path" {
  value       = local_file.inventory.filename
  description = "Absolute path to the rendered ansible inventory. Wrapper passes this to `ansible-playbook -i`."
}

output "ssh_key_path" {
  value       = local_sensitive_file.ssh_private_key.filename
  description = "Absolute path to the chmod-600 SSH private key. Used only for ad-hoc tmsh debugging."
}

output "admin_password_path" {
  value       = local_sensitive_file.admin_password.filename
  sensitive   = true
  description = "Path to the chmod-600 admin password file. Wrapper reads this and exports F5_API_PASSWORD before running ansible."
}

output "effective_mgmt_cidrs" {
  value       = local.effective_mgmt_cidrs
  description = "CIDRs the VE security groups accept mgmt traffic from. Sanity-check this is a /32 of your runner IP, never 0.0.0.0/0."
}
