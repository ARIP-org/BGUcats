# Being told when the app breaks. Until this file nothing was: a failing
# Lambda only showed in its log, to whoever went looking. In October, 48
# photos stalled for an hour before anyone noticed.
#
# One SNS topic, one email subscription, and alarms on the two things that
# mean "a person's request, or a photo, was just lost":
#   - any error in any of the app's Lambdas;
#   - any 5xx answer from the API.
# Deliberately not alarmed: 4xx (an expired sign-in is a 401), throttles
# (API Gateway's own limits protect the bill; they are not an outage), and
# slow answers. Add those when the app is public and has traffic to judge.
#
# Cost: each account's first ten alarms and first thousand emails a month
# are free; this is six alarms in production and five in staging.

# Not encrypted with a KMS key: CloudWatch cannot publish to a topic under
# the AWS-managed SNS key, and a key of our own costs $1 a month to protect
# messages that say "bgucats-process had an error".
resource "aws_sns_topic" "alerts" {
  name = "bgucats-alerts"
}

# The address is the bootstrap admin's, which each environment's deploy
# already has (the BOOTSTRAP_ADMIN_EMAIL secret). AWS sends a confirmation
# email on the first apply, and nothing is delivered until its link is
# clicked. CI plans with a placeholder address, so a change of address is
# ignored here, the same way the bootstrap admin row ignores it; to move the
# alerts, subscribe the new address in the console.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = lower(var.bootstrap_admin_email)

  lifecycle {
    ignore_changes = [endpoint]
  }
}

locals {
  # Every Lambda the environment has. The bot's exists in production only.
  alarmed_functions = merge(
    {
      admin           = aws_lambda_function.admin.function_name
      admin-presignup = aws_lambda_function.admin_presignup.function_name
      beacon          = aws_lambda_function.beacon.function_name
      process         = aws_lambda_function.process.function_name
    },
    { for f in aws_lambda_function.ingest : "ingest" => f.function_name },
  )
}

# An unhandled exception, a timeout or an out-of-memory kill. For the
# process Lambda that is a photo with no thumbnail; for the others, a
# request that got a 500. One error in five minutes is enough: at this
# traffic there is no "normal" error rate to stay under.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.alarmed_functions

  alarm_name        = "bgucats-${each.key}-errors"
  alarm_description = "${each.value} (${var.environment}) failed at least once in five minutes. Logs: CloudWatch, log group /aws/lambda/${each.value}."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = each.value }
  statistic   = "Sum"
  period      = 300

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  # No invocations means no data points, which is the usual state here and
  # not a problem.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# What a person in the app actually sees: the API answered 5xx. It also
# catches what no Lambda metric can: an integration that timed out or a
# Lambda API Gateway could not invoke at all.
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name        = "bgucats-api-5xx"
  alarm_description = "The ${var.environment} API answered 5xx at least once in five minutes."

  namespace   = "AWS/ApiGateway"
  metric_name = "5xx"
  dimensions  = { ApiId = aws_apigatewayv2_api.main.id }
  statistic   = "Sum"
  period      = 300

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
