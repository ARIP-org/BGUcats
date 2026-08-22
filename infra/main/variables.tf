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
