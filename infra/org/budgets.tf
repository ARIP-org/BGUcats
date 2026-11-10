# A spending limit that acts, not only one that writes an email.
#
# AWS has no hard cap: nothing stops an account at a dollar figure by
# itself. The nearest thing is a budget action, which attaches a service
# control policy to the account when its spending crosses a line.
#
#   $10  email only: the budget inside each account (infra/bootstrap)
#   $20  bgucats-budget-freeze: no creates or changes; the app keeps running
#   $40  bgucats-budget-stop:   the app's API stops; data and pages stay
#
# What this cannot do, said plainly: AWS Budgets sees spending some hours
# late (its figures update a few times a day), so the limit is "$40 plus
# whatever was spent before Budgets noticed". The service allowlist and the
# account's own quotas (scp.tf) are what keep that remainder small.
#
# AWS detaches both policies when the next month starts. The first two
# budgets with actions are free; a third would cost $0.10 a day.

locals {
  freeze_at_usd = 20
  stop_at_usd   = 40
}

resource "aws_budgets_budget" "member" {
  for_each = local.members

  name        = "bgucats-${each.key}-limit"
  budget_type = "COST"
  time_unit   = "MONTHLY"
  # The actions below use dollar thresholds, so this figure only labels the
  # budget in the console: the level the account's own budget emails at.
  limit_amount = "10"
  limit_unit   = "USD"

  cost_filter {
    name   = "LinkedAccount"
    values = [each.value]
  }

  # What was used, before credits and refunds. A credit that hides a
  # runaway bill this month is gone the next.
  cost_types {
    include_credit = false
    include_refund = false
  }
}

# The role AWS Budgets assumes to attach and detach those two policies on
# those two accounts, and nothing else.
resource "aws_iam_role" "budget_actions" {
  name        = "bgucats-budget-actions"
  description = "Assumed by AWS Budgets to attach the freeze and stop SCPs to a member account."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/bgucats-*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "budget_actions" {
  name = "attach-budget-scps"
  role = aws_iam_role.budget_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["organizations:AttachPolicy", "organizations:DetachPolicy"]
      Resource = concat(
        [aws_organizations_policy.budget_freeze.arn, aws_organizations_policy.budget_stop.arn],
        [for id in values(local.members) :
        "arn:aws:organizations::${data.aws_caller_identity.current.account_id}:account/${data.aws_organizations_organization.this.id}/${id}"],
      )
    }]
  })
}

resource "aws_budgets_budget_action" "freeze" {
  for_each = local.members

  budget_name        = aws_budgets_budget.member[each.key].name
  action_type        = "APPLY_SCP_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_actions.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = local.freeze_at_usd
  }

  definition {
    scp_action_definition {
      policy_id  = aws_organizations_policy.budget_freeze.id
      target_ids = [each.value]
    }
  }

  subscriber {
    address           = local.alert_email
    subscription_type = "EMAIL"
  }

  # Budgets checks the role when the action is made.
  depends_on = [aws_iam_role_policy.budget_actions]
}

resource "aws_budgets_budget_action" "stop" {
  for_each = local.members

  budget_name        = aws_budgets_budget.member[each.key].name
  action_type        = "APPLY_SCP_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_actions.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = local.stop_at_usd
  }

  definition {
    scp_action_definition {
      policy_id  = aws_organizations_policy.budget_stop.id
      target_ids = [each.value]
    }
  }

  subscriber {
    address           = local.alert_email
    subscription_type = "EMAIL"
  }

  depends_on = [aws_iam_role_policy.budget_actions]
}
