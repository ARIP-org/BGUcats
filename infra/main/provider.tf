terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.61"
    }
  }

  # Partial configuration: which account's state bucket is a per-account
  # file, backend/<env>.hcl, passed to init with -backend-config. Nothing
  # else in this root names an account.
  backend "s3" {
    key            = "main/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "bgucats-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project   = "bgucats"
      ManagedBy = "terraform"
    }
  }
}
