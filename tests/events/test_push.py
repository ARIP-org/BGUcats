"""src/events/push.py: one notification to Apple.

Apple is a stand-in here: a list of the requests it was sent and the
answers it gives. The key is a real one, made for the test, so the token
is really signed and really checked.
"""

import json

import boto3
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from moto import mock_aws

from events import push

DEVICE = {"apnsToken": "ab" * 32, "environment": "production"}
PAYLOAD = {"aps": {"alert": {"title": "BGU Cats", "body": "Maya posted a cat"}}}
NOW = 1_794_500_000


class Answer:
    def __init__(self, status, reason=None):
        self.status_code = status
        self._reason = reason

    def json(self):
        if self._reason is None:
            raise ValueError("no body")
        return {"reason": self._reason}


class Apple:
    """Answers in order; the last answer repeats."""

    def __init__(self, *answers):
        self.answers = list(answers) or [Answer(200)]
        self.asked = []

    def post(self, url, headers, content):
        self.asked.append({"url": url, "headers": headers, "body": json.loads(content)})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def key():
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, private.public_key()


@pytest.fixture
def apple(key, monkeypatch):
    """Push set up as the owner's step O7 leaves it, and Apple a stand-in."""
    with mock_aws():
        boto3.client("ssm", region_name="us-east-1").put_parameter(
            Name=push.KEY_PARAMETER, Value=key[0], Type="SecureString"
        )
        monkeypatch.setattr(push, "KEY_ID", "KEY1234567")
        monkeypatch.setattr(push, "TEAM_ID", "TEAM123456")
        monkeypatch.setattr(push, "TOPIC", "org.arip.bgucats")
        push._forget()
        monkeypatch.setattr(push, "_said", False)
        stand_in = Apple()
        monkeypatch.setattr(push, "_http", lambda: stand_in)
        yield stand_in
        push._forget()


def test_a_notification_goes_to_apple_signed_and_addressed(apple, key):
    assert push.send(DEVICE, PAYLOAD, collapse="post:P1", now=NOW) == "sent"
    (asked,) = apple.asked
    assert asked["url"] == f"https://api.push.apple.com/3/device/{'ab' * 32}"
    assert asked["body"] == PAYLOAD
    headers = asked["headers"]
    assert headers["apns-topic"] == "org.arip.bgucats"
    assert headers["apns-push-type"] == "alert"
    assert headers["apns-collapse-id"] == "post:P1"
    assert int(headers["apns-expiration"]) == NOW + push.KEEP_TRYING_S
    # The token: Apple's three fields, signed by the key and by no other.
    scheme, token = headers["authorization"].split(" ")
    assert scheme == "bearer"
    assert jwt.get_unverified_header(token) == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    claims = jwt.decode(token, key[1], algorithms=["ES256"], options={"verify_iat": False})
    assert claims == {"iss": "TEAM123456", "iat": NOW}


def test_a_phone_built_from_xcode_is_reached_in_apples_other_world(apple):
    push.send({**DEVICE, "environment": "development"}, PAYLOAD, now=NOW)
    assert apple.asked[0]["url"].startswith("https://api.sandbox.push.apple.com/3/device/")
    assert "apns-collapse-id" not in apple.asked[0]["headers"]


def test_one_token_serves_fifty_minutes_and_then_a_new_one_is_made(apple):
    for at in (NOW, NOW + 60, NOW + push.TOKEN_LIFE_S - 1, NOW + push.TOKEN_LIFE_S + 1):
        push.send(DEVICE, PAYLOAD, now=at)
    tokens = [a["headers"]["authorization"] for a in apple.asked]
    assert tokens[0] == tokens[1] == tokens[2] != tokens[3]


@pytest.mark.parametrize(
    ("answer", "result"),
    [
        (Answer(410, "Unregistered"), "gone"),
        (Answer(400, "BadDeviceToken"), "gone"),
        (Answer(400, "DeviceTokenNotForTopic"), "gone"),
        (Answer(400, "PayloadTooLarge"), "failed"),
        (Answer(429, "TooManyRequests"), "failed"),
        (Answer(503), "failed"),
    ],
)
def test_what_apple_answers_and_what_becomes_of_it(apple, answer, result):
    apple.answers = [answer]
    assert push.send(DEVICE, PAYLOAD, now=NOW) == result
    assert len(apple.asked) == 1


def test_a_connection_that_died_while_the_lambda_slept_is_made_again_once(apple):
    apple.answers = [httpx.RemoteProtocolError("closed"), Answer(200)]
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "sent"
    assert len(apple.asked) == 2
    # Apple out of reach altogether: two tries, and the change goes on.
    apple.answers = [httpx.ConnectTimeout("no answer")]
    apple.asked.clear()
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "failed"
    assert len(apple.asked) == 2


def test_a_token_apple_calls_expired_is_made_again_once(apple):
    apple.answers = [Answer(403, "ExpiredProviderToken"), Answer(200)]
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "sent"
    assert len(apple.asked) == 2
    # And if Apple still says so, that is the end of it for this one.
    apple.answers = [Answer(403, "ExpiredProviderToken")]
    apple.asked.clear()
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "failed"
    assert len(apple.asked) == 2


def test_without_the_key_nothing_is_sent_and_it_is_said_once(apple, caplog):
    boto3.client("ssm", region_name="us-east-1").delete_parameter(Name=push.KEY_PARAMETER)
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "off"
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "off"
    assert apple.asked == []
    assert caplog.text.count("push is not set up") == 1


def test_without_the_keys_settings_nothing_is_sent(apple, monkeypatch):
    monkeypatch.setattr(push, "KEY_ID", "")
    assert push.send(DEVICE, PAYLOAD, now=NOW) == "off"
    assert apple.asked == []


def test_the_log_never_holds_a_device_token(apple, caplog):
    apple.answers = [Answer(400, "PayloadTooLarge")]
    push.send(DEVICE, PAYLOAD, now=NOW)
    assert "Apple refused a push: 400 PayloadTooLarge" in caplog.text
    assert DEVICE["apnsToken"] not in caplog.text


def test_the_real_client_speaks_http2():
    push._forget()
    client = push._http()
    try:
        assert isinstance(client, httpx.Client)
        # Apple takes nothing older; h2 is what `httpx[http2]` brings.
        assert client._transport._pool._http2 is True
    finally:
        client.close()
        push._forget()
