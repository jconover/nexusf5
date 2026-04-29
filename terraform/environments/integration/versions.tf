terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0.5"
    }
    http = {
      source  = "hashicorp/http"
      version = ">= 3.4.5"
    }
    local = {
      source  = "hashicorp/local"
      version = ">= 2.5.2"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.3"
    }
  }
}
