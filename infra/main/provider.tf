terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.61"
    }
  }

  backend "s3" {
    bucket         = "bgucats-tfstate-851725214678"
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
