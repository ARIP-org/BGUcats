variable "cognito_domain_prefix" {
  description = <<-EOT
    Prefix of the Cognito hosted-UI domain. Must be globally unique across
    AWS. Chosen rather than generated so the Google redirect URI is known
    before the first apply.
  EOT
  type        = string
  default     = "bgucats-app"
}

variable "bootstrap_admin_email" {
  description = "Google account seeded into the admin allowlist so the tool can be opened at all."
  type        = string
}
