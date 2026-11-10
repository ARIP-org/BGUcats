.PHONY: fmt lint test build build-ingest build-process build-admin build-beacon \
	tf-init tf-plan site-invalidate admin-add poster \
	model-export model-publish

# Lambda runs Linux x86_64; resolve binary wheels for that, not for whatever
# the build host happens to be.
LAMBDA_PIP = pip install --quiet --no-compile \
	--platform manylinux_2_28_x86_64 --only-binary=:all: --python-version 3.12

# The same source must give the same zip, or every push to main redeploys
# all six Lambdas and nobody can tell a real code change from noise in the
# plan. archive_file already fixes every entry's date; what varied was the
# .pyc files pip writes, which carry the build time and pip's random temp
# directory. So pip compiles nothing, and this compiles each package once:
# hash-based (no timestamp), with the path the code has on Lambda.
lambda-compile = python -m compileall -q -j 0 --invalidation-mode checked-hash \
	-s build/$(1) -p /var/task build/$(1)

fmt:
	ruff format .
	terraform -chdir=infra/main fmt -recursive
	terraform -chdir=infra/bootstrap fmt -recursive
	terraform -chdir=infra/org fmt -recursive

lint:
	ruff check .
	terraform -chdir=infra/main fmt -check -recursive
	terraform -chdir=infra/bootstrap fmt -check -recursive
	terraform -chdir=infra/org fmt -check -recursive

test:
	pytest

build: build-ingest build-process build-admin build-beacon

# Always rebuilt rather than tracked as file targets: a directory's mtime
# doesn't change when a source file inside it is edited, so a file-target
# version would silently ship stale code.
# handler.py (Telegram) is a thin adapter over core.py, shipped as a package
# so `from ingest import core` resolves the same in the Lambda as under pytest.
build-ingest:
	rm -rf build/ingest && mkdir -p build/ingest/ingest
	$(LAMBDA_PIP) --target build/ingest -r src/ingest/requirements.txt
	cp src/ingest/__init__.py src/ingest/core.py src/ingest/handler.py \
		build/ingest/ingest/
	$(call lambda-compile,ingest)

# Shipped as a package (handler = process.handler.handler) rather than
# flattened, so `from process.phash import ...` resolves identically in
# the Lambda and under pytest.
build-process:
	rm -rf build/process && mkdir -p build/process/process
	$(LAMBDA_PIP) --target build/process -r src/process/requirements.txt
	cp src/process/__init__.py src/process/handler.py src/process/phash.py \
		build/process/process/
	$(call lambda-compile,process)

# Same package shape as build-process, and for the same reason: the API and
# the Cognito trigger are two handlers inside one `admin` package.
build-admin:
	rm -rf build/admin && mkdir -p build/admin/admin
	$(LAMBDA_PIP) --target build/admin -r src/admin/requirements.txt
	cp src/admin/__init__.py src/admin/handler.py src/admin/insights.py \
		src/admin/presignup.py build/admin/admin/
	$(call lambda-compile,admin)

# The landing page's visit counter. Its own package and its own role: the one
# public endpoint that writes gets the smallest possible zip and grant.
build-beacon:
	rm -rf build/beacon && mkdir -p build/beacon/beacon
	$(LAMBDA_PIP) --target build/beacon -r src/beacon/requirements.txt
	cp src/beacon/__init__.py src/beacon/handler.py build/beacon/beacon/
	$(call lambda-compile,beacon)

# Every target that calls AWS from a person's shell takes the profile by
# name, PROFILE=bgucats-prod-ro or PROFILE=bgucats-staging-ro (or -admin),
# and first runs infra/scripts/aws-guard.sh: no access keys in the
# environment, and the credentials must be the environment's account
# (infra/main/backend/<prod|staging>.hcl).
# In GitHub Actions the OIDC role is the environment, and PROFILE is unset.
#
# BGUCATS_ENV is production or staging, the name aws-guard.sh reads too. It
# follows the profile (bgucats-staging-* is staging) unless given.
BGUCATS_ENV ?= $(if $(filter bgucats-staging-%,$(PROFILE)),staging,production)
AWS_ENV = BGUCATS_ENV=$(BGUCATS_ENV) $(if $(PROFILE),AWS_PROFILE=$(PROFILE))
aws-guard = $(AWS_ENV) infra/scripts/aws-guard.sh

# Which account's state: backend/<BACKEND>.hcl, prod or staging.
# -reconfigure, because a .terraform left over from another backend would
# otherwise offer to copy that state into this one.
BACKEND = $(if $(filter staging,$(BGUCATS_ENV)),staging,prod)

tf-init:
	$(aws-guard)
	$(AWS_ENV) terraform -chdir=infra/main init -reconfigure -backend-config=backend/$(BACKEND).hcl

# Read-only, for debugging with an SSO session (docs/codespaces.md): no lock,
# since the read-only role cannot write one, and no apply target at all.
# Deploys run in GitHub Actions only (.github/workflows/deploy.yml). Needs the
# TF_VAR_bootstrap_admin_email in the environment; without it, plan asks.
# Run tf-init with the same profile first.
tf-plan: build
	$(aws-guard)
	$(AWS_ENV) TF_VAR_environment=$(BGUCATS_ENV) terraform -chdir=infra/main plan -lock=false

# The landing page sits behind CachingOptimized (default TTL one day), so an
# apply alone leaves visitors on the old page until the edge copy expires.
# deploy.yml runs this after an apply that changed the page.
site-invalidate:
	$(aws-guard)
	$(AWS_ENV) aws cloudfront create-invalidation \
		--distribution-id $$($(AWS_ENV) terraform -chdir=infra/main output -raw site_distribution_id) \
		--paths '/*'

# Convenience wrapper for the same allowlist row the Admins tab writes —
# useful for adding the first colleague before anyone has logged in.
admin-add:
	@test -n "$(EMAIL)" || (echo "usage: make admin-add EMAIL=someone@example.com" && exit 1)
	$(AWS_ENV) infra/scripts/add-admin.sh "$(EMAIL)"

# Printable A4 recruitment poster. Defaults to the deployed landing page;
# override with `make poster URL=https://...` to point it elsewhere.
poster:
	python scripts/build_poster.py $(if $(URL),--url $(URL),)

# The recognition model the labeling desk runs in the browser
# (web/recognition.js). Exporting needs the research environment —
# research/requirements.txt, never the Lambda one. --no-eval skips the
# polar-bear accuracy check, which needs that dataset on disk.
MODEL_ONNX = research/runs/browser/megadescriptor-t-224-int8.onnx

model-export:
	PYTHONPATH=research python -m catreid.export --out research/runs/browser --no-eval

# Uploads to the admin web bucket under model/{version}/, outside Terraform
# (the file is built, not committed), manifest last. No CloudFront
# invalidation needed: the admin distribution caches nothing.
model-publish:
	$(aws-guard)
	$(AWS_ENV) python scripts/publish_model.py --model $(MODEL_ONNX) \
		--bucket bgucats-admin-web-$$($(AWS_ENV) aws sts get-caller-identity --query Account --output text)
