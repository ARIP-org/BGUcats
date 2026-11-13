"""Staging's home-screen icon: the app's icon with a "BETA" band under the cat.

Someone who installs the staging site next to the real app, or next to the
TestFlight build, has to be able to tell the two apart on the home screen.
`infra/main/web.tf` lays `web-staging/` over `web/` in the staging account
only, so these files take the place of the ones they are named after.

    python scripts/beta_icon.py

Rewrites web-staging/icon-512.png, icon-192.png and apple-touch-icon.png
from web/icon-512.png. The band sits inside the central 80% of the square,
so Android's round crop of a maskable icon keeps the word whole. The
letters are the app's own font (web/vendor), so the result does not depend
on what the machine has installed. Run it again when web/icon-512.png
changes; a test checks the three files are the script's output.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "web" / "icon-512.png"
FONT = REPO / "web" / "vendor" / "inter-latin-wght-normal.woff2"
OUT = REPO / "web-staging"
SIZES = {"icon-512.png": 512, "icon-192.png": 192, "apple-touch-icon.png": 180}

# In 512ths of the icon's side: the band's top and bottom, and the letters.
BAND = (378, 452)
BAND_COLOUR = "#E8913A"  # the app's accent (web/tokens.css, bgu-dark)
INK = "#1f1b18"  # the cat's black (web/icon.svg)
WORD = "BETA"
LETTER_HEIGHT = 46
TRACKING = 9


def beta_icon():
    """The 512px icon with the band. The band and its letters are drawn at
    four times the size and scaled down, so their edges are smooth, then
    laid over the icon, which is otherwise left exactly as it is."""
    scale = 4
    side = 512 * scale
    band = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(band)
    top, bottom = (y * scale for y in BAND)
    draw.rectangle([0, top, side, bottom - 1], fill=BAND_COLOUR)

    font = ImageFont.truetype(str(FONT), LETTER_HEIGHT * scale)
    font.set_variation_by_name("Bold")
    widths = [draw.textlength(letter, font=font) for letter in WORD]
    gap = TRACKING * scale
    x = (side - sum(widths) - gap * (len(WORD) - 1)) / 2
    middle = (top + bottom) / 2
    for letter, width in zip(WORD, widths, strict=True):
        draw.text((x, middle), letter, font=font, fill=INK, anchor="lm")
        x += width + gap

    icon = Image.open(SOURCE).convert("RGBA")
    icon.alpha_composite(band.resize((512, 512), Image.BOX))
    return icon.convert("RGB")


def build():
    """{file name: image} for every size."""
    big = beta_icon()
    return {
        name: big if side == 512 else big.resize((side, side), Image.LANCZOS)
        for name, side in SIZES.items()
    }


def main():
    OUT.mkdir(exist_ok=True)
    for name, image in build().items():
        image.save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
