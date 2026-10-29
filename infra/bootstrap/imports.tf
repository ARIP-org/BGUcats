# This root keeps local state, and that state lived on whichever machine ran
# the first apply. Rather than depend on finding that file, these blocks let
# a fresh checkout adopt what already exists: the first plan shows them as
# "will be imported", and after that they are no-ops. A machine that still
# has the original state sees nothing at all for them.
#
# Everything bootstrap created before the deploy role is listed. A resource
# missing from this list would show up as "will be created" and then fail
# with "already exists", which is the safe way to find out.

import {
  to = aws_s3_bucket.tfstate
  id = "bgucats-tfstate-851725214678"
}

import {
  to = aws_s3_bucket_versioning.tfstate
  id = "bgucats-tfstate-851725214678"
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.tfstate
  id = "bgucats-tfstate-851725214678"
}

import {
  to = aws_s3_bucket_public_access_block.tfstate
  id = "bgucats-tfstate-851725214678"
}

import {
  to = aws_dynamodb_table.tfstate_lock
  id = "bgucats-tfstate-lock"
}

import {
  to = aws_iam_openid_connect_provider.github_actions
  id = "arn:aws:iam::851725214678:oidc-provider/token.actions.githubusercontent.com"
}

import {
  to = aws_iam_role.github_actions_ci
  id = "bgucats-github-actions-ci"
}

import {
  to = aws_iam_role_policy.github_actions_ci_kms_list
  id = "bgucats-github-actions-ci:bgucats-kms-list-aliases"
}

import {
  to = aws_iam_role_policy.github_actions_ci_state_access
  id = "bgucats-github-actions-ci:bgucats-tfstate-read"
}

import {
  to = aws_iam_role_policy.github_actions_ci_plan_read
  id = "bgucats-github-actions-ci:bgucats-plan-read-infra-main"
}
