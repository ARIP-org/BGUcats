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

resource "aws_ssm_parameter" "submitter_hash_salt" {
  name  = "/bgucats/submitter-hash-salt"
  type  = "SecureString"
  value = var.submitter_hash_salt
}
