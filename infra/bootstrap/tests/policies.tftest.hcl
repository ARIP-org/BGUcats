# The deploy, CI and Lambda roles' policies, checked before AWS sees them.
#
#   terraform -chdir=infra/bootstrap init -backend=false
#   terraform -chdir=infra/bootstrap test
#
# Nothing here reaches AWS: the provider is a mock, and the IDs and ARNs it
# would make up are replaced by ones of the real length, because the size
# of a policy is what is being measured. bootstrap-apply.sh runs this before
# every plan.
#
# Why sizes: IAM refuses a role whose inline policies add up to more than
# 10,240 characters, and a managed policy over 6,144. It refuses at apply,
# part-way through, in an account where the deploy role is the thing being
# changed. On 2026-11-12 the deploy role measured 8,407 before the app
# plan's additions (docs/notes.md, "Deploying and Terraform").

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "395591097129" }
  }
  override_data {
    target = data.aws_kms_alias.ssm
    values = { target_key_arn = "arn:aws:kms:us-east-1:395591097129:key/12345678-1234-1234-1234-123456789012" }
  }
  override_data {
    target = data.aws_iam_policy_document.github_actions_trust
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.github_actions_deploy_trust
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

override_resource {
  target = aws_iam_policy.lambda_boundary
  values = { arn = "arn:aws:iam::395591097129:policy/bgucats-lambda-permissions-boundary" }
}

override_resource {
  target = aws_iam_openid_connect_provider.github_actions
  values = { arn = "arn:aws:iam::395591097129:oidc-provider/token.actions.githubusercontent.com" }
}

override_resource {
  target = aws_s3_bucket.tfstate
  values = { arn = "arn:aws:s3:::bgucats-tfstate-395591097129" }
}

override_resource {
  target = aws_dynamodb_table.tfstate_lock
  values = { arn = "arn:aws:dynamodb:us-east-1:395591097129:table/bgucats-tfstate-lock" }
}

variables {
  environment        = "staging"
  budget_alert_email = "nobody@example.com"
}

run "policies" {
  command = apply

  # 10,240 is AWS's limit for all of a role's inline policies together. The
  # margin covers the difference between these made-up ARNs and real ones.
  assert {
    condition = sum([for p in [
      aws_iam_role_policy.github_actions_deploy_state.policy,
      aws_iam_role_policy.github_actions_deploy_storage.policy,
      aws_iam_role_policy.github_actions_deploy_compute.policy,
      aws_iam_role_policy.github_actions_deploy_edge.policy,
      aws_iam_role_policy.github_actions_deploy_alerts.policy,
      aws_iam_role_policy.github_actions_deploy_guards.policy,
    ] : length(p)]) <= 10000
    error_message = "The deploy role's inline policies are over 10,000 characters together (AWS refuses past 10,240). Move statements into a managed policy before adding more."
  }

  assert {
    condition = sum([for p in [
      aws_iam_role_policy.github_actions_ci_kms_list.policy,
      aws_iam_role_policy.github_actions_ci_state_access.policy,
      aws_iam_role_policy.github_actions_ci_plan_read.policy,
    ] : length(p)]) <= 10000
    error_message = "The CI role's inline policies are over 10,000 characters together (AWS refuses past 10,240)."
  }

  assert {
    condition     = length(aws_iam_policy.lambda_boundary.policy) <= 6000
    error_message = "The Lambda permissions boundary is over 6,000 characters (a managed policy is refused past 6,144)."
  }

  # Deleting a store is never something the deploy role is allowed: the
  # dataset, the state and the user pool outlive any deploy.
  assert {
    condition = alltrue(flatten([for p in [
      aws_iam_role_policy.github_actions_deploy_state.policy,
      aws_iam_role_policy.github_actions_deploy_storage.policy,
      aws_iam_role_policy.github_actions_deploy_compute.policy,
      aws_iam_role_policy.github_actions_deploy_edge.policy,
      aws_iam_role_policy.github_actions_deploy_alerts.policy,
      ] : [for s in jsondecode(p).Statement :
      s.Effect != "Allow" || length(setintersection(
        toset(flatten([try(s.Action, [])])),
        toset(["dynamodb:DeleteTable", "dynamodb:DeleteBackup", "s3:DeleteBucket", "cognito-idp:DeleteUserPool"]),
      )) == 0
    ]]))
    error_message = "A deploy role statement allows deleting a table, a bucket or the user pool."
  }

  # An event source mapping may only be created, changed or deleted for one
  # of our own functions: the condition is the only scope AWS offers.
  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.github_actions_deploy_compute.policy).Statement :
      length(setintersection(
        toset(flatten([try(s.Action, [])])),
        toset(["lambda:CreateEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"]),
        )) == 0 || try(
        s.Condition.StringLike["lambda:FunctionArn"] == "arn:aws:lambda:us-east-1:395591097129:function:bgucats-*",
        false,
      )
    ])
    error_message = "An event source mapping action is allowed without the bgucats-* function condition."
  }
}
