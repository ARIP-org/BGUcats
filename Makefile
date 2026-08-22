.PHONY: fmt lint test build-ingest tf-init tf-plan tf-apply

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

build-ingest:
	rm -rf build/ingest
	mkdir -p build/ingest
	pip install -r src/ingest/requirements.txt -t build/ingest --quiet
	cp src/ingest/handler.py build/ingest/

tf-init:
	terraform -chdir=infra/main init

tf-plan: build-ingest
	terraform -chdir=infra/main plan

tf-apply: build-ingest
	terraform -chdir=infra/main apply
