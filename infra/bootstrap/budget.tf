# A monthly cost alert for this account. It is here and not in main/ because it
# belongs to the account rather than to the app, and because neither GitHub role
# then needs any access to Budgets. It only sends email: nothing stops at the
# limit.
#
# The address is not a secret, but this repo does not need to hold it. Every
# bootstrap plan needs it as TF_VAR_budget_alert_email (infra/README.md).
variable "budget_alert_email" {
  description = "Where the monthly budget alerts go."
  type        = string
}

resource "aws_budgets_budget" "monthly" {
  name         = "bgucats-monthly"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
