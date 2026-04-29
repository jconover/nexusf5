terraform {
  required_version = ">= 1.9.0"

  required_providers {
    bigip = {
      source  = "F5Networks/bigip"
      version = ">= 1.22.0"
    }
  }
}
