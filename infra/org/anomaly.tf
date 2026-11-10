# Cost Anomaly Detection: free, and the fastest signal there is, because it
# compares each service's spending with its own past, not with a
# month-long budget.
#
# The monitor is the one AWS made with the account in 2024, imported. An
# account may have only one monitor of this kind, and in the management
# account it sees every member account's spending. Its original
# subscription (made by AWS, not managed here) emails only for an anomaly
# of $100 and 40%, which this project could not reach without something
# having gone very wrong. The subscription below emails from $5.
resource "aws_ce_anomaly_monitor" "services" {
  name              = "Default-Services-Monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "from_five_dollars" {
  name             = "bgucats-anomaly-from-5-usd"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "EMAIL"
    address = local.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = ["5"]
    }
  }
}
