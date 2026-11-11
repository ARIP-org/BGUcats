# The iPhone app (native/) is the same pages as the PWA, packed inside the
# app, where their address is capacitor://localhost and not the CloudFront
# one. To the web view the API is then another origin, and it will not hand
# the page an answer unless the API says it may (CORS).
locals {
  # What the pages are served from inside the app. Capacitor's default.
  native_app_origin = "capacitor://localhost"
  # Where Cognito answers the app's sign-in: the bundle ID as a scheme.
  native_app_redirect = "org.arip.bgucats://signin"
}

resource "aws_apigatewayv2_api" "main" {
  name          = "bgucats-api"
  protocol_type = "HTTP"

  # Any origin, because API Gateway accepts only http(s) origins or "*" here
  # and the app's is neither. It gives nothing away: no route takes a cookie.
  # Every /api/ call must carry a token in a header the page adds itself,
  # which another site's page does not have, and the authorizer still checks
  # it on every call. What CORS decides is only whether a page may read the
  # answer to a request it was able to make. Credentials stay off, so a
  # browser never attaches anything on its own. With this, API Gateway
  # answers the web view's preflight itself, but only on a route without an
  # authorizer: admin_api.tf has one for OPTIONS.
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "PATCH", "DELETE"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

# The Telegram webhook: production only (variables.tf, telegram_bot).
resource "aws_apigatewayv2_integration" "ingest" {
  count                  = local.telegram_bot_count
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "telegram_webhook" {
  count     = local.telegram_bot_count
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /webhook/telegram"
  target    = "integrations/${aws_apigatewayv2_integration.ingest[0].id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # The landing page's beacon is public and unauthenticated (beacon.tf). A
  # lecture hall opening the page at once is a few requests a second; this
  # caps a script at roughly a dollar a day of Lambda and DynamoDB. Beacons
  # over the limit get a 429 and simply aren't counted — under a flood,
  # undercounting is the right way to fail.
  route_settings {
    route_key              = aws_apigatewayv2_route.beacon.route_key
    throttling_rate_limit  = 10
    throttling_burst_limit = 30
  }
}

resource "aws_lambda_permission" "apigw" {
  count         = local.telegram_bot_count
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# null in staging, which has no bot.
output "webhook_url" {
  value = local.settings.telegram_bot ? "${aws_apigatewayv2_api.main.api_endpoint}/webhook/telegram" : null
}

moved {
  from = aws_apigatewayv2_integration.ingest
  to   = aws_apigatewayv2_integration.ingest[0]
}

moved {
  from = aws_apigatewayv2_route.telegram_webhook
  to   = aws_apigatewayv2_route.telegram_webhook[0]
}

moved {
  from = aws_lambda_permission.apigw
  to   = aws_lambda_permission.apigw[0]
}
