# The landing page's visit counter: POST /landing on the shared HTTP API.
#
# The only route on the API that writes without authenticating anyone, so
# everything about it is sized for abuse rather than for convenience:
# its own role that can increment TRAFFIC# counters and nothing else, an
# API Gateway throttle on the route (api.tf), and a handler that stores
# daily totals only — see src/beacon/handler.py.
#
# Called cross-origin by the landing page with a text/plain body, which is
# a CORS "simple request": no preflight, and since the page never reads the
# response, no CORS configuration on the API at all.

data "archive_file" "beacon" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/beacon"
  output_path = "${path.module}/../../build/beacon.zip"
}

resource "aws_iam_role" "beacon_lambda" {
  name = "bgucats-beacon-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "lambda.amazonaws.com" }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "beacon_lambda_logs" {
  role       = aws_iam_role.beacon_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "beacon_lambda_access" {
  name = "bgucats-beacon-lambda-access"
  role = aws_iam_role.beacon_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IncrementTrafficCountersOnly"
        Effect   = "Allow"
        Action   = "dynamodb:UpdateItem"
        Resource = aws_dynamodb_table.data.arn
        # Enforced by IAM, not just by the handler: even a bug in it can't
        # reach a photo, a session or the admin allowlist.
        Condition = {
          "ForAllValues:StringLike" = {
            "dynamodb:LeadingKeys" = ["TRAFFIC#*"]
          }
        }
      },
    ]
  })
}

resource "aws_lambda_function" "beacon" {
  function_name = "bgucats-beacon"
  role          = aws_iam_role.beacon_lambda.arn
  handler       = "beacon.handler.handler"
  runtime       = "python3.12"
  timeout       = 5
  memory_size   = 128

  filename         = data.archive_file.beacon.output_path
  source_code_hash = data.archive_file.beacon.output_base64sha256

  environment {
    variables = {
      TABLE_NAME  = aws_dynamodb_table.data.name
      SITE_ORIGIN = "https://${aws_cloudfront_distribution.site.domain_name}"
    }
  }
}

resource "aws_apigatewayv2_integration" "beacon" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.beacon.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "beacon" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /landing"
  target    = "integrations/${aws_apigatewayv2_integration.beacon.id}"
}

resource "aws_lambda_permission" "apigw_beacon" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.beacon.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*/landing"
}
