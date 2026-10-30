# The production account, sasha-bgucats-prod. Used by every init of
# infra/main: terraform -chdir=infra/main init -backend-config=backend/prod.hcl
# The bucket is created by infra/bootstrap in the same account.
bucket = "bgucats-tfstate-395591097129"
