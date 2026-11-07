# This root module creates the Terraform backend (S3 state bucket + DynamoDB
# lock table) that every other root module uses, the GitHub Actions roles,
# and the permissions boundary for infra/main's roles. It can't depend on
# that backend itself, so it keeps local state (a copy goes into the state
# bucket after each apply), and it is applied by the owner, by hand, with an
# SSO admin session: never by CI, and never by the deploy role it creates.
# See infra/README.md.

terraform {
  required_version = ">= 1.9"

  # Local state, one file per account: infra/scripts/bootstrap-apply.sh
  # passes -backend-config=path=state/<account>.tfstate. A copy goes to
  # that account's state bucket after each apply.
  backend "local" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.61"
    }
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

data "aws_caller_identity" "current" {}

# Which copy of the app this account runs: "production" (sasha-bgucats-prod)
# or "staging" (bgucats-staging). The deploy role trusts only GitHub jobs in
# the environment of the same name. bootstrap-apply.sh sets it from the
# profile; no default, so it is never a guess.
variable "environment" {
  description = "production or staging: the GitHub environment this account's deploy role trusts."
  type        = string

  validation {
    condition     = contains(["production", "staging"], var.environment)
    error_message = "environment must be \"production\" or \"staging\"."
  }
}

resource "aws_s3_bucket" "tfstate" {
  bucket = "bgucats-tfstate-${data.aws_caller_identity.current.account_id}"

  # Every deployed resource is found through this bucket's state. Losing it
  # means importing all of infra/main by hand.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "bgucats-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.id
}

output "tfstate_lock_table" {
  value = aws_dynamodb_table.tfstate_lock.name
}
