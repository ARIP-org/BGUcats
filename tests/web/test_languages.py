"""The app's languages (E10): every file under web/i18n/ says the same
things as English. No browser.

- the same keys, in the same order;
- the same {placeholders} in each string (a plural's forms together may
  leave {count} out of the form for one, never add one English lacks);
- a plural has exactly the forms its language's rules can ask for;
- the server accepts each, the client names each, and the service worker
  keeps each for a phone with no signal.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
I18N = REPO / "web" / "i18n"
ENGLISH = json.loads((I18N / "en.json").read_text())

# What Intl.PluralRules can answer for each language (CLDR).
FORMS = {
    "en": {"one", "other"},
    "he": {"one", "two", "other"},
    "ru": {"one", "few", "many", "other"},
    "ar": {"zero", "one", "two", "few", "many", "other"},
}
DRAFTS = sorted(set(FORMS) - {"en"})


def placeholders(value):
    return set(re.findall(r"\{(\w+)\}", json.dumps(value, ensure_ascii=False)))


def test_the_languages_are_the_ones_everything_else_names():
    assert {p.stem for p in I18N.glob("*.json")} == set(FORMS)
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert 'LANGUAGES = ("en", "he", "ru", "ar")' in handler
    client = (REPO / "web" / "social" / "i18n.js").read_text()
    names = re.search(r"export const LANGUAGES = \{([^}]*)\}", client).group(1)
    assert set(re.findall(r"(\w+):", names)) == set(FORMS)
    assert set(re.search(r"RIGHT_TO_LEFT = new Set\(\[([^\]]*)\]", client).group(1).replace('"', "").split(", ")) == {"he", "ar"}
    worker = (REPO / "web" / "sw.js").read_text()
    assert all(f'"/i18n/{code}.json"' in worker for code in FORMS)


def test_english_plurals_have_their_two_forms():
    for key, value in ENGLISH.items():
        if isinstance(value, dict):
            assert set(value) == FORMS["en"], key


@pytest.mark.parametrize("code", DRAFTS)
def test_a_language_says_everything_english_says(code):
    strings = json.loads((I18N / f"{code}.json").read_text())
    assert list(strings) == list(ENGLISH)
    wrong = []
    for key, english in ENGLISH.items():
        theirs = strings[key]
        if isinstance(english, dict) != isinstance(theirs, dict):
            wrong.append(f"{key}: a plural in one and not the other")
        elif isinstance(theirs, dict):
            if set(theirs) != FORMS[code]:
                wrong.append(f"{key}: forms {sorted(theirs)}")
            if not placeholders(theirs) <= placeholders(english):
                wrong.append(f"{key}: a placeholder English lacks")
            if any(not form.strip() for form in theirs.values()):
                wrong.append(f"{key}: an empty form")
        else:
            if placeholders(theirs) != placeholders(english):
                wrong.append(f"{key}: placeholders {sorted(placeholders(theirs))}")
            if not theirs.strip():
                wrong.append(f"{key}: empty")
    assert not wrong, wrong


@pytest.mark.parametrize("code", DRAFTS)
def test_a_draft_is_translated_not_copied(code):
    strings = json.loads((I18N / f"{code}.json").read_text())
    # Names, numbers and marks are the same in every language.
    same = [
        k
        for k, v in strings.items()
        if v == ENGLISH[k]
        and re.search(r"[A-Za-z]{4,}", re.sub(r"\{\w+\}", "", json.dumps(v)))
        and "BGU" not in json.dumps(v)
    ]
    assert same in ([], ["language.en"]), same
