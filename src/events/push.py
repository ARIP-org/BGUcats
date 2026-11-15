"""Sending one notification to Apple (B9; A5: straight to Apple, no SNS).

Apple's provider API is HTTP/2 only, and each request carries a token
signed with the team's key (ES256), good for an hour. Neither is in the
Python the Lambda runs on, so this module needs two packages
(`requirements.txt`): httpx with h2, and PyJWT with cryptography. It is
imported only when there is something to send (`handler._deliver`), so the
Lambda's other work, counters and badges, never loads them and cannot be
broken by them.

The key is a secret (`/bgucats/apns-auth-key`, typed by the owner with
`infra/scripts/set-secret.sh`, step O7). Its Key ID, the Team ID and the
app's bundle id are not, and come as settings. Until all of them exist,
nothing is sent and the log says so once per container.

Nothing here knows what a notification says or who it is for: `send`
takes a device and a payload. The device token is never logged.
"""

import json
import logging
import os
import time

import boto3
import httpx
import jwt

logger = logging.getLogger()

# Apple's two worlds. A build from Xcode registers with `development`;
# TestFlight and the App Store with `production`. A token is good in the
# one it was made in and nowhere else.
HOSTS = {
    "production": "https://api.push.apple.com",
    "development": "https://api.sandbox.push.apple.com",
}

KEY_PARAMETER = os.environ.get("APNS_KEY_PARAMETER", "/bgucats/apns-auth-key")
KEY_ID = os.environ.get("APNS_KEY_ID", "")
TEAM_ID = os.environ.get("APNS_TEAM_ID", "")
TOPIC = os.environ.get("APNS_TOPIC", "")  # the app's bundle id

# Apple accepts a token for an hour and refuses one renewed more often than
# every twenty minutes: one is made and kept for fifty.
TOKEN_LIFE_S = 50 * 60
# A notification the phone could not take in six hours is no longer news.
KEEP_TRYING_S = 6 * 3600
TIMEOUT_S = 10

# Apple's reasons that mean "this device will never take it": the app was
# removed, or the token is not one of this app's in this world.
GONE = frozenset({"Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic"})


class NotConfigured(Exception):
    """The key or one of its three settings is missing: push is not set up."""


_key = None
_token = (None, 0.0)
_client = None
_said = False


def _signing_key():
    global _key
    if _key is None:
        if not (KEY_ID and TEAM_ID and TOPIC):
            raise NotConfigured("APNS_KEY_ID, APNS_TEAM_ID or APNS_TOPIC is not set")
        ssm = boto3.client("ssm")
        try:
            found = ssm.get_parameter(Name=KEY_PARAMETER, WithDecryption=True)
        except ssm.exceptions.ParameterNotFound:
            raise NotConfigured(f"{KEY_PARAMETER} is not set") from None
        _key = found["Parameter"]["Value"]
    return _key


def provider_token(now=None):
    """The signed token every request carries, kept until it is nearly old."""
    global _token
    now = time.time() if now is None else now
    token, made = _token
    if token is None or now - made > TOKEN_LIFE_S:
        token = jwt.encode(
            {"iss": TEAM_ID, "iat": int(now)},
            _signing_key(),
            algorithm="ES256",
            headers={"kid": KEY_ID},
        )
        _token = (token, now)
    return token


def _http():
    # One connection, kept between invocations: Apple asks for that, and
    # treats a new connection per notification as an attack.
    global _client
    if _client is None:
        _client = httpx.Client(http2=True, timeout=TIMEOUT_S)
    return _client


def _forget():
    """Tests, and a connection that failed: start again from nothing."""
    global _key, _token, _client
    _key, _token, _client = None, (None, 0.0), None


def send(device, payload, collapse=None, now=None):
    """One payload to one device. "sent", "gone" (remove the device: Apple
    will never deliver to it), "failed" (try another time), or "off" (push
    is not set up in this account). Never raises: a notification is not
    worth failing the change that caused it."""
    global _said, _token, _client
    now = time.time() if now is None else now
    try:
        for attempt in (1, 2):
            again = attempt == 1
            headers = {
                "authorization": f"bearer {provider_token(now)}",
                "apns-topic": TOPIC,
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-expiration": str(int(now) + KEEP_TRYING_S),
            }
            if collapse:
                # Apple's limit is 64 bytes; two notifications with one id
                # show as one.
                headers["apns-collapse-id"] = collapse[:64]
            host = HOSTS.get(device.get("environment"), HOSTS["production"])
            try:
                response = _http().post(
                    f"{host}/3/device/{device['apnsToken']}",
                    headers=headers,
                    content=json.dumps(payload, separators=(",", ":")),
                )
            except httpx.HTTPError as exc:
                # Usually the kept connection, closed by Apple while the
                # Lambda slept between invocations: a fresh one, once.
                _client = None
                if again:
                    continue
                logger.warning("could not reach Apple: %s", type(exc).__name__)
                return "failed"
            if response.status_code == 200:
                return "sent"
            reason = _reason(response)
            if response.status_code == 410 or reason in GONE:
                return "gone"
            if reason == "ExpiredProviderToken" and again:
                _token = (None, 0.0)  # the clock disagreed with Apple's
                continue
            logger.warning("Apple refused a push: %s %s", response.status_code, reason)
            return "failed"
    except NotConfigured as exc:
        if not _said:
            logger.warning("push is not set up, nothing is sent: %s", exc)
            _said = True
        return "off"
    return "failed"


def _reason(response):
    try:
        return response.json().get("reason", "")
    except ValueError:
        return ""
