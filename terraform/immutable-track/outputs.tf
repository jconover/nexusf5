output "run_id" {
  value       = local.run_id
  description = "The CreatedAt tag value applied to every resource. Wrapper logs this for cross-referencing run logs to AWS resources."
}

output "vpc_id" {
  value       = aws_vpc.this.id
  description = "Per-run VPC ID. Useful when grepping CloudTrail for everything one run touched."
}

output "ve_endpoints" {
  value = {
    "bigip-aws-new" = {
      instance_id     = module.bigip_aws_new.instance_id
      mgmt_public_ip  = module.bigip_aws_new.mgmt_public_ip
      mgmt_https_port = module.bigip_aws_new.mgmt_https_port
      ami_id          = module.bigip_aws_new.ami_id
      ami_name        = module.bigip_aws_new.ami_name
    }
  }
  description = "Per-VE metadata. Wrapper polls (mgmt_public_ip, mgmt_https_port) for iControl REST readiness. Single-entry map keeps the shape symmetric with the integration env so the wrapper's VE-iteration loops do not need a separate code path."
}

output "inventory_path" {
  value       = local_sensitive_file.inventory.filename
  description = "Absolute path to the rendered ansible inventory (chmod 600). Wrapper passes this to `ansible-playbook -i`."
}

output "ssh_key_path" {
  value       = local_sensitive_file.ssh_private_key.filename
  description = "Absolute path to the chmod-600 SSH private key. Used only for ad-hoc tmsh debugging on a wedged VE."
}

output "effective_mgmt_cidrs" {
  value       = local.effective_mgmt_cidrs
  description = "CIDRs the VE security group accepts mgmt traffic from. Sanity-check this is a /32 of your runner IP, never 0.0.0.0/0."
}

output "admin_password" {
  value       = random_password.admin.result
  sensitive   = true
  description = "BIG-IP admin user password for this run. Set on first boot by f5-bigip-runtime-init. Wrapper reads this via `terraform output -raw` to authenticate iControl REST readiness probes."
}

output "drain_window_seconds" {
  value       = var.drain_window_seconds
  description = "Drain window the cutover playbook pauses for after the DNS stub fires. Surfaced as an output so the wrapper can echo it into run logs without re-deriving the value."
}

output "dns_cutover_record_name" {
  value       = var.dns_cutover_record_name
  description = "FQDN the DNS cutover would flip. Surfaced for run-log clarity; the stub does not actually change DNS."
}
