# Render the ansible inventory and SSH private key for the wrapper.
#
# Two separate files because they have different lifetimes and security
# postures. The inventory is plain YAML — checked at every run, references
# F5_API_PASSWORD via lookup('env', ...) so the password never lands on
# disk. The SSH key is written to a chmod-600 file used only for ad-hoc
# tmsh inspection during debugging; the wrapper deletes it on teardown.
#
# Both files land under build/integration/ — gitignored, regenerated each
# run. Wrapper uses build/integration/ as its working directory and
# inventory pointer.

locals {
  build_dir = "${path.module}/../../../build/integration"

  inventory_yaml = yamlencode({
    all = {
      children = {
        integration = {
          hosts = {
            "bigip-aws-01" = {
              ansible_host      = module.bigip_aws_01.mgmt_public_ip
              f5_api_base_url   = "https://${module.bigip_aws_01.mgmt_public_ip}"
              f5_api_user       = "admin"
              f5_api_password   = "{{ lookup('env', 'F5_API_PASSWORD') }}"
              f5_validate_certs = false
              ec2_instance_id   = module.bigip_aws_01.instance_id
              ec2_ami_id        = module.bigip_aws_01.ami_id
            }
            "bigip-aws-02" = {
              ansible_host      = module.bigip_aws_02.mgmt_public_ip
              f5_api_base_url   = "https://${module.bigip_aws_02.mgmt_public_ip}"
              f5_api_user       = "admin"
              f5_api_password   = "{{ lookup('env', 'F5_API_PASSWORD') }}"
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

resource "local_file" "inventory" {
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

resource "local_sensitive_file" "admin_password" {
  # The wrapper reads this and exports it as F5_API_PASSWORD before invoking
  # ansible. Writing it to a chmod-600 file rather than `terraform output`
  # avoids accidental leakage into shell history or CI logs that capture
  # output of `terraform output -json` whole.
  content              = random_password.admin.result
  filename             = "${local.build_dir}/admin_password"
  file_permission      = "0600"
  directory_permission = "0700"
}
