# Render the ansible inventory and SSH private key for the wrapper.
#
# Same shape as terraform/environments/integration/inventory.tf with two
# deltas:
#   * Single host (bigip-aws-new), not an HA pair
#   * f5_postcheck_drift_enabled=true and f5_postcheck_version_check_enabled
#     =false — the immutable track validates "did the apply succeed" via the
#     drift gate alone (see ADR 003 + the f5_postcheck role README).
#   * f5_postcheck_terraform_env_path points at this directory so the
#     drift gate runs against this state.

locals {
  build_dir = "${path.module}/../../build/integration-immutable"

  inventory_yaml = yamlencode({
    all = {
      children = {
        immutable_new = {
          hosts = {
            "bigip-aws-new" = {
              ansible_host      = module.bigip_aws_new.mgmt_public_ip
              f5_api_base_url   = "https://${module.bigip_aws_new.mgmt_public_ip}:${module.bigip_aws_new.mgmt_https_port}"
              f5_api_user       = "admin"
              f5_api_password   = random_password.admin.result
              f5_validate_certs = false
              ec2_instance_id   = module.bigip_aws_new.instance_id
              ec2_ami_id        = module.bigip_aws_new.ami_id
            }
          }
          vars = {
            ansible_connection                 = "local"
            f5_api_timeout                     = 30
            f5_postcheck_drift_enabled         = true
            f5_postcheck_version_check_enabled = false
            f5_postcheck_terraform_env_path    = abspath("${path.module}")
            immutable_drain_window_seconds     = var.drain_window_seconds
            immutable_dns_cutover_record_name  = var.dns_cutover_record_name
          }
        }
      }
    }
  })
}

resource "local_sensitive_file" "inventory" {
  content              = local.inventory_yaml
  filename             = "${local.build_dir}/inventory.yml"
  file_permission      = "0600"
  directory_permission = "0700"
}

resource "local_sensitive_file" "ssh_private_key" {
  content              = tls_private_key.ssh.private_key_pem
  filename             = "${local.build_dir}/ssh_key"
  file_permission      = "0600"
  directory_permission = "0700"
}
