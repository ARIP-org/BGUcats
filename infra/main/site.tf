# The public landing page — what the QR code on the poster points at.
#
# Its own bucket and distribution rather than a path on the admin tool's:
# this one is meant to be handed to strangers, and it should not be possible
# for a CloudFront behaviour edit to expose the labeling API alongside it.
# The two share no origin, no policy and no failure mode.

resource "aws_s3_bucket" "site" {
  bucket = "bgucats-site-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "bgucats-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Unlike the admin tool, this one is cached: it is static, public, and the
# whole point is that a lecture hall full of people can open it at once.
data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "bgucats public landing page"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "s3-site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
          }
        }
      },
    ]
  })
}

locals {
  site_files = {
    "index.html" = "text/html; charset=utf-8"
    "styles.css" = "text/css; charset=utf-8"
    "hero.webp"  = "image/webp"
  }
}

resource "aws_s3_object" "site" {
  for_each = local.site_files

  bucket       = aws_s3_bucket.site.id
  key          = each.key
  source       = "${path.module}/../../site/${each.key}"
  content_type = each.value
  etag         = filemd5("${path.module}/../../site/${each.key}")
}

output "site_url" {
  description = "Public landing page — the URL the poster's QR code encodes."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}/"
}
