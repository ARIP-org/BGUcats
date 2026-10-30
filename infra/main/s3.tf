data "aws_caller_identity" "current" {}

# Key layout — spec §6.2:
#   raw/{sessionId}/{photoId}.{ext}        original, write-once, never mutated
#   derived/{photoId}/thumb-256.webp
#   derived/{photoId}/medium-1024.webp
#   exports/{datasetVersion}/manifest.json
#   exports/{datasetVersion}/images/...
resource "aws_s3_bucket" "media" {
  bucket = "bgucats-media-${data.aws_caller_identity.current.account_id}"

  # People's photos. A plan that would destroy or replace the bucket fails
  # instead (and the deploy role is denied DeleteBucket as well).
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "derived-to-ia"
    status = "Enabled"

    filter {
      prefix = "derived/"
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }
}

# The PWA's camera uploads go from the phone straight to raw/ (presigned
# POST, see src/admin/handler.py), so the browser needs the bucket to answer
# its CORS preflight. GET is for the in-browser recognition model
# (web/recognition.js), which has to read a photo's pixels: without CORS the
# canvas is "tainted" and refuses to hand them over. One origin — the admin
# app's own CloudFront address. CORS only lets that page read a response it
# was already allowed to fetch: every read and write still needs a URL the
# API signed, and nothing is listable.
resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  cors_rule {
    allowed_origins = ["https://${aws_cloudfront_distribution.web.domain_name}"]
    allowed_methods = ["GET", "POST"]
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}

output "media_bucket" {
  value = aws_s3_bucket.media.id
}

output "media_bucket_arn" {
  value = aws_s3_bucket.media.arn
}
