"""infra/scripts/domain.sh, run against a stand-in for the `aws` command.

The script buys something, so what is tested here is every way it refuses,
and the exact request it makes when it does not. Nothing reaches AWS: the
stand-in answers from environment variables and writes each call to a log.
The script has never been run against AWS by these tests.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "infra" / "scripts" / "domain.sh"

FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$*" in
  "sts get-caller-identity"*) echo "${FAKE_ACCOUNT:-111111111111}" ;;
  "organizations describe-organization"*) echo "${FAKE_MANAGEMENT:-111111111111}" ;;
  *"check-domain-availability"*) echo "${FAKE_AVAILABILITY:-AVAILABLE}" ;;
  *"list-prices"*) printf '%s\t%s\t%s\n' "${FAKE_PRICE:-19.0}" "${FAKE_RENEWAL:-19.0}" "${FAKE_CURRENCY:-USD}" ;;
  *"register-domain"*) echo "op-123" ;;
  *"list-operations"*) echo "(operations)" ;;
  *"get-domain-detail"*) echo '{"autoRenew": true}' ;;
  *) echo "fake aws: unexpected call: $*" >&2; exit 2 ;;
esac
"""

CONTACT = {
    "FirstName": "Test",
    "LastName": "Person",
    "ContactType": "PERSON",
    "AddressLine1": "1 Example Street",
    "City": "Exampleville",
    "CountryCode": "IL",
    "ZipCode": "0000000",
    "PhoneNumber": "+972.500000000",
    "Email": "nobody@example.com",
}


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "aws.log"
    log.touch()
    contact = tmp_path / "contact.json"
    contact.write_text(json.dumps(CONTACT))

    def _run(*args, stdin="", **env):
        environment = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "FAKE_AWS_LOG": str(log),
            "AWS_PROFILE": "mgmt-admin",
            "BGUCATS_DOMAIN_CONTACT": str(contact),
            **env,
        }
        done = subprocess.run(
            ["bash", str(SCRIPT), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        done.calls = log.read_text().splitlines()
        return done

    _run.contact = contact
    return _run


def bought(result):
    return [call for call in result.calls if "register-domain" in call]


def test_check_says_whether_it_is_free_and_what_it_costs(run):
    result = run("check", "bgucats.app", AWS_PROFILE="mgmt-ro")
    assert result.returncode == 0, result.stderr
    assert "bgucats.app: AVAILABLE" in result.stdout
    assert "first year: 19.0 USD" in result.stdout
    assert not bought(result)


def test_buying_registers_one_year_with_renewal_and_every_contact_hidden(run):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n")
    assert result.returncode == 0, result.stderr
    (call,) = bought(result)
    assert "--region us-east-1" in call
    assert "--domain-name bgucats.app" in call
    assert "--duration-in-years 1" in call
    assert "--auto-renew" in call
    for who in ("admin", "registrant", "tech"):
        assert f"--privacy-protect-{who}-contact" in call
        assert f"--{who}-contact file://{run.contact}" in call
    assert "op-123" in result.stdout


def test_the_contact_is_never_printed(run):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n")
    printed = result.stdout + result.stderr
    for private in ("Example Street", "Exampleville", "+972.500000000", "nobody@example.com"):
        assert private not in printed


@pytest.mark.parametrize("answer", ["", "no\n", "y\n", "YES\n"])
def test_nothing_is_bought_without_the_word_yes(run, answer):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin=answer)
    assert result.returncode != 0
    assert "Nothing bought" in result.stdout
    assert not bought(result)


def test_a_price_over_the_ceiling_is_refused_before_asking(run):
    result = run("buy", "bgucats.app", "--max-usd", "15", stdin="yes\n")
    assert result.returncode != 0
    assert "over the ceiling" in result.stderr
    assert not bought(result)


def test_buying_needs_a_ceiling(run):
    result = run("buy", "bgucats.app", stdin="yes\n")
    assert result.returncode != 0
    assert "--max-usd" in result.stderr
    assert result.calls == []


@pytest.mark.parametrize("state", ["UNAVAILABLE", "UNAVAILABLE_PREMIUM", "DONT_KNOW"])
def test_a_name_that_is_not_free_is_not_bought(run, state):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n", FAKE_AVAILABILITY=state)
    assert result.returncode != 0
    assert state in result.stderr
    assert not bought(result)


def test_a_price_in_another_currency_is_refused(run):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n", FAKE_CURRENCY="EUR")
    assert result.returncode != 0
    assert not bought(result)


@pytest.mark.parametrize("profile", ["bgucats-prod-admin", "bgucats-staging-admin", "default"])
def test_only_the_management_profiles_are_accepted(run, profile):
    result = run("check", "bgucats.app", AWS_PROFILE=profile)
    assert result.returncode != 0
    assert "management account" in result.stderr
    assert result.calls == []


def test_the_read_only_profile_cannot_buy(run):
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n", AWS_PROFILE="mgmt-ro")
    assert result.returncode != 0
    assert result.calls == []


def test_a_profile_that_is_not_the_management_account_is_refused(run):
    result = run("check", "bgucats.app", FAKE_ACCOUNT="222222222222")
    assert result.returncode != 0
    assert "management account is 111111111111" in result.stderr
    assert not [call for call in result.calls if "route53domains" in call]


def test_leftover_access_keys_are_refused(run):
    result = run("check", "bgucats.app", AWS_ACCESS_KEY_ID="AKIAEXAMPLE")
    assert result.returncode != 0
    assert result.calls == []


def test_a_contact_file_inside_the_repo_is_refused(run, tmp_path):
    inside = REPO / "build" / "test-domain-contact.json"
    inside.parent.mkdir(exist_ok=True)
    inside.write_text(json.dumps(CONTACT))
    try:
        result = run(
            "buy", "bgucats.app", "--max-usd", "25", stdin="yes\n",
            BGUCATS_DOMAIN_CONTACT=str(inside),
        )
    finally:
        inside.unlink()
    assert result.returncode != 0
    assert "inside the repo" in result.stderr
    assert not bought(result)


@pytest.mark.parametrize("missing", ["Email", "PhoneNumber", "ZipCode"])
def test_an_incomplete_contact_is_refused(run, missing):
    run.contact.write_text(json.dumps({**CONTACT, missing: ""}))
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n")
    assert result.returncode != 0
    assert missing in result.stderr
    assert not bought(result)


def test_a_phone_number_without_the_dot_is_refused(run):
    run.contact.write_text(json.dumps({**CONTACT, "PhoneNumber": "+972500000000"}))
    result = run("buy", "bgucats.app", "--max-usd", "25", stdin="yes\n")
    assert result.returncode != 0
    assert "+972.501234567" in result.stderr


@pytest.mark.parametrize("name", ["BGUcats.app", "bgucats", "a.b.app", "bgucats.app; rm -rf /", ""])
def test_a_name_that_is_not_one_plain_domain_is_refused(run, name):
    result = run("check", name)
    assert result.returncode != 0
    assert result.calls == []


def test_the_template_is_valid_and_needs_no_aws(run):
    result = run("contact-template", AWS_PROFILE="")
    assert result.returncode == 0
    assert set(json.loads(result.stdout)) == set(CONTACT)
    assert result.calls == []


def test_status_shows_nothing_about_a_person(run):
    result = run("status", "bgucats.app", AWS_PROFILE="mgmt-ro")
    assert result.returncode == 0, result.stderr
    (detail,) = [call for call in result.calls if "get-domain-detail" in call]
    assert "Contact" not in detail.split("--query", 1)[1].replace("RegistrantPrivacy", "")
