# What the GitHub roles (github_oidc.tf, deploy_role.tf) and the Lambda
# permissions boundary (lambda_boundary.tf) are scoped to: infra/main's
# resources. This root and infra/main deliberately share no state, so they
# are written out here.
#
# Names are ones we chose, so they are stable. IDs are ones AWS assigned to
# resources that have no name-based ARN (API Gateway, CloudFront, Cognito).
# The account also hosts schedule-ai-app, which has one of each, so a
# wildcard over those services would cover its resources too. Pinning the
# deploy role to our IDs also means that replacing one of these resources
# (a new ID) fails the deploy instead of happening silently: the owner
# updates the ID here first. Read them with
#   terraform -chdir=infra/main state show <address>
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

  api_id                  = "kxle008kl8"                         # aws_apigatewayv2_api.main
  cloudfront_distribution = ["E1KM1WXCPKSU13", "E1DFTNHZ0NL01S"] # .site, .web
  cloudfront_oac          = ["EW78DHJ9WGKM9", "E38522F4F2GXTV"]  # .site, .web
  cognito_user_pool_arn   = "arn:aws:cognito-idp:us-east-1:${local.account_id}:userpool/us-east-1_iLd1I4gJ9"
}
