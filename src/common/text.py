"""Cleaning what a person typed, before it is stored or checked.

Every text a member writes passes through clean() on the server: names,
descriptions, usernames (docs/app-plan/02-architecture.md, "Abuse and
limits"). The phone's maxlength is a convenience; this is the check.

What it does, in order, and why:

1. NFKC normalisation. Fullwidth letters, ligatures and other look-alike
   forms become their plain letters, so the blocklist and the moderation
   model see what a reader sees, and "mango" in fullwidth is "mango".
2. Removes characters that change how text displays without being text:
   controls, unassigned and private-use code points, and Unicode "format"
   characters: direction overrides and isolates (U+202A-202E,
   U+2066-2069), marks such as RLM, zero-width spaces, soft hyphens, the
   byte-order mark. A direction override can make a name read differently
   from what is stored, which matters in an app that shows Hebrew, Arabic
   and English side by side. The one exception: the zero-width joiner
   between two characters that are not letters, which is how emoji are
   built ("🐈\u200d⬛" is a cat, a joiner and a black square). Between letters a
   joiner only hides things, and is removed.
3. At most four combining marks in a row. Hebrew points and Arabic vowel
   marks need one to three; a tower of fifty is a way to spill text over
   the lines around it.
4. Whitespace: one line becomes single spaces. Several lines (a post's
   description) keep their line breaks, at most one empty line in a row.
5. Length, in characters (code points) after all of the above.
"""

import re
import unicodedata

from common.api import ApiError

ZWJ = "\u200d"
MAX_COMBINING_MARKS = 4
# Category Zl and Zp: written as one line or paragraph break.
LINE_BREAKS = {"\u2028": "\n", "\u2029": "\n", "\r\n": "\n", "\r": "\n"}


def _keep(text, index):
    char = text[index]
    category = unicodedata.category(char)
    if char in "\n\t":
        return True
    if category in ("Cc", "Cs", "Co", "Cn"):
        return False
    if category == "Cf":
        if char != ZWJ or index == 0 or index == len(text) - 1:
            return False
        neighbours = (text[index - 1], text[index + 1])
        return not any(unicodedata.category(c).startswith("L") for c in neighbours)
    return True


def _cap_marks(text):
    out, run = [], 0
    for char in text:
        if unicodedata.category(char) in ("Mn", "Me"):
            run += 1
            if run > MAX_COMBINING_MARKS:
                continue
        else:
            run = 0
        out.append(char)
    return "".join(out)


def clean(value, field, maximum, *, required=True, multiline=False):
    """The cleaned text, or ApiError(400) saying what is wrong with it.

    An absent value (None) counts as empty: "" when not required.
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be text")
    text = unicodedata.normalize("NFKC", value)
    for old, new in LINE_BREAKS.items():
        text = text.replace(old, new)
    text = "".join(char for i, char in enumerate(text) if _keep(text, i))
    text = _cap_marks(text)
    if multiline:
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    if not text and required:
        raise ApiError(400, f"{field} is required")
    if len(text) > maximum:
        raise ApiError(400, f"{field} is longer than {maximum} characters")
    return text
