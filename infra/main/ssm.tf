# The bot's secrets live in SSM Parameter Store, and only there. Terraform
# names them but never holds their values: anything Terraform manages ends
# up in its state file, which the CI role must read to plan, and a
# SecureString parameter is decrypted on every refresh even with value_wo.
# They are set and rotated by the owner with infra/scripts/set-secret.sh.
#
# Until 2026-10-31 these were aws_ssm_parameter resources fed from GitHub
# environment secrets. The removed blocks below let Terraform forget them
# without deleting the parameters.

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

locals {
  ssm_params = {
    telegram_bot_token      = "/bgucats/telegram/bot-token"
    telegram_webhook_secret = "/bgucats/telegram/webhook-secret"
    submitter_hash_salt     = "/bgucats/submitter-hash-salt"
  }
  # In this order, as the ARNs were listed before, so the Lambda's policy
  # does not change.
  ssm_param_arns = [
    for key in ["telegram_bot_token", "telegram_webhook_secret", "submitter_hash_salt"] :
    "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_params[key]}"
  ]
}

removed {
  from = aws_ssm_parameter.telegram_bot_token
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_ssm_parameter.telegram_webhook_secret
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_ssm_parameter.submitter_hash_salt
  lifecycle {
    destroy = false
  }
}
