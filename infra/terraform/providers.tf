terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket = "fb-marketplace-greatdeals-terraform-state"
    key    = "fb-marketplace-greatdeals/terraform.tfstate"
    region = "ca-central-1"
  }
}

provider "aws" {
  region = var.region
}
