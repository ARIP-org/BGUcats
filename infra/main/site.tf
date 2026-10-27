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

# Everything under site/ is published, so adding a cat photo is "drop the
# file in site/cats/ and apply". Content type comes from the extension; an
# extension missing from this map fails the plan rather than uploading
# something with the wrong type.
#
# Caching is explicit because the default bit us: with no Cache-Control,
# browsers guess freshness from Last-Modified, and a desktop Chrome kept a
# weeks-old styles.css under the new HTML. Now HTML always revalidates
# (cheap: a 304 on the ETag), and pages ask for styles.css?v=<content hash>,
# so a changed stylesheet is a new URL no browser has cached.
locals {
  site_dir = "${path.module}/../../site"

  site_types = {
    html = { content_type = "text/html; charset=utf-8", cache_control = "no-cache" }
    css  = { content_type = "text/css; charset=utf-8", cache_control = "public, max-age=31536000, immutable" }
    svg  = { content_type = "image/svg+xml", cache_control = "public, max-age=86400" }
    webp = { content_type = "image/webp", cache_control = "public, max-age=86400" }
    jpg  = { content_type = "image/jpeg", cache_control = "public, max-age=86400" }
    png  = { content_type = "image/png", cache_control = "public, max-age=86400" }
  }

  site_files = {
    for f in fileset(local.site_dir, "**") :
    f => merge(local.site_types[lower(regex("[^.]+$", f))], { ext = lower(regex("[^.]+$", f)) })
  }

  site_css_version = substr(filemd5("${local.site_dir}/styles.css"), 0, 10)

  # HTML is uploaded as rewritten content rather than straight from disk.
  site_html = {
    for f, meta in local.site_files :
    f => replace(file("${local.site_dir}/${f}"), "href=\"/styles.css\"", "href=\"/styles.css?v=${local.site_css_version}\"")
    if meta.ext == "html"
  }
}

resource "aws_s3_object" "site" {
  for_each = local.site_files

  bucket        = aws_s3_bucket.site.id
  key           = each.key
  content_type  = each.value.content_type
  cache_control = each.value.cache_control

  source  = each.value.ext == "html" ? null : "${local.site_dir}/${each.key}"
  content = each.value.ext == "html" ? local.site_html[each.key] : null
  etag    = each.value.ext == "html" ? md5(local.site_html[each.key]) : filemd5("${local.site_dir}/${each.key}")
}

output "site_distribution_id" {
  description = "For `make site-invalidate` — the page is cached for up to a day."
  value       = aws_cloudfront_distribution.site.id
}

output "site_url" {
  description = "Public landing page — the URL the poster's QR code encodes."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}/"
}
