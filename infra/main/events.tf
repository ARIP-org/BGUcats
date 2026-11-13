# What happens after a write to bgucats-social: moderation, counters,
# badges, push (docs/app-plan/02-architecture.md). Milestone F3 builds the
# path, a Lambda fed from the table's stream; it only sorts and counts
# changes until the milestones that bring each kind give it work.
#
# A record that keeps failing is retried three times, the batch split to
# find it, and then sent to the alerts topic, which emails the admins
# (docs/deploy.md, "When an alert email arrives"). The item it was about
# stays as it was, so nothing is lost by moving on.

data "archive_file" "events" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/events"
  output_path = "${path.module}/../../build/events.zip"
}

# Named bgucats-*-lambda: the $20 budget freeze exempts exactly those roles,
# so the app keeps running while changes are frozen (infra/org/scp.tf).
resource "aws_iam_role" "events_lambda" {
  name                 = "bgucats-events-lambda"
  permissions_boundary = local.lambda_permissions_boundary

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

resource "aws_iam_role_policy_attachment" "events_lambda_logs" {
  role       = aws_iam_role.events_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# What it does: read the stream, write bgucats-social (never the dataset),
# report a failed record.
resource "aws_iam_role_policy" "events_lambda_access" {
  name = "bgucats-events-lambda-access"
  role = aws_iam_role.events_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The mapping reads the stream as this role.
        Sid    = "ReadSocialStream"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeStream",
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
        ]
        Resource = aws_dynamodb_table.social.stream_arn
      },
      {
        Sid      = "ListStreams"
        Effect   = "Allow"
        Action   = "dynamodb:ListStreams"
        Resource = "*"
      },
      {
        # Publishing a post (B3a): the post itself, and its cat's public
        # counters, in one transaction. Later milestones add their items
        # under the same statement: it is this table, and only this table.
        Sid    = "SocialItems"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:ConditionCheckItem",
        ]
        Resource = [
          aws_dynamodb_table.social.arn,
          "${aws_dynamodb_table.social.arn}/index/*",
        ]
      },
      {
        # Where a record goes after its last retry.
        Sid      = "ReportFailedRecords"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
    ]
  })
}

resource "aws_lambda_function" "events" {
  function_name = "bgucats-events"
  role          = aws_iam_role.events_lambda.arn
  handler       = "events.handler.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 256

  filename         = data.archive_file.events.output_path
  source_code_hash = data.archive_file.events.output_base64sha256

  environment {
    variables = {
      SOCIAL_TABLE_NAME = aws_dynamodb_table.social.name
      # Where a report of a post or a person is emailed (B8): the alerts
      # topic, which this role may already publish to.
      ALERTS_TOPIC_ARN = aws_sns_topic.alerts.arn
      ENVIRONMENT      = var.environment
    }
  }
}

resource "aws_lambda_event_source_mapping" "social_stream" {
  event_source_arn  = aws_dynamodb_table.social.stream_arn
  function_name     = aws_lambda_function.events.arn
  starting_position = "LATEST"
  batch_size        = 25

  # One failing record is reported alone (the handler returns its sequence
  # number), retried three times, the batch halved to find it, then sent to
  # the alerts topic. A record older than six hours is sent there too.
  function_response_types            = ["ReportBatchItemFailures"]
  maximum_retry_attempts             = 3
  bisect_batch_on_function_error     = true
  maximum_record_age_in_seconds      = 21600
  maximum_batching_window_in_seconds = 0

  destination_config {
    on_failure {
      destination_arn = aws_sns_topic.alerts.arn
    }
  }

  # Only changes with consequences, and never the items the Lambda writes
  # itself (src/events/filters.json; tests/events/test_filters.py).
  filter_criteria {
    dynamic "filter" {
      for_each = jsondecode(file("${path.module}/../../src/events/filters.json")).patterns
      content {
        pattern = jsonencode(filter.value)
      }
    }
  }

  # AWS checks, when the mapping is made, that the function's role can read
  # the stream.
  depends_on = [aws_iam_role_policy.events_lambda_access]
}

output "events_lambda_name" {
  value = aws_lambda_function.events.function_name
}
