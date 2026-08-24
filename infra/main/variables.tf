variable "telegram_bot_token" {
  description = "Telegram Bot API token from @BotFather."
  type        = string
  sensitive   = true
}

variable "telegram_webhook_secret" {
  description = "Value Telegram echoes back in X-Telegram-Bot-Api-Secret-Token on every webhook call."
  type        = string
  sensitive   = true
}

variable "submitter_hash_salt" {
  description = "Salt mixed into the SHA-256 hash of Telegram user IDs before storage."
  type        = string
  sensitive   = true
}

variable "google_client_id" {
  description = "OAuth 2.0 client ID from the Google Cloud console, used by Cognito's Google IdP."
  type        = string
  sensitive   = true
}

variable "google_client_secret" {
  description = "OAuth 2.0 client secret paired with google_client_id."
  type        = string
  sensitive   = true
}

variable "cognito_domain_prefix" {
  description = <<-EOT
    Prefix of the Cognito hosted-UI domain. Must be globally unique across
    AWS. Chosen rather than generated so the Google redirect URI is known
    before the first apply.
  EOT
  type        = string
  default     = "bgucats-admin"
}

variable "bootstrap_admin_email" {
  description = "Google account seeded into the admin allowlist so the tool can be opened at all."
  type        = string
}
