.PHONY: fmt lint test tf-init tf-plan tf-apply

fmt:
	ruff format .
	terraform -chdir=infra/main fmt -recursive
	terraform -chdir=infra/bootstrap fmt -recursive

lint:
	ruff check .
	terraform -chdir=infra/main fmt -check -recursive
	terraform -chdir=infra/bootstrap fmt -check -recursive

test:
	pytest

tf-init:
	terraform -chdir=infra/main init

tf-plan:
	terraform -chdir=infra/main plan

tf-apply:
	terraform -chdir=infra/main apply
