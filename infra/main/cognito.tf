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

# Credentials come from a Google Cloud OAuth 2.0 client — see infra/README.md
# for the console walkthrough. The authorized redirect URI Google needs is
# https://{domain_prefix}.auth.{region}.amazoncognito.com/oauth2/idpresponse,
# which is knowable before this is ever applied because we pick the prefix.
resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.admins.id
  provider_name = "Google"
  provider_type = "Google"

  # The four endpoint values below are filled in by Cognito itself when the
  # provider type is Google. Left out of the config they come back as
  # unmanaged drift, so every future `plan` proposes deleting them and
  # nobody reads plans that always say something. Stating them explicitly
  # makes the resource converge.
  provider_details = {
    client_id                     = var.google_client_id
    client_secret                 = var.google_client_secret
    authorize_scopes              = "openid email profile"
    attributes_url                = "https://people.googleapis.com/v1/people/me?personFields="
    attributes_url_add_attributes = "true"
    authorize_url                 = "https://accounts.google.com/o/oauth2/v2/auth"
    oidc_issuer                   = "https://accounts.google.com"
    token_request_method          = "POST"
    token_url                     = "https://www.googleapis.com/oauth2/v4/token"
  }

  attribute_mapping = {
    email    = "email"
    username = "sub"
    name     = "name"
    picture  = "picture"
  }
}

resource "aws_cognito_user_pool_domain" "admins" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.admins.id
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
  supported_identity_providers         = [aws_cognito_identity_provider.google.provider_name]

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
