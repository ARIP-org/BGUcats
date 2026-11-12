# What the GitHub roles (github_oidc.tf, deploy_role.tf) and the Lambda
# permissions boundary (lambda_boundary.tf) are scoped to: infra/main's
# resources. This root and infra/main deliberately share no state, so they
# are written out here.
#
# Names are ones we chose, so they are stable, and the policies name them.
# API Gateway, CloudFront and Cognito have no name-based ARNs: AWS assigns
# an ID at creation. Those are scoped to the account instead. That is
# exact, because each account (sasha-bgucats-prod, bgucats-staging) runs bgucats and
# nothing else, and it is what lets a deploy into an empty account create
# them. Until 2026-10 the account was shared with schedule-ai-app and the
# policies were pinned to our IDs; that reason is gone.
locals {
  account_id = data.aws_caller_identity.current.account_id

  app_bucket_names = [
    "bgucats-media-${local.account_id}",
    "bgucats-site-${local.account_id}",
    "bgucats-admin-web-${local.account_id}",
  ]
  app_bucket_arns = [for b in local.app_bucket_names : "arn:aws:s3:::${b}"]

  # Buckets whose objects Terraform manages (aws_s3_object). Not media.
  published_object_arns = [
    "arn:aws:s3:::bgucats-site-${local.account_id}/*",
    "arn:aws:s3:::bgucats-admin-web-${local.account_id}/*",
  ]

  data_table_arn = "arn:aws:dynamodb:us-east-1:${local.account_id}:table/bgucats-data"

  # The second table: everything people do in the app (docs/app-plan/,
  # decided 2026-11-12). Kept apart so the member API's role can be given
  # this table and not the dataset.
  social_table_arn = "arn:aws:dynamodb:us-east-1:${local.account_id}:table/bgucats-social"
  app_table_arns   = [local.data_table_arn, local.social_table_arn]

  # The events Lambda reads the social table's stream through one of these.
  # AWS gives each an ID, not a name we choose.
  event_source_mapping_arns = "arn:aws:lambda:us-east-1:${local.account_id}:event-source-mapping:*"

  # API Gateway ARNs carry no account; the role's credentials only ever act
  # in their own account, so region-wide is account-wide.
  apigateway_arns = [
    "arn:aws:apigateway:us-east-1::/apis",
    "arn:aws:apigateway:us-east-1::/apis/*",
    "arn:aws:apigateway:us-east-1::/tags/*",
  ]
  cloudfront_distribution_arns = "arn:aws:cloudfront::${local.account_id}:distribution/*"
  cloudfront_oac_arns          = "arn:aws:cloudfront::${local.account_id}:origin-access-control/*"
  cognito_user_pool_arns       = "arn:aws:cognito-idp:us-east-1:${local.account_id}:userpool/*"

  # alarms.tf: one topic and alarms named bgucats-*.
  alerts_topic_arn = "arn:aws:sns:us-east-1:${local.account_id}:bgucats-alerts"
  alarm_arns       = "arn:aws:cloudwatch:us-east-1:${local.account_id}:alarm:bgucats-*"
}
