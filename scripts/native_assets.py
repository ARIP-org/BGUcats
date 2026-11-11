"""The iPhone app's icon and launch image, drawn from web/icon.svg.

Run by hand when the icon changes; the PNGs it writes are committed, so a
build needs neither this script nor a browser.

    python scripts/native_assets.py

* **Icon:** 1024×1024, the SVG as it is. No transparency: App Store Connect
  refuses an icon with an alpha channel.
* **Launch image:** what shows for the moment before the page draws. The
  storyboard fills the screen with it and crops the sides, so the cat sits
  small in the middle of a large sheet of the same paper colour.

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

ICON_SIZE = 1024
SPLASH_SIZE = 2732
# A phone shows the middle 46% of the square's width; the cat takes a third
# of that.
SPLASH_CAT = 420


def render(size):
    """web/icon.svg as a size×size RGB image."""
    html = (
        "<style>html,body{margin:0}svg{display:block}</style>"
        + SVG.read_text().replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
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
    icon = render(ICON_SIZE)
    icon.save(ICON, optimize=True)

    paper = icon.getpixel((2, 2))
    splash = Image.new("RGB", (SPLASH_SIZE, SPLASH_SIZE), paper)
    cat = icon.resize((SPLASH_CAT, SPLASH_CAT), Image.LANCZOS)
    corner = (SPLASH_SIZE - SPLASH_CAT) // 2
    splash.paste(cat, (corner, corner))
    for path in SPLASHES:
        splash.save(path, optimize=True)

    for path in [ICON, *SPLASHES]:
        print(f"{path.relative_to(REPO)}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
