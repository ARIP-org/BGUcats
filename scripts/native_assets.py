"""The iPhone app's icon and launch image, drawn from web/icon.svg.

Run by hand when the icon changes; the PNGs it writes are committed, so a
build needs neither this script nor a browser.

    python scripts/native_assets.py

* **Icon:** 1024×1024, the same cat on a ginger sheet where the PWA's is
  paper, so the two can be told apart on one home screen (the owner's
  choice, 2026-11-11). No transparency: App Store Connect refuses an icon
  with an alpha channel.
* **Launch image:** what shows for the moment before the page draws. The
  storyboard fills the screen with it and crops the sides, so the cat sits
  small in the middle of a large sheet of the page's own paper colour.

Needs the dev requirements (Playwright's Chromium renders the SVG, Pillow
writes the files).
"""

import io
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
SVG = REPO / "web" / "icon.svg"
ASSETS = REPO / "native" / "ios" / "App" / "App" / "Assets.xcassets"
ICON = ASSETS / "AppIcon.appiconset" / "AppIcon-512@2x.png"
SPLASHES = [
    ASSETS / "Splash.imageset" / name
    for name in (
        "splash-2732x2732.png",
        "splash-2732x2732-1.png",
        "splash-2732x2732-2.png",
    )
]

# The PWA's icon is the cat on paper. The app's sheet is the ginger of the
# buttons, and what was paper on the cat becomes the lighter page white,
# which reads better against it.
PAPER = "#fbf6ec"
GINGER = "#e07b2f"
WHITE = "#fffdf8"

ICON_SIZE = 1024
SPLASH_SIZE = 2732
# A phone shows the middle 46% of the square's width; the cat takes a third
# of that.
SPLASH_CAT = 420


def app_icon_svg():
    """web/icon.svg recoloured for the app: ginger sheet, white details."""
    svg = SVG.read_text()
    sheet = f'<rect width="512" height="512" fill="{PAPER}"/>'
    if svg.count(sheet) != 1:
        raise SystemExit(f"{SVG} no longer starts with a paper sheet: {sheet}")
    return svg.replace(sheet, sheet.replace(PAPER, GINGER)).replace(PAPER, WHITE)


def render(svg, size):
    """An SVG text as a size×size RGB image."""
    html = "<style>html,body{margin:0}svg{display:block}</style>" + svg.replace(
        "<svg ", f'<svg width="{size}" height="{size}" ', 1
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("CHROME_PATH") or None
        )
        page = browser.new_page(viewport={"width": size, "height": size})
        page.set_content(html)
        png = page.screenshot()
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGB")


def main():
    render(app_icon_svg(), ICON_SIZE).save(ICON, optimize=True)

    # The launch image keeps the paper: the page that replaces it is paper.
    web_icon = render(SVG.read_text(), ICON_SIZE)
    paper = web_icon.getpixel((2, 2))
    splash = Image.new("RGB", (SPLASH_SIZE, SPLASH_SIZE), paper)
    cat = web_icon.resize((SPLASH_CAT, SPLASH_CAT), Image.LANCZOS)
    corner = (SPLASH_SIZE - SPLASH_CAT) // 2
    splash.paste(cat, (corner, corner))
    for path in SPLASHES:
        splash.save(path, optimize=True)

    for path in [ICON, *SPLASHES]:
        print(f"{path.relative_to(REPO)}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
