# The staging account, bgucats-staging (created 2026-11-07,
# docs/MANUAL_STEPS.md step 12). Used by every init of infra/main for
# staging: terraform -chdir=infra/main init -backend-config=backend/staging.hcl
# The bucket is created by infra/bootstrap in the same account.
bucket = "bgucats-tfstate-586943192664"
