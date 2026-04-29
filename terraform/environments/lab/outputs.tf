output "do_declaration_ids" {
  value = {
    bigip-lab-01 = module.do_bigip_lab_01.declaration_id
    bigip-lab-02 = module.do_bigip_lab_02.declaration_id
    bigip-lab-03 = module.do_bigip_lab_03.declaration_id
    bigip-lab-04 = module.do_bigip_lab_04.declaration_id
    bigip-lab-05 = module.do_bigip_lab_05.declaration_id
  }
  description = "Per-device DO resource IDs."
}

output "as3_declaration_ids" {
  value = {
    bigip-lab-01 = module.as3_bigip_lab_01.declaration_id
    bigip-lab-02 = module.as3_bigip_lab_02.declaration_id
    bigip-lab-03 = module.as3_bigip_lab_03.declaration_id
    bigip-lab-04 = module.as3_bigip_lab_04.declaration_id
    bigip-lab-05 = module.as3_bigip_lab_05.declaration_id
  }
  description = "Per-device AS3 resource IDs."
}
