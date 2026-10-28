# Single table, three GSIs — see docs/cat-app-design-spec.pdf §6.3 for the
# exact key formats and per-entity attributes (Cat, Session, Photo). Only
# key attributes need declaring here; everything else is written freely by
# the Lambdas.
#
# Two additional item shapes live in this table that aren't in §6.3,
# because the spec describes ingest behavior (session resolution,
# rate-limiting) without specifying a lookup mechanism, and neither
# warrants a 4th GSI:
#   PK = SUBMITTER#{submitterHash}, SK = ACTIVE_SESSION  — one item per
#     submitter tracking their currently-open session.
#   PK = RATE#{submitterHash}#{minuteBucket}, SK = META   — a per-minute
#     counter, self-expiring via the table's TTL attribute.
#
# And three for the admin tool's stats page, all listed through GSI2 the
# way cats and admins are (GSI2PK = ENTITY#<kind>):
#   PK = SUBMITTER#{submitterHash}, SK = PROFILE — when someone first showed
#     up, on which channel, and the tracked link that brought them.
#   PK = TRAFFIC#{day}#{referral}, SK = META — the landing page's daily
#     visit and bot-button counters (beacon.tf). No per-visitor items.
#   PK = LINK#{slug}, SK = META — a tracked link's name, and the partner's
#     own numbers for it, typed in from their dashboard.
#
# And one for the PWA's Capture screen:
#   Session items opened in the app (channel "app") carry
#   GSI2PK = ENTITY#ENCOUNTER, GSI2SK = {email}#{startedAt}, so "my recent
#   encounters" is one begins_with Query. Bot sessions are not in it.
#
# hash_key/range_key are deprecated in favor of key_schema as of provider
# ~6.29, but key_schema has several open upstream bugs around perpetual
# drift and forced GSI replacement as of ~6.61 — staying on the
# deprecated-but-stable syntax deliberately until that settles.
resource "aws_dynamodb_table" "data" {
  name         = "bgucats-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  attribute {
    name = "GSI3PK"
    type = "S"
  }

  attribute {
    name = "GSI3SK"
    type = "S"
  }

  # All photos in a session.
  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # Labeling queue, oldest first.
  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  # All photos of a cat, for export.
  global_secondary_index {
    name            = "GSI3"
    hash_key        = "GSI3PK"
    range_key       = "GSI3SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.data.name
}

output "dynamodb_table_arn" {
  value = aws_dynamodb_table.data.arn
}
