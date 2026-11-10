# What existed before this root, brought under it without being recreated.
# Applied once on 2026-11-10; an import block for something already in the
# state does nothing, so these stay as the record of where each came from.

import {
  to = aws_organizations_policy.member_guardrails
  id = "p-2wtfhxmo"
}

import {
  to = aws_organizations_policy_attachment.member_guardrails
  id = "r-6978:p-2wtfhxmo"
}

import {
  to = aws_organizations_policy.deny_leave_and_close
  id = "p-oo66pcpq"
}

import {
  to = aws_organizations_policy_attachment.deny_leave_and_close
  id = "r-6978:p-oo66pcpq"
}

import {
  to = aws_ce_anomaly_monitor.services
  id = "arn:aws:ce::851725214678:anomalymonitor/db441e25-9b9c-4373-a323-39370a01d7cb"
}
