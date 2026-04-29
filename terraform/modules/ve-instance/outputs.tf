output "instance_id" {
  value       = aws_instance.ve.id
  description = "EC2 instance ID. Used by the nuclear-option teardown to filter on AutoDestroy=true."
}

output "mgmt_public_ip" {
  value       = aws_eip.ve.public_ip
  description = "Static public IP for the VE mgmt plane. Goes into ansible_host in the inventory the wrapper generates."
}

output "mgmt_public_dns" {
  value       = aws_eip.ve.public_dns
  description = "Public DNS for the EIP. Useful for human inspection; ansible uses the IP."
}

output "private_ip" {
  value       = aws_instance.ve.private_ip
  description = "Internal IP. Reserved for future HA-sync or two-NIC topologies; PR 2 single-NIC doesn't depend on it."
}

output "ami_id" {
  value       = data.aws_ami.f5_ve.id
  description = "AMI the VE booted from. Surface in run logs so a regression after F5 publishes a point release is diagnosable."
}

output "ami_name" {
  value       = data.aws_ami.f5_ve.name
  description = "Human-readable AMI name (encodes version + license tier + throughput tier). Sanity check that the data source matched what was expected."
}

output "security_group_id" {
  value       = aws_security_group.ve.id
  description = "SG ID. Mostly informational; consumers usually don't need to reference it."
}
