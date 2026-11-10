# The organization's guardrails: what no member account may do, whoever asks.
#
# Everything here lives in the management account (851725214678) and acts on
# the member accounts from outside. That is the point: infra/main and
# infra/bootstrap are applied inside an account, by roles a pull request can
# influence. Nothing inside a member account, not its administrator and not
# its deploy role, can change or remove what this root attaches to it.
#
#   scp.tf      service control policies: the two that existed before this
#               root (imported), the service allowlist, and the two the
#               budget actions attach
#   budgets.tf  one budget per member account, and what happens at $20 and $40
#   anomaly.tf  Cost Anomaly Detection, at a threshold this project can reach
#
# Applied with infra/scripts/org-apply.sh from an SSO session on the
# management account, never by CI: no GitHub role exists in that account,
# and none should. Runbook: docs/MANUAL_STEPS.md, step 13.

terraform {
  required_version = ">= 1.10" # use_lockfile

  # The bucket is the one thing this root cannot create: its own state lives
  # there. org-apply.sh makes it on the first run (versioned, private). The
  # lock is a file in the bucket, so there is no lock table to pay for.
  backend "s3" {
    bucket       = "bgucats-org-tfstate-851725214678"
    key          = "org/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

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
data "aws_organizations_organization" "this" {}

locals {
  root_id = data.aws_organizations_organization.this.roots[0].id

  # The member accounts, read from the files that already name them, so an
  # account ID is still written in one place (infra/scripts/aws-guard.sh
  # reads the same two files).
  members = {
    production = regex("bgucats-tfstate-([0-9]{12})", file("${path.module}/../main/backend/prod.hcl"))[0]
    staging    = regex("bgucats-tfstate-([0-9]{12})", file("${path.module}/../main/backend/staging.hcl"))[0]
  }

  # Where budget and anomaly emails go: the management account's own
  # address, which the organization already knows. Not a variable, so no
  # apply can send them anywhere else by mistake.
  alert_email = data.aws_organizations_organization.this.master_account_email
}

# A plan against any other account stops here, before it can propose to
# recreate the organization's policies somewhere they do not belong.
check "management_account" {
  assert {
    condition     = data.aws_caller_identity.current.account_id == data.aws_organizations_organization.this.master_account_id
    error_message = "infra/org is applied from the organization's management account only."
  }
}
