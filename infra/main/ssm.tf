data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_ssm_parameter" "telegram_bot_token" {
  name  = "/bgucats/telegram/bot-token"
  type  = "SecureString"
  value = var.telegram_bot_token
}

resource "aws_ssm_parameter" "telegram_webhook_secret" {
  name  = "/bgucats/telegram/webhook-secret"
  type  = "SecureString"
  value = var.telegram_webhook_secret
}

# WhatsApp's secrets come from the Meta developer dashboard, after this
# infrastructure exists (the webhook URL has to be known first). Terraform
# owns the parameters but not their values: it creates them as "unset",
# which the Lambda treats as "refuse everything", and
# infra/scripts/set-whatsapp-secrets.sh writes the real ones.
resource "aws_ssm_parameter" "whatsapp" {
  for_each = toset(["access-token", "app-secret", "verify-token"])

  name  = "/bgucats/whatsapp/${each.key}"
  type  = "SecureString"
  value = "unset"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "submitter_hash_salt" {
  name  = "/bgucats/submitter-hash-salt"
  type  = "SecureString"
  value = var.submitter_hash_salt
}
