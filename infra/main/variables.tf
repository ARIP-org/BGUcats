variable "environment" {
  description = <<-EOT
    Which copy of the app this is: "production" (sasha-bgucats-prod) or
    "staging" (bgucats-staging). Each lives in its own account, named in
    backend/<prod|staging>.hcl. No default, so a plan can never quietly
    describe the wrong one.
  EOT
  type        = string

  validation {
    condition     = contains(["production", "staging"], var.environment)
    error_message = "environment must be \"production\" or \"staging\"."
  }
}

variable "bootstrap_admin_email" {
  description = "Google account seeded into the admin allowlist so the tool can be opened at all."
  type        = string
}

# Everything that differs between the two copies, in one place. The rest
# of this root is the same in both accounts: bucket names carry the account
# ID, and every other name is per account.
locals {
  settings = {
    production = {
      # Prefix of the Cognito hosted-UI domain. Must be globally unique
      # across AWS. Chosen rather than generated so the Google redirect URI
      # is known before the first apply.
      cognito_domain_prefix = "bgucats-app"
      # The Telegram bot is a stopgap kept working for the landing page's
      # users; staging has none (docs/ROADMAP.md, 2b).
      telegram_bot = true
    }
    staging = {
      cognito_domain_prefix = "bgucats-staging"
      telegram_bot          = false
    }
  }[var.environment]

  # count for the bot's resources: 1 in production, 0 in staging.
  telegram_bot_count = local.settings.telegram_bot ? 1 : 0
}
