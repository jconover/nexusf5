# Two independent VEs. The kickoff specifies "HA pair" but PR 2 doesn't
# wire active/standby sync — the upgrade pipeline test exercises per-device
# flow, not HA failover. Real HA-sync logic is exercised against the 50-
# device mock-f5 stack where it doesn't cost anything. Naming follows the
# CLAUDE.md bigip-{site}-{number} convention with site=aws.

module "bigip_aws_01" {
  source = "../../modules/ve-instance"

  name      = "bigip-aws-01"
  vpc_id    = aws_vpc.integration.id
  subnet_id = aws_subnet.public.id

  ssh_key_name   = aws_key_pair.integration.key_name
  admin_password = random_password.admin.result

  instance_type      = var.ve_instance_type
  f5_version_pattern = var.f5_version_pattern
  f5_license_tier    = var.f5_license_tier
  f5_throughput_tier = var.f5_throughput_tier

  allowed_mgmt_cidrs = local.effective_mgmt_cidrs

  tags = local.per_run_tags
}

module "bigip_aws_02" {
  source = "../../modules/ve-instance"

  name      = "bigip-aws-02"
  vpc_id    = aws_vpc.integration.id
  subnet_id = aws_subnet.public.id

  ssh_key_name   = aws_key_pair.integration.key_name
  admin_password = random_password.admin.result

  instance_type      = var.ve_instance_type
  f5_version_pattern = var.f5_version_pattern
  f5_license_tier    = var.f5_license_tier
  f5_throughput_tier = var.f5_throughput_tier

  allowed_mgmt_cidrs = local.effective_mgmt_cidrs

  tags = local.per_run_tags
}
