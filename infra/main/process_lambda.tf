data "archive_file" "process" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/process"
  output_path = "${path.module}/../../build/process.zip"
}

resource "aws_iam_role" "process_lambda" {
  name = "bgucats-process-lambda"

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

resource "aws_iam_role_policy_attachment" "process_lambda_logs" {
  role       = aws_iam_role.process_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "process_lambda_access" {
  name = "bgucats-process-lambda-access"
  role = aws_iam_role.process_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadRawPhotos"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.media.arn}/raw/*"
      },
      {
        Sid      = "WriteDerivatives"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.media.arn}/derived/*"
      },
      {
        Sid    = "DataTableAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
        ]
        Resource = aws_dynamodb_table.data.arn
      },
      {
        # Near-duplicate detection queries GSI1 for the session's other
        # photos. Index ARNs are separate from the table ARN — table-level
        # permission alone does not cover an index query.
        Sid      = "QuerySessionPhotos"
        Effect   = "Allow"
        Action   = "dynamodb:Query"
        Resource = "${aws_dynamodb_table.data.arn}/index/GSI1"
      },
    ]
  })
}

resource "aws_lambda_function" "process" {
  function_name = "bgucats-process"
  role          = aws_iam_role.process_lambda.arn
  handler       = "process.handler.handler"
  runtime       = "python3.12"
  # Pillow resizing is memory-bound, and on Lambda more memory also buys
  # proportionally more CPU — 1024MB is cheaper per photo than 512MB here.
  timeout     = 60
  memory_size = 1024

  filename         = data.archive_file.process.output_path
  source_code_hash = data.archive_file.process.output_base64sha256

  environment {
    variables = {
      TABLE_NAME   = aws_dynamodb_table.data.name
      MEDIA_BUCKET = aws_s3_bucket.media.id
    }
  }
}

resource "aws_lambda_permission" "process_from_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.process.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.media.arn
}

resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.process.arn
    events              = ["s3:ObjectCreated:*"]
    # Only originals trigger processing. Without this prefix the
    # derivatives this Lambda writes would re-trigger it, forever.
    filter_prefix = "raw/"
  }

  depends_on = [aws_lambda_permission.process_from_s3]
}

output "process_lambda_name" {
  value = aws_lambda_function.process.function_name
}
