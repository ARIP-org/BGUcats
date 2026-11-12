# The second table: everything people do in the app (docs/app-plan/,
# milestone F3, decided 2026-11-12, A2). Kept apart from bgucats-data, the
# dataset, so the member API's role can be given this table and not that
# one. Same shape as the first table; its keys are in docs/data-model.md,
# "bgucats-social". Empty until the milestones that write it (B1 onward).
#
# The stream carries every change, old and new, to the events Lambda
# (events.tf). Lambda's reads of a stream are not billed; the stream itself
# costs nothing beyond the writes.
resource "aws_dynamodb_table" "social" {
  name         = "bgucats-social"
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

  # A person's posts.
  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # The feed by month, and the admins' queues.
  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  # A cat's posts.
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

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  # People's posts, friendships and votes: the same three locks as the
  # dataset (dynamodb.tf). The deploy role can never delete a table either.
  deletion_protection_enabled = true

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

output "social_table_name" {
  value = aws_dynamodb_table.social.name
}
