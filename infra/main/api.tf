resource "aws_apigatewayv2_api" "main" {
  name          = "bgucats-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "telegram_webhook" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /webhook/telegram"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"
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
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

output "webhook_url" {
  value = "${aws_apigatewayv2_api.main.api_endpoint}/webhook/telegram"
}
