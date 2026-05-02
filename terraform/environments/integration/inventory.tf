# Render the ansible inventory and SSH private key for the wrapper.
#
# Inventory is YAML, chmod 600, regenerated per run. f5_api_password is
# the random_password generated in main.tf and threaded into each VE's
# user_data so f5-bigip-runtime-init sets it on first boot. Putting it
# inline rather than via env-var lookup is the simplest correct shape:
# the inventory file is already gitignored and 0600, both VEs share the
# same password (one random_password resource), and the wrapper reads
# the password from the (sensitive) terraform output for its iControl
# REST readiness probe.

locals {
  build_dir = "${path.module}/../../../build/integration"

  inventory_yaml = yamlencode({
    all = {
      children = {
        integration = {
          hosts = {
            "bigip-aws-01" = {
              ansible_host      = module.bigip_aws_01.mgmt_public_ip
              f5_api_base_url   = "https://${module.bigip_aws_01.mgmt_public_ip}:${module.bigip_aws_01.mgmt_https_port}"
              f5_api_user       = "admin"
              f5_api_password   = random_password.admin.result
              f5_validate_certs = false
              ec2_instance_id   = module.bigip_aws_01.instance_id
              ec2_ami_id        = module.bigip_aws_01.ami_id
            }
            "bigip-aws-02" = {
              ansible_host      = module.bigip_aws_02.mgmt_public_ip
              f5_api_base_url   = "https://${module.bigip_aws_02.mgmt_public_ip}:${module.bigip_aws_02.mgmt_https_port}"
              f5_api_user       = "admin"
              f5_api_password   = random_password.admin.result
              f5_validate_certs = false
              ec2_instance_id   = module.bigip_aws_02.instance_id
              ec2_ami_id        = module.bigip_aws_02.ami_id
            }
          }
          vars = {
            ansible_connection         = "local"
            f5_api_timeout             = 30
            f5_target_version          = "17.1.0"
            f5_postcheck_drift_enabled = false
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
