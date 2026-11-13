"""Staging's site is web/ with web-staging/ laid over it (infra/main/web.tf):
the home-screen icon with "BETA" on it, and the manifest that names the
install. No AWS: the files and the Terraform that picks them."""

import json
from pathlib import Path

from PIL import Image, ImageChops

import beta_icon

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web"
OVERLAY = REPO / "web-staging"


def test_every_overlay_file_takes_the_place_of_one_in_web():
    """web.tf uploads the files of web/, each from web-staging/ when a
    namesake is there. A file with no namesake would never be uploaded,
    and would look as if it had been."""
    names = [p.relative_to(OVERLAY) for p in OVERLAY.rglob("*") if p.is_file()]
    assert names
    missing = [str(n) for n in names if not (WEB / n).is_file()]
    assert not missing, missing


def test_only_staging_gets_the_overlay():
    tf = (REPO / "infra" / "main" / "web.tf").read_text()
    assert 'var.environment == "staging" ? fileset(' in tf
    assert "source       = local.web_sources[each.key]" in tf
    assert "etag         = filemd5(local.web_sources[each.key])" in tf


def test_the_beta_icons_are_what_the_script_draws():
    """Compared as pictures, not bytes: a newer Pillow may pack a PNG
    differently. A changed web/icon-512.png fails this until
    `python scripts/beta_icon.py` is run again."""
    for name, drawn in beta_icon.build().items():
        kept = Image.open(OVERLAY / name).convert("RGB")
        assert kept.size == drawn.size, name
        difference = ImageChops.difference(kept, drawn.convert("RGB")).getbbox()
        assert difference is None, f"{name} differs from the script's output"


def test_the_beta_icon_differs_from_the_real_one_where_the_band_is():
    real = Image.open(WEB / "icon-512.png").convert("RGB")
    beta = Image.open(OVERLAY / "icon-512.png").convert("RGB")
    left, top, right, bottom = ImageChops.difference(real, beta).getbbox()
    # The band, edge to edge, and nothing above it: the cat is untouched.
    assert (left, right) == (0, 512)
    assert top >= beta_icon.BAND[0] - 2 and bottom <= beta_icon.BAND[1] + 2
    # Inside the central 80%, which Android's round crop keeps.
    assert top >= 512 * 0.1 and bottom <= 512 * 0.9


def test_the_staging_manifest_installs_as_the_beta():
    real = json.loads((WEB / "manifest.webmanifest").read_text())
    beta = json.loads((OVERLAY / "manifest.webmanifest").read_text())
    assert "beta" in beta["name"].lower() and "beta" in beta["short_name"].lower()
    # The same app in every other way: where it opens, and what it covers.
    for key in ("start_url", "scope", "display", "orientation"):
        assert beta[key] == real[key], key
    for icon in beta["icons"]:
        assert (OVERLAY / icon["src"].lstrip("/")).is_file(), icon["src"]
