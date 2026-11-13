# The admin UI: a private S3 bucket of static files, fronted by CloudFront.
#
# The API is a second origin on the *same* distribution rather than a separate
# hostname. That makes /api/* same-origin to the browser, which means no CORS
# configuration, no preflights, and no chance of a misconfigured wildcard
# origin. It also keeps the execute-api URL out of the page entirely.

resource "aws_s3_bucket" "web" {
  bucket = "bgucats-admin-web-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket = aws_s3_bucket.web.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "bgucats-admin-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Forwards everything the API needs — crucially the Authorization header —
# while dropping Host, which must stay the origin's own for execute-api to
# route the request.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  # Managed-SimpleCORS: the same ID in every account (AWS's managed policies).
  managed_simple_cors = "60669652-455b-4ae9-85a4-c4c02393f86c"
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = "bgucats admin labeling tool"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "s3-web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Caching is off for both origins. The audience is a handful of admins, so
  # there is nothing to gain, and it removes the entire class of "I deployed
  # a fix and the browser is still running last week's JavaScript" — no
  # invalidation step, no cache-busting filenames.
  default_cache_behavior {
    target_origin_id       = "s3-web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_disabled.id
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true
  }

  # The recognition model (published by scripts/publish_model.py) is read
  # by the iPhone app too, whose pages are capacitor://localhost: another
  # origin, so its fetches need CORS (N1 of docs/app-plan/). AWS's own
  # Managed-SimpleCORS response headers policy answers
  # `Access-Control-Allow-Origin: *` on this path only. Named by its ID, not
  # looked up with a data source, so neither the CI nor the deploy role
  # needs to read response headers policies. The files are public already;
  # caching stays off, as everywhere here.
  ordered_cache_behavior {
    path_pattern               = "/model/*"
    target_origin_id           = "s3-web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    response_headers_policy_id = local.managed_simple_cors
    compress                   = true
  }

  # No custom_error_response mapping 403/404 to index.html: the UI is a single
  # page with no client-side routes to rescue, and such a rule is
  # distribution-wide — it would quietly rewrite the API's own 403s into a
  # 200 and an HTML body.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.web.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.web.arn
          }
        }
      },
    ]
  })
}

locals {
  # Every file under web/ is the site, typed by its extension. A file with
  # an extension not listed here fails the plan rather than going out with
  # the wrong type. Until E0 this was a list of names by hand, and a new
  # file (web/lib/, the member app) would have been missing from the site
  # while every local test passed.
  #
  # Not here: config.json, generated below, and the recognition model,
  # which is built, not committed, and published under model/ by
  # scripts/publish_model.py, a prefix Terraform never touches. The service
  # worker caches the app shell only, never /api/ or photos (web/sw.js).
  web_types = {
    html        = "text/html; charset=utf-8"
    js          = "text/javascript; charset=utf-8"
    css         = "text/css; charset=utf-8"
    json        = "application/json; charset=utf-8"
    webmanifest = "application/manifest+json"
    svg         = "image/svg+xml"
    png         = "image/png"
    woff2       = "font/woff2"
    txt         = "text/plain; charset=utf-8"
  }
  web_files = {
    for name in fileset("${path.module}/../../web", "**") :
    name => local.web_types[reverse(split(".", name))[0]]
  }
  # Staging's site is web/ with web-staging/ laid over it: a file there
  # takes the place of the one in web/ it is named after. Today that is the
  # home-screen icon with "BETA" on it (scripts/beta_icon.py) and the
  # manifest that names the install "BGU Cats beta", so nobody mistakes the
  # test copy on their phone for the real app. Nothing else differs, and a
  # file with no namesake in web/ is not uploaded (a test refuses one).
  web_overlay = var.environment == "staging" ? fileset("${path.module}/../../web-staging", "**") : toset([])
  web_sources = {
    for name, type in local.web_files :
    name => contains(local.web_overlay, name) ? "${path.module}/../../web-staging/${name}" : "${path.module}/../../web/${name}"
  }
}

resource "aws_s3_object" "web" {
  for_each = local.web_files

  bucket       = aws_s3_bucket.web.id
  key          = each.key
  source       = local.web_sources[each.key]
  content_type = each.value
  etag         = filemd5(local.web_sources[each.key])
}

# Generated rather than committed, so the page never contains a hand-copied
# pool id that silently drifts from what is actually deployed.
resource "aws_s3_object" "web_config" {
  bucket       = aws_s3_bucket.web.id
  key          = "config.json"
  content_type = "application/json"

  content = jsonencode({
    userPoolClientId = aws_cognito_user_pool_client.web.id
    cognitoDomain    = "${aws_cognito_user_pool_domain.admins.domain}.auth.us-east-1.amazoncognito.com"
    redirectUri      = "https://${aws_cloudfront_distribution.web.domain_name}/"
    # Tracked links on the stats page are built from these: the landing page
    # with ?src=, and the bot with the same slug as its /start payload.
    siteUrl = "https://${aws_cloudfront_distribution.site.domain_name}/"
    botUrl  = "https://t.me/bgucatsbot"
    # index.html or app.html first (variables.tf, front_door).
    frontDoor = local.settings.front_door
  })
}

output "admin_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}/"
}
