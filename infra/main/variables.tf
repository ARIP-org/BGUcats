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
      # The member app (docs/app-plan/): off until it opens (L3).
      social        = false
      signup_policy = "allowlist"
      # The languages the profile offers. English until a native speaker
      # has read a draft (docs/app-plan/OWNER_STEPS.md, O14).
      languages = ["en"]
      # Which page the site opens on: "desk" (the labeling desk and
      # Capture, index.html) or "app" (the member app, app.html). The
      # desk until L3 (docs/app-plan/05-client.md).
      front_door = "desk"
    }
    staging = {
      cognito_domain_prefix = "bgucats-staging"
      telegram_bot          = false
      # Every feature on as soon as it exists; sign-up stays the allowlist,
      # because staging never holds real contributors' photos.
      social        = true
      signup_policy = "allowlist"
      # Every draft, so it can be read on a phone before it is offered.
      languages = ["en", "he", "ru", "ar"]
      # The member app since 2026-11-13 (the owner: the installed staging
      # app opened on the desk, and the new screens only in a browser
      # tab). The desk is one tap away (the profile, or `?desk`).
      front_door = "app"
    }
  }[var.environment]

  # Who may sign in when signup_policy is "domain": BGU's Google accounts
  # (docs/app-plan/DECISIONS.md, D1). Read by the sign-up trigger and both
  # APIs (src/common/admission.py).
  signup_domains = ["post.bgu.ac.il", "bgu.ac.il"]

  # The terms a person accepts before writing anything. A new value asks
  # everyone again. "draft" until the owner's terms page exists (O10).
  terms_version = "draft"

  # What the member app may offer, sent to the phone in GET /api/v1/me.
  # Each feature adds its flag here when it is built (02-architecture.md,
  # "Flags").
  app_flags = {
    social = local.settings.social
    # A cat's grade, worked out from its popularity (D9, B7b). One switch
    # hides it everywhere if the owner decides it is not wanted.
    gpa = true
    # Points, levels and badges (B7, E8): the card on Home and its sheet.
    achievements = true
    # "I fed this cat" (D10, B7c): the log, "last fed", its points and badge.
    feeding = true
    # Which languages the profile's menu offers (E10).
    languages = local.settings.languages
  }

  # count for the bot's resources: 1 in production, 0 in staging.
  telegram_bot_count = local.settings.telegram_bot ? 1 : 0
}
