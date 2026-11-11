"""scripts/cloud_session_setup.sh, the cloud session's SessionStart hook.

Its last line is what the session shows. It used to say "set up" even when
the log said "pip install failed" (2026-11-11), so a session started with
no pytest and an old ruff and nobody knew why. These run the real script
with stand-ins for python3, pip, curl and terraform: no network, nothing
installed.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cloud_session_setup.sh"


def _stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, *, venv_ok, terraform_ok):
    home, stubs = tmp_path / "home", tmp_path / "stubs"
    venv = home / ".venvs" / "bgucats"
    # `python3 -m venv DIR` leaves a pip that works or one that fails.
    pip = "exit 0" if venv_ok else "echo 'ERROR: Cannot uninstall blinker' >&2; exit 1"
    _stub(
        stubs / "python3",
        f'mkdir -p "$3/bin" && printf "#!/bin/sh\\n{pip}\\n" > "$3/bin/pip"'
        ' && chmod +x "$3/bin/pip"',
    )
    _stub(stubs / "curl", "exit 7")  # no network: a download always fails
    if terraform_ok:
        _stub(home / ".local" / "bin" / "terraform", 'echo "Terraform v1.15.9"')
    env_file = tmp_path / "claude_env"
    env = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "CLAUDE_CODE_REMOTE": "true",
        "CLAUDE_PROJECT_DIR": str(REPO),
        "CLAUDE_ENV_FILE": str(env_file),
    }
    env.pop("BGUCATS_VENV", None)
    done = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    log = (tmp_path / "bgucats-cloud-setup.log").read_text()
    return done, log, env_file.read_text(), venv


def test_everything_installed_says_so_and_puts_the_venv_first(tmp_path):
    done, log, env_file, venv = _run(tmp_path, venv_ok=True, terraform_ok=True)
    assert done.returncode == 0
    assert done.stdout.startswith(
        "Cloud session: dev dependencies and Terraform set up"
    )
    assert "INCOMPLETE" not in done.stdout
    assert f"dev dependencies installed in {venv}" in log
    assert env_file.strip().startswith(f'export PATH="{venv}/bin:')


def test_a_failed_pip_install_is_named_and_the_session_still_starts(tmp_path):
    done, log, _, _ = _run(tmp_path, venv_ok=False, terraform_ok=True)
    assert done.returncode == 0
    assert "INCOMPLETE" in done.stdout
    assert "the dev dependencies" in done.stdout
    assert "Terraform" not in done.stdout.split("did not install")[0]
    assert "pip install failed" in log


def test_both_failing_names_both(tmp_path):
    done, log, _, _ = _run(tmp_path, venv_ok=False, terraform_ok=False)
    assert done.returncode == 0
    assert "the dev dependencies" in done.stdout
    assert "Terraform 1.15.9 did not install" in done.stdout
    assert "not installed" in log


def test_it_does_nothing_outside_a_cloud_session(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    env.pop("CLAUDE_CODE_REMOTE", None)
    done = subprocess.run(
        ["bash", str(SCRIPT)], check=False, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0
    assert done.stdout == ""
    assert not (tmp_path / "bgucats-cloud-setup.log").exists()
