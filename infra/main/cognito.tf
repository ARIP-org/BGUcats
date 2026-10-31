# Admin identity. Google is the only way in — there are no passwords in this
# pool at all, so there is nothing to leak, rotate, or reset.
#
# Access is granted by the DynamoDB allowlist, not by email domain: a
# "@post.bgu.ac.il ends in the right thing" rule would make every student at
# the university an admin over the whole dataset.

resource "aws_cognito_user_pool" "admins" {
  name = "bgucats-admins"

  auto_verified_attributes = ["email"]

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 1
      max_length = 254
    }
  }

  lambda_config {
    pre_sign_up = aws_lambda_function.admin_presignup.arn
  }
}

resource "aws_lambda_permission" "cognito_presignup" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.admin_presignup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.admins.arn
}

# Google is the identity provider, and its client secret is the one value
# Terraform must not hold: Cognito returns it on every read, so it would sit
# in the state that the CI role reads to plan. The provider is created and
# updated outside Terraform, by the owner, with
# `infra/scripts/set-secret.sh google-oauth` (Google Cloud walkthrough:
# infra/README.md). In a new account, run that after the user pool exists
# and before the app client is created: the client names "Google", and
# Cognito refuses a client whose provider does not exist yet.
#
# Until 2026-10-31 this was aws_cognito_identity_provider.google. The
# removed block lets Terraform forget it without deleting it.
removed {
  from = aws_cognito_identity_provider.google
  lifecycle {
    destroy = false
  }
}

locals {
  google_provider_name = "Google"
}

resource "aws_cognito_user_pool_domain" "admins" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.admins.id

  # Managed login (2), not the classic hosted UI (1). Only managed login
  # passes the app's prompt=select_account on to Google, and without it
  # Google silently reuses the account the phone is signed in to — so a
  # person turned away, or signed out, could never choose another account.
  # Included in the pool's Essentials tier; no change in cost.
  managed_login_version = 2
}

# Managed login will not serve an app client that has no style. Nobody
# normally sees these pages — the app goes straight to Google — so Cognito's
# own defaults are enough.
resource "aws_cognito_managed_login_branding" "web" {
  user_pool_id                = aws_cognito_user_pool.admins.id
  client_id                   = aws_cognito_user_pool_client.web.id
  use_cognito_provided_values = true
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "bgucats-admin-web"
  user_pool_id = aws_cognito_user_pool.admins.id

  # Public client: the SPA holds no secret and uses authorization code + PKCE,
  # which is the only correct flow for code that ships to a browser.
  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = [local.google_provider_name]

  # No SRP, no admin password auth, no refresh-less flows — the pool has no
  # passwords, so every one of these would be dead surface area.
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]

  callback_urls = ["https://${aws_cloudfront_distribution.web.domain_name}/"]
  logout_urls   = ["https://${aws_cloudfront_distribution.web.domain_name}/"]

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# The first admin, so the tool is usable before anyone can log in to add
# admins through it. Terraform-managed on purpose: it also means you cannot
# permanently lock yourself out through the UI — the next apply puts it back.
resource "aws_dynamodb_table_item" "bootstrap_admin" {
  table_name = aws_dynamodb_table.data.name
  hash_key   = aws_dynamodb_table.data.hash_key
  range_key  = aws_dynamodb_table.data.range_key

  item = jsonencode({
    PK      = { S = "ADMIN#${lower(var.bootstrap_admin_email)}" }
    SK      = { S = "META" }
    email   = { S = lower(var.bootstrap_admin_email) }
    addedAt = { S = "bootstrap" }
    addedBy = { S = "terraform" }
    GSI2PK  = { S = "ENTITY#ADMIN" }
    GSI2SK  = { S = lower(var.bootstrap_admin_email) }
  })

  lifecycle {
    # Admins added through the UI are not Terraform's business; this resource
    # owns exactly one item and should not react to the others.
    ignore_changes = [item]
  }
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.admins.id
}

output "cognito_hosted_ui_domain" {
  value = "${aws_cognito_user_pool_domain.admins.domain}.auth.us-east-1.amazoncognito.com"
}

output "google_redirect_uri" {
  description = "Paste this into the Google Cloud OAuth client's Authorized redirect URIs."
  value       = "https://${aws_cognito_user_pool_domain.admins.domain}.auth.us-east-1.amazoncognito.com/oauth2/idpresponse"
}
