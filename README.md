# BGUcats

Identifying, naming, and tracking the ~50 cats of the BGU campus.

Design spec: [`docs/cat-app-design-spec.pdf`](docs/cat-app-design-spec.pdf).
Constraints digest for agents and humans: [`CLAUDE.md`](CLAUDE.md).
Which branch holds what, and which one is deployed: [`docs/branches.md`](docs/branches.md).
Working in the codespace from your own machine: [`docs/codespaces.md`](docs/codespaces.md).

**Current phase: 1 — collection and labeling infrastructure. No ML of any kind.**

The cat-names voting app is the phase 4 read path, and is deliberately out of
scope until there is a labeled dataset to build it on — see spec §2 for why the
data problem gates everything else.

## Development

This repo is built to run in a GitHub Codespace. Open it with **Code → Codespaces
→ Create codespace on main**; the dev container brings up Python 3.12, Terraform,
the AWS CLI, the GitHub CLI, and the Claude Code CLI.

Locally, VS Code with the Dev Containers extension opens the same container.

### First run inside the codespace

```bash
claude          # authenticate once (browser flow, or set the ANTHROPIC_API_KEY codespace secret)
pre-commit install   # done automatically by postCreate.sh, but harmless to rerun
make test       # once tests exist
make tf-init    # infra/main only; infra/bootstrap is applied once, by hand, see infra/README.md
```

Common commands are wrapped in the `Makefile` (`make fmt`, `make lint`, `make test`,
`make tf-init`, `make tf-plan`, `make tf-apply`).

### Layout

```
.devcontainer/  dev container definition
.github/        CI (GitHub Actions)
docs/           design spec
infra/          Terraform — infra/bootstrap (state backend, applied by hand),
                infra/main (application resources, see infra/README.md)
src/            Python Lambda handlers
tests/          pytest, moto-backed
```

## AWS

Nothing here requires a VPC — see spec §8.1. Region defaults to `us-east-1`.
Credentials come from a Codespaces secret or `aws configure`, never from a
committed file.
