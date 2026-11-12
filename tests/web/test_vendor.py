"""web/vendor/ holds exactly the files scripts/vendor_web.py fetched, byte for
byte (milestone E0). Changing a version means running the script and
changing the pin here, in the same pull request."""

import hashlib
from pathlib import Path

from vendor_web import FILES

VENDOR = Path(__file__).resolve().parents[2] / "web" / "vendor"

PINS = {
    "preact-htm.js": "72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7",
    "inter-latin-wght-normal.woff2": "f052ee44c3728dfd23aba8a4567150bc314d23903026fbb6ad089422c2df56af",
}


def test_every_vendored_file_is_the_one_fetched():
    for name, sha256 in PINS.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == sha256, name


def test_nothing_else_is_vendored_and_every_file_is_licensed():
    assert set(PINS) == set(FILES)
    assert {p.name for p in VENDOR.iterdir()} == set(PINS) | {"LICENSES.txt"}
    licenses = (VENDOR / "LICENSES.txt").read_text()
    for name in PINS:
        assert name in licenses
    for words in ("Apache License", "MIT License", "SIL Open Font License"):
        assert words in licenses


def test_the_renderer_is_loaded_from_here_and_never_from_a_cdn():
    web = VENDOR.parent
    for path in [*web.glob("*.html"), *web.glob("*.js"), *web.glob("social/*.js")]:
        text = path.read_text()
        for cdn in ("unpkg.com", "jsdelivr", "esm.sh", "cdnjs", "skypack"):
            assert cdn not in text, f"{path.name} loads from {cdn}"
