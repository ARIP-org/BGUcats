"""The iPhone app's bundle (scripts/native_bundle.py) and the few settings
of the Xcode project that App Store Connect refuses a build without."""

import json
import plistlib
import re
from pathlib import Path

import pytest

import native_bundle as n

REPO = Path(__file__).resolve().parents[2]
IOS = REPO / "native" / "ios" / "App"
CONFIG = {
    "userPoolClientId": "client",
    "cognitoDomain": "example.auth.us-east-1.amazoncognito.com",
    "redirectUri": "https://app.example/",
}


# ------------------------------------------------------------ the bundle


def test_the_bundle_is_web_plus_a_config_that_says_where_the_api_is(tmp_path):
    out = tmp_path / "www"
    n.bundle("https://app.example/", CONFIG, out)

    packed = json.loads((out / "config.json").read_text())
    assert packed == {**CONFIG, "apiBase": "https://app.example"}
    web = {p.name for p in (REPO / "web").iterdir()}
    assert {p.name for p in out.iterdir()} == web | {"config.json"}
    assert (out / "app.js").read_bytes() == (REPO / "web" / "app.js").read_bytes()


def test_a_second_run_replaces_the_first(tmp_path):
    out = tmp_path / "www"
    n.bundle("https://app.example", CONFIG, out)
    (out / "left-over.js").write_text("old")
    n.bundle("https://other.example", CONFIG, out)

    assert not (out / "left-over.js").exists()
    assert json.loads((out / "config.json").read_text())["apiBase"] == (
        "https://other.example"
    )


def test_it_never_deletes_a_directory_it_did_not_make(tmp_path):
    (tmp_path / "notes.txt").write_text("mine")
    with pytest.raises(ValueError, match="not a bundle"):
        n.bundle("https://app.example", CONFIG, tmp_path)
    assert (tmp_path / "notes.txt").read_text() == "mine"


def test_a_config_without_sign_in_is_refused(tmp_path):
    with pytest.raises(ValueError, match="cognitoDomain"):
        n.bundle("https://app.example", {**CONFIG, "cognitoDomain": ""}, tmp_path / "w")
    assert not (tmp_path / "w").exists()


@pytest.mark.parametrize(
    "site",
    [
        "http://app.example",  # not https
        "app.example",  # no scheme
        "https://app.example/app",  # a path
        "https://app.example/?x=1",
        "ftp://app.example",
    ],
)
def test_only_an_https_site_address_is_accepted(site):
    with pytest.raises(ValueError):
        n.site_origin(site)


def test_the_site_address_is_reduced_to_its_origin():
    assert n.site_origin("https://app.example/") == "https://app.example"
    assert n.site_origin("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


# ------------------------------------------------- the Xcode project


def test_the_bundle_id_is_the_one_registered_with_apple():
    capacitor = json.loads((REPO / "native" / "capacitor.config.json").read_text())
    project = (IOS / "App.xcodeproj" / "project.pbxproj").read_text()
    ids = set(re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", project))
    assert ids == {capacitor["appId"]} == {"org.arip.bgucats"}


def test_the_app_says_why_it_asks_for_camera_and_location():
    """An upload without these is refused, and the app would be killed the
    moment Capture opened the camera."""
    with (IOS / "App" / "Info.plist").open("rb") as f:
        info = plistlib.load(f)
    for key in (
        "NSCameraUsageDescription",
        "NSMicrophoneUsageDescription",
        "NSLocationWhenInUseUsageDescription",
    ):
        assert len(info[key]) > 20, key
    # No encryption of its own, so no export question on every build.
    assert info["ITSAppUsesNonExemptEncryption"] is False


def test_the_icon_has_no_transparency():
    """App Store Connect refuses an icon with an alpha channel."""
    image = pytest.importorskip("PIL.Image")
    icon = image.open(
        IOS / "App" / "Assets.xcassets" / "AppIcon.appiconset" / "AppIcon-512@2x.png"
    )
    assert icon.size == (1024, 1024)
    assert icon.mode == "RGB"
