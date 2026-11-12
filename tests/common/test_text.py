"""common.text.clean: what a person typed, as it will be stored."""

import pytest

from common.api import ApiError
from common.text import clean


def one(value, maximum=280):
    return clean(value, "name", maximum)


def many(value, maximum=280):
    return clean(value, "text", maximum, multiline=True)


@pytest.mark.parametrize(
    "value",
    ["Mango", "מנגו", "مانجو", "Манго", "Professor Pumpkin", "Garfield Jr."],
)
def test_ordinary_names_in_four_languages_are_kept(value):
    assert one(value) == value


def test_hebrew_points_and_arabic_vowel_marks_survive():
    assert one("שָׁלוֹם") == "שָׁלוֹם"
    assert one("مَرْحَبًا") == "مَرْحَبًا"


def test_fullwidth_and_ligatures_become_plain_letters():
    assert one("Ｍａｎｇｏ") == "Mango"
    assert one("ﬁsh") == "fish"


@pytest.mark.parametrize(
    "hidden",
    [
        "\u202e",  # right-to-left override
        "\u202d",  # left-to-right override
        "\u2066",  # left-to-right isolate
        "\u2069",  # pop directional isolate
        "\u200f",  # right-to-left mark
        "\u200b",  # zero-width space
        "\ufeff",  # byte-order mark
        "\u00ad",  # soft hyphen
        "\x07",  # a control character
        "\ue000",  # private use
    ],
)
def test_characters_that_change_display_without_being_text_are_removed(hidden):
    assert one(f"Man{hidden}go") == "Mango"


def test_a_direction_override_cannot_reverse_a_name():
    # Displayed, "\u202e" + "ognam" reads "mango"; stored, it is "ognam".
    assert one("\u202eognam") == "ognam"


def test_a_joiner_between_letters_is_removed():
    assert one("Man\u200dgo") == "Mango"


def test_emoji_built_with_a_joiner_are_kept():
    black_cat = "\U0001f408\u200d⬛"
    assert one(black_cat) == black_cat
    assert one(f"Shadow {black_cat}") == f"Shadow {black_cat}"


def test_a_tower_of_combining_marks_is_cut_to_four():
    # "x" has no precomposed accented form, so NFKC leaves every mark.
    zalgo = "x" + "\u0301" * 50
    assert one(zalgo) == "x" + "\u0301" * 4


def test_one_line_collapses_whitespace():
    assert one("  Mango \t\n  Jr.  ") == "Mango Jr."


def test_several_lines_keep_their_breaks_but_not_a_wall_of_empty_lines():
    assert many("Line one  \r\n\r\n\r\n\r\n  line   two\u2028three") == (
        "Line one\n\nline two\nthree"
    )


def test_length_is_counted_in_characters_after_cleaning():
    assert one("א" * 24, maximum=24) == "א" * 24
    assert one("x" + "\u200b" * 100, maximum=1) == "x"
    with pytest.raises(ApiError) as err:
        one("x" * 25, maximum=24)
    assert err.value.status == 400
    assert "24 characters" in err.value.message


@pytest.mark.parametrize("value", ["", "   ", "\u200b\u202e", None])
def test_empty_is_refused_when_required(value):
    with pytest.raises(ApiError) as err:
        one(value)
    assert err.value.status == 400
    assert "required" in err.value.message


def test_empty_is_allowed_when_optional():
    assert clean(None, "text", 280, required=False) == ""
    assert clean("  ", "text", 280, required=False, multiline=True) == ""


@pytest.mark.parametrize("value", [42, ["Mango"], {"name": "Mango"}])
def test_anything_but_text_is_refused(value):
    with pytest.raises(ApiError) as err:
        one(value)
    assert err.value.status == 400
