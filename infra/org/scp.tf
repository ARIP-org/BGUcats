# Service control policies. An SCP never grants anything: it takes away, from
# every user and role in a member account, including its administrators. It
# does not apply to the management account, to service-linked roles, or to
# AWS services acting as themselves (CloudFront reading a bucket, API
# Gateway invoking a Lambda).

# --- The two that were there before this root (docs/MANUAL_STEPS.md, step 10)

# Stay in the organization, no IAM users or access keys, us-east-1 only.
resource "aws_organizations_policy" "member_guardrails" {
  name        = "bgucats-member-guardrails"
  description = "Stay in the org; no IAM users or access keys; us-east-1 only"
  type        = "SERVICE_CONTROL_POLICY"
  content     = jsonencode(jsondecode(file("${path.module}/scp-member-guardrails.json")))
}

resource "aws_organizations_policy_attachment" "member_guardrails" {
  policy_id = aws_organizations_policy.member_guardrails.id
  target_id = local.root_id
}

# Made by the owner in the console before the repo had any SCP. It overlaps
# the one above (leaving) and adds closing an account.
resource "aws_organizations_policy" "deny_leave_and_close" {
  name        = "DenyLeaveAndCloseAccount"
  description = "Prevents member accounts from leaving the organization and self closure"
  type        = "SERVICE_CONTROL_POLICY"
  content     = jsonencode(jsondecode(file("${path.module}/scp-deny-leave-and-close.json")))
}

resource "aws_organizations_policy_attachment" "deny_leave_and_close" {
  policy_id = aws_organizations_policy.deny_leave_and_close.id
  target_id = local.root_id
}

# --- The service allowlist

# Everything is denied except the services this project uses. A list of
# expensive services to deny (RDS, NAT gateways, EC2, ...) is never
# complete: AWS has hundreds of services and adds more. This way a service
# nobody has thought about is closed by default, and opening one is a change
# to this file, applied from the management account. It can never be a side
# effect of a pull request to the app.
#
# Not on the list, on purpose, until something needs them: acm and route53
# (a custom domain), sns and events (alarms, schedules), wafv2,
# secretsmanager, sqs. route53domains, shield, aws-marketplace and
# savingsplans must stay off it: each is a purchase in one API call.
locals {
  allowed_actions = [
    # The app and its deploys (infra/main, infra/bootstrap).
    "apigateway:*",
    "cloudfront:*",
    "cognito-idp:*",
    "dynamodb:*",
    "execute-api:*",
    "iam:*",
    "kms:*",
    "lambda:*",
    "logs:*",
    "s3:*",
    "ssm:*",
    "sts:*",
    # Looking: metrics, the audit trail, bills, limits, the console itself.
    "access-analyzer:*",
    "account:*",
    "billing:*",
    "budgets:*",
    "ce:*",
    "cloudtrail:Describe*",
    "cloudtrail:Get*",
    "cloudtrail:List*",
    "cloudtrail:LookupEvents",
    "cloudwatch:*",
    "consolidatedbilling:*",
    "cost-optimization-hub:*",
    "ec2:Describe*",
    "freetier:*",
    "health:*",
    "notifications:*",
    "notifications-contacts:*",
    "organizations:*",
    "pricing:*",
    "resource-explorer-2:*",
    "resource-groups:*",
    "servicequotas:*",
    "signin:*",
    "sso:*",
    "support:*",
    "tag:*",
    "trustedadvisor:*",
    "uxc:*",
  ]

  # Inside the allowed services, the calls that buy a commitment or lift a
  # ceiling. Lambda's concurrency quota and DynamoDB's on-demand mode are
  # what bound how fast this account can spend, so raising a quota is a
  # decision made here too.
  #
  # Known gap: DynamoDB offers no condition key for a table's billing mode,
  # so an administrator can still create a provisioned table. For pull
  # requests scripts/check_plan.py refuses it; for a hand-run command the
  # budget actions (budgets.tf) are what catches it.
  denied_knobs = [
    "cloudfront:CreateSavingsPlan",
    "cloudfront:UpdateSavingsPlan",
    "dynamodb:PurchaseReservedCapacityOfferings",
    "lambda:CreateCapacityProvider",
    "lambda:PutProvisionedConcurrencyConfig",
    "servicequotas:RequestServiceQuotaIncrease",
  ]

  # Rolled out in two steps. Staging first: its first deploy creates every
  # resource infra/main has, through this policy, which is the proof the
  # list is complete. Then the root, which covers production and every
  # account made later (step 13c).
  service_allowlist_targets = {
    staging = local.members.staging
  }
}

resource "aws_organizations_policy" "service_allowlist" {
  name        = "bgucats-service-allowlist"
  description = "Only the services this project uses; no commitments, no quota increases"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OnlyTheServicesWeUse"
        Effect    = "Deny"
        NotAction = local.allowed_actions
        Resource  = "*"
      },
      {
        Sid      = "NoCommitmentsNoQuotaIncreases"
        Effect   = "Deny"
        Action   = local.denied_knobs
        Resource = "*"
      },
    ]
  })
}

resource "aws_organizations_policy_attachment" "service_allowlist" {
  for_each = local.service_allowlist_targets

  policy_id = aws_organizations_policy.service_allowlist.id
  target_id = each.value
}

# --- The two the budget actions attach (budgets.tf)

# Neither is attached by Terraform. AWS Budgets attaches one to a member
# account when that account's spending crosses a line, and detaches it when
# the next month starts. Lifting one sooner: docs/deploy.md, "When a budget
# action fires".
locals {
  # The app itself: the five Lambdas' roles (infra/main). Whatever a pull
  # request writes into one, the permissions boundary caps it
  # (infra/bootstrap/lambda_boundary.tf).
  app_runtime_roles = ["arn:aws:iam::*:role/bgucats-*-lambda"]

  # People and jobs that can only look: the SSO read-only permission set
  # and the CI role, which can plan and nothing else.
  read_only_roles = [
    "arn:aws:iam::*:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_ReadOnlyAccess_*",
    "arn:aws:iam::*:role/bgucats-github-actions-ci",
  ]
}

# $20: nothing can be created or changed, by a deploy, an administrator or
# anyone else. The app keeps running and can still be looked at.
resource "aws_organizations_policy" "budget_freeze" {
  name        = "bgucats-budget-freeze"
  description = "Attached by a budget action at $20: no changes; the app keeps running"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "OnlyTheAppAndReadOnly"
      Effect   = "Deny"
      Action   = "*"
      Resource = "*"
      Condition = {
        ArnNotLike = {
          "aws:PrincipalArn" = concat(local.app_runtime_roles, local.read_only_roles)
        }
      }
    }]
  })
}

# $40: the app's own roles are denied too, so its API stops answering.
# Nothing is deleted: the table, the photos and the static pages stay, and
# what is stored keeps costing its few cents.
resource "aws_organizations_policy" "budget_stop" {
  name        = "bgucats-budget-stop"
  description = "Attached by a budget action at $40: the app's API stops; data stays"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "OnlyReadOnly"
      Effect   = "Deny"
      Action   = "*"
      Resource = "*"
      Condition = {
        ArnNotLike = {
          "aws:PrincipalArn" = local.read_only_roles
        }
      }
    }]
  })
}
