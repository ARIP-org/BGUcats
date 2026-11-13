"""Contrast (E9): the words of the member app against what they sit on, in
each of the four themes, by WCAG 2's formula on web/tokens.css itself. No
browser.

4.5 to 1 for text, 3 to 1 for what is large or only an outline. The
colours are the prototype's; a pair that falls short is listed in
KNOWN_SHORT with what it measures, for the designer, and may not get
worse or be joined by another without this file saying so.
"""

import re
from pathlib import Path

import pytest

TOKENS = (Path(__file__).resolve().parents[2] / "web" / "tokens.css").read_text()
THEMES = ("bgu-light", "bgu-dark", "cats-light", "cats-dark")

# (the words, what they sit on, what is under that if it lets light through,
# the least ratio).
PAIRS = (
    ("ink", "bg", None, 4.5),
    ("ink", "surface", None, 4.5),
    ("muted", "bg", None, 4.5),
    ("muted", "surface", None, 4.5),
    ("accent", "bg", None, 4.5),
    ("accent", "surface", None, 4.5),
    ("accent", "chip", "surface", 4.5),
    ("ink", "chip-neutral", "surface", 4.5),
    ("muted", "chip-neutral", "surface", 4.5),
    ("on-accent", "heart", None, 4.5),
    ("on-danger", "danger", None, 4.5),
    ("danger", "surface", None, 3.0),
    ("border", "bg", None, 1.0),  # a hairline: read, never relied on
)

# theme, words, ground -> the ratio it has, rounded down to one decimal.
# White on the prototype's red (#E5534B), the words of a "Delete post" or
# "Send report" button: 3.7 to 1 in every theme, since the two are the same
# in all four. Enough for large text, short of 4.5 for a button's 16 px.
KNOWN_SHORT = {(theme, "on-danger", "danger"): 3.7 for theme in THEMES}


def _blocks():
    shared = {}
    themes = {name: {} for name in THEMES}
    css = re.sub(r"/\*.*?\*/", "", TOKENS, flags=re.S)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        values = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
        named = re.findall(r'data-theme="([\w-]+)"', selector)
        if named:
            for name in named:
                themes[name].update(values)
        elif selector.strip() == ":root":
            shared.update(values)
    return {name: {**shared, **values} for name, values in themes.items()}


def _rgba(value):
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return (*(int(digits[i : i + 2], 16) for i in (0, 2, 4)), 1.0)
    parts = [float(p) for p in re.findall(r"[\d.]+", value)]
    return (*parts[:3], parts[3] if len(parts) > 3 else 1.0)


def _over(top, under):
    r, g, b, a = top
    return tuple(a * c + (1 - a) * u for c, u in zip((r, g, b), under[:3], strict=True)) + (1.0,)


def _luminance(colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(theme, words, ground, under):
    values = _blocks()[theme]
    back = _rgba(values[f"--{ground}"])
    if under:
        back = _over(back, _rgba(values[f"--{under}"]))
    front = _over(_rgba(values[f"--{words}"]), back)
    light, dark = sorted((_luminance(front), _luminance(back)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_formula_knows_black_on_white():
    assert round(
        (_luminance((255, 255, 255)) + 0.05) / (_luminance((0, 0, 0)) + 0.05), 1
    ) == 21.0


@pytest.mark.parametrize("theme", THEMES)
def test_words_can_be_read_on_what_they_sit_on(theme):
    short = {}
    for words, ground, under, least in PAIRS:
        measured = ratio(theme, words, ground, under)
        known = KNOWN_SHORT.get((theme, words, ground))
        if known is not None:
            assert measured < least, f"{words} on {ground} in {theme} now passes: take it off KNOWN_SHORT"
            assert measured >= known, f"{words} on {ground} in {theme} got worse: {measured:.2f}"
        elif measured < least:
            short[(theme, words, ground)] = int(measured * 10) / 10
    assert not short, f"below the least ratio: {short}"
