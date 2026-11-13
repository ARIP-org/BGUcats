"""Rules for the member app's code that are easy to break by reflex
(docs/app-plan/05-client.md), checked on the files themselves.

- Only logical CSS properties in tokens.css and web/social/: Hebrew and
  Arabic read right to left, and adding that to finished CSS is a rewrite.
- No colour written outside tokens.css.
- Every string through t(), and every key t() is given exists in English.
- A screen never calls fetch itself; it goes through the data layer.
"""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
SOCIAL = WEB / "social"
STYLES = [WEB / "tokens.css", *SOCIAL.glob("*.css")]
SCRIPTS = list(SOCIAL.glob("*.js"))

PHYSICAL = re.compile(
    r"\b(?:(?:margin|padding|border|inset)-(?:left|right)"
    r"|border-(?:top|bottom)-(?:left|right)-radius"
    r"|(?<![-\w])(?:left|right)\s*:"
    r"|text-align\s*:\s*(?:left|right)"
    r"|float\s*:\s*(?:left|right)"
    r"|clear\s*:\s*(?:left|right))"
)
# A line that is truly physical (the camera's brackets) says so.
PHYSICAL_OK = "physical:"

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")


def lines(path):
    return enumerate(path.read_text().splitlines(), start=1)


def test_the_checks_have_files_to_check():
    assert STYLES and SCRIPTS


def test_only_logical_properties():
    found = [
        f"{path.name}:{n}: {line.strip()}"
        for path in [*STYLES, *SCRIPTS]
        for n, line in lines(path)
        if PHYSICAL.search(line) and PHYSICAL_OK not in line
    ]
    assert not found, found


def test_the_rule_catches_what_it_should():
    for bad in (
        "margin-left: 4px",
        "left: 0",
        "text-align: right",
        "padding-right:2px",
    ):
        assert PHYSICAL.search(bad), bad
    for good in (
        "margin-inline-start: 4px",
        "inset-inline-start: 0",
        "text-align: start",
    ):
        assert not PHYSICAL.search(good), good


def test_no_colour_outside_the_tokens():
    found = [
        f"{path.name}:{n}"
        for path in [p for p in STYLES if p.name != "tokens.css"] + SCRIPTS
        for n, line in lines(path)
        if COLOUR.search(line)
    ]
    assert not found, found


def test_every_theme_sets_every_token():
    css = (WEB / "tokens.css").read_text()
    blocks = re.findall(r'data-theme="([\w-]+)"\]\s*\{([^}]*)\}', css)
    assert {name for name, _ in blocks} == {
        "bgu-light",
        "bgu-dark",
        "cats-light",
        "cats-dark",
    }
    names = [set(re.findall(r"(--[\w-]+):", body)) for _, body in blocks]
    assert all(n == names[0] for n in names)
    assert len(names[0]) >= 30


def test_every_string_key_exists_in_english():
    english = json.loads((WEB / "i18n" / "en.json").read_text())
    used = {
        key
        for path in SCRIPTS
        for key in re.findall(r"""\bt(?:Rich)?\(\s*["']([\w.]+)["']""", path.read_text())
    }
    assert used, "no t() calls found: the check would pass for nothing"
    assert used <= set(english), sorted(used - set(english))


def test_plural_strings_have_an_other_form():
    english = json.loads((WEB / "i18n" / "en.json").read_text())
    for key, value in english.items():
        if isinstance(value, dict):
            assert "other" in value, key


def test_screens_do_not_fetch_for_themselves():
    allowed = {"main.js", "i18n.js", "data.js"}  # boot, strings, the data layer
    found = [
        path.name
        for path in SCRIPTS
        if path.name not in allowed and re.search(r"\bfetch\(", path.read_text())
    ]
    assert not found, found


def test_the_service_worker_keeps_every_file_the_member_app_loads():
    # The installed app opens with no signal only if every module of it is
    # in the shell the service worker keeps (web/sw.js).
    shell = set(re.findall(r'"(/[^"]+)"', (WEB / "sw.js").read_text().split("];")[0]))
    needed = {
        "/" + str(path.relative_to(WEB))
        for folder in ("social", "lib", "i18n", "vendor")
        for path in (WEB / folder).iterdir()
        if path.suffix in {".js", ".css", ".json", ".woff2"}
    } | {"/app.html", "/tokens.css"}
    assert needed <= shell, sorted(needed - shell)
