.PHONY: fmt lint test build build-ingest build-process build-admin \
	tf-init tf-plan tf-apply admin-add poster

# Lambda runs Linux x86_64; resolve binary wheels for that, not for whatever
# the build host happens to be.
LAMBDA_PIP = pip install --quiet \
	--platform manylinux_2_28_x86_64 --only-binary=:all: --python-version 3.12

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

build: build-ingest build-process build-admin

# Always rebuilt rather than tracked as file targets: a directory's mtime
# doesn't change when a source file inside it is edited, so a file-target
# version would silently ship stale code.
build-ingest:
	rm -rf build/ingest && mkdir -p build/ingest
	$(LAMBDA_PIP) --target build/ingest -r src/ingest/requirements.txt
	cp src/ingest/handler.py build/ingest/

# Shipped as a package (handler = process.handler.handler) rather than
# flattened, so `from process.phash import ...` resolves identically in
# the Lambda and under pytest.
build-process:
	rm -rf build/process && mkdir -p build/process/process
	$(LAMBDA_PIP) --target build/process -r src/process/requirements.txt
	cp src/process/__init__.py src/process/handler.py src/process/phash.py \
		build/process/process/

# Same package shape as build-process, and for the same reason: the API and
# the Cognito trigger are two handlers inside one `admin` package.
build-admin:
	rm -rf build/admin && mkdir -p build/admin/admin
	$(LAMBDA_PIP) --target build/admin -r src/admin/requirements.txt
	cp src/admin/__init__.py src/admin/handler.py src/admin/presignup.py \
		build/admin/admin/

tf-init:
	terraform -chdir=infra/main init

tf-plan: build
	terraform -chdir=infra/main plan

tf-apply: build
	terraform -chdir=infra/main apply

# Convenience wrapper for the same allowlist row the Admins tab writes —
# useful for adding the first colleague before anyone has logged in.
admin-add:
	@test -n "$(EMAIL)" || (echo "usage: make admin-add EMAIL=someone@example.com" && exit 1)
	infra/scripts/add-admin.sh "$(EMAIL)"

# Printable A4 recruitment poster. Defaults to the deployed landing page;
# override with `make poster URL=https://...` to point it elsewhere.
poster:
	python scripts/build_poster.py $(if $(URL),--url $(URL),)
