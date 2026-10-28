# The admin labelling tool (spec §4.4, §10): one Lambda serving both the page
# and its JSON API under /admin on the existing HTTP API. No VPC, like every
# other function here (§8.1).
data "archive_file" "admin" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/admin"
  output_path = "${path.module}/../../build/admin.zip"
}

resource "aws_iam_role" "admin_lambda" {
  name = "bgucats-admin-lambda"

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

resource "aws_iam_role_policy_attachment" "admin_lambda_logs" {
  role       = aws_iam_role.admin_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "admin_lambda_access" {
  name = "bgucats-admin-lambda-access"
  role = aws_iam_role.admin_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Reads and conditional updates only. Nothing in the labelling tool
        # deletes an item: a rejected photo, a merged cat and a reassigned
        # session all keep their records.
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
        # Photos in a session (GSI1), the queue and the catalogue (GSI2),
        # photos of a cat (GSI3). Index ARNs need their own grant.
        Sid    = "QueryIndexes"
        Effect = "Allow"
        Action = "dynamodb:Query"
        Resource = [
          "${aws_dynamodb_table.data.arn}/index/GSI1",
          "${aws_dynamodb_table.data.arn}/index/GSI2",
          "${aws_dynamodb_table.data.arn}/index/GSI3",
        ]
      },
      {
        # A presigned URL carries the signer's permissions, so this grant is
        # what lets the browser load a thumbnail. derived/ only: the page
        # never needs a raw original, and so cannot leak one.
        Sid      = "PresignDerivatives"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.media.arn}/derived/*"
      },
      {
        Sid      = "ReadAdminToken"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.admin_token.arn
      },
      {
        Sid      = "DecryptAdminToken"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

resource "aws_lambda_function" "admin" {
  function_name = "bgucats-admin"
  role          = aws_iam_role.admin_lambda.arn
  handler       = "admin.handler.handler"
  runtime       = "python3.12"
  # Just under the HTTP API's 30s integration limit. A merge of a well-covered
  # cat updates each of its photos in turn, which is the slowest request here.
  timeout     = 29
  memory_size = 256

  filename         = data.archive_file.admin.output_path
  source_code_hash = data.archive_file.admin.output_base64sha256

  environment {
    variables = {
      TABLE_NAME        = aws_dynamodb_table.data.name
      MEDIA_BUCKET      = aws_s3_bucket.media.id
      ADMIN_TOKEN_PARAM = aws_ssm_parameter.admin_token.name
    }
  }
}

output "admin_lambda_name" {
  value = aws_lambda_function.admin.function_name
}
