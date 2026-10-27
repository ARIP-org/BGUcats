#!/usr/bin/env python3
"""Generate the printable recruitment poster.

Not a hosted page and not Terraform-managed: the poster's whole job is to
become paper. It is built locally, opened in a browser, and printed to A4 —
which also means the QR code can be regenerated for a different URL without
touching any infrastructure.

The output is a single self-contained HTML file. The photo is inlined as a
data URI and the QR as inline SVG, so the file survives being emailed to
whoever has access to the good printer.

    make poster                      # URL from `terraform output site_url`
    make poster URL=https://...      # or point it anywhere

Then open build/poster.html and print at 100% scale, A4, no margins.
"""

import argparse
import base64
import pathlib
import subprocess
import sys

import segno

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERO = ROOT / "site" / "hero.webp"
OUTPUT = ROOT / "build" / "poster.html"

BOT_HANDLE = "@bgucatsbot"
BOT_URL = "https://t.me/bgucatsbot"

# The landing page counts visits by ?src= (stats page in the admin tool).
# Only the QR carries it: someone typing the printed address by hand is
# still counted, just as "no source".
QR_SOURCE = "poster"

# Enough tabs to span A4 without any one of them being too narrow to tear.
TEAR_OFF_TABS = 8


def site_url_from_terraform():
    result = subprocess.run(
        [
            "terraform",
            f"-chdir={ROOT / 'infra' / 'main'}",
            "output",
            "-raw",
            "site_url",
        ],
        capture_output=True,
        text=True,
        # Handled below with a message that says what to do about it, rather
        # than a CalledProcessError traceback.
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            "Could not read site_url from Terraform. Apply infra/main first, "
            "or pass URL=https://... explicitly.\n\n" + result.stderr.strip()
        )
    return result.stdout.strip()


def qr_svg(data, scale, dark="#2a2320"):
    """QR as inline SVG.

    error='h' (30% recovery) because this is going on a wall: it will be
    rained on, sun-bleached, and photographed at an angle from two metres
    away by someone who is not trying very hard.
    """
    qr = segno.make(data, error="h")
    return qr.svg_inline(scale=scale, dark=dark, border=2)


def tracked(url):
    """The URL with ?src=poster, unless it already carries a query."""
    return url if "?" in url else f"{url}?src={QR_SOURCE}"


def build(site_url):
    hero_data = base64.b64encode(HERO.read_bytes()).decode()
    qr_target = tracked(site_url)

    tabs = "\n".join(
        f"""        <div class="tab">
          <div class="tab-qr">{qr_svg(qr_target, scale=2)}</div>
          <div class="tab-text" dir="ltr">{BOT_HANDLE}</div>
        </div>"""
        for _ in range(TEAR_OFF_TABS)
    )

    html = POSTER_TEMPLATE.format(
        hero_data=hero_data,
        big_qr=qr_svg(qr_target, scale=7),
        site_url=site_url.replace("https://", "").rstrip("/"),
        bot_handle=BOT_HANDLE,
        bot_url=BOT_URL,
        tabs=tabs,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html)
    print(f"Wrote {OUTPUT}")
    print(f"QR points at {qr_target}")
    print("\nOpen it and print: A4 portrait, 100% scale, background graphics on.")


POSTER_TEMPLATE = """<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<title>BGUcats poster</title>
<style>
  /* A4 portrait, edge to edge. Printers disagree about margins, so the
     layout keeps everything important well inside a 12mm safe area. */
  @page {{ size: A4 portrait; margin: 0; }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    width: 210mm;
    height: 297mm;
    background: #faf5ec;
    color: #2a2320;
    /* Hebrew serif coverage in system fonts is patchy; sans everywhere. */
    font-family: system-ui, -apple-system, "Segoe UI", "Noto Sans Hebrew",
      "Arial Hebrew", Arial, sans-serif;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}

  .poster {{
    flex: 1;
    padding: 16mm 14mm 6mm;
    display: flex;
    flex-direction: column;
  }}

  .kicker {{
    font-size: 11pt;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #b45c1c;
    margin-bottom: 5mm;
  }}

  h1 {{
    font-size: 40pt;
    line-height: 1.03;
    letter-spacing: -0.025em;
    margin: 0 0 6mm;
    font-weight: 800;
  }}

  h1 em {{
    font-style: normal;
    color: #b45c1c;
  }}

  .lede {{
    font-size: 14pt;
    line-height: 1.45;
    margin: 0;
    max-width: 105mm;
    color: #40352f;
  }}

  .middle {{
    display: flex;
    gap: 10mm;
    align-items: center;
    margin: 8mm 0;
    flex: 1;
  }}

  .photo {{
    width: 88mm;
    flex-shrink: 0;
  }}

  .photo img {{
    width: 100%;
    aspect-ratio: 3 / 4;
    object-fit: cover;
    border-radius: 4mm;
    /* Mirrored for RTL, where the photo sits on the right. */
    transform: rotate(2deg);
    box-shadow: 0 4mm 12mm rgba(80, 55, 30, 0.25);
  }}

  .ask {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }}

  .qr {{
    background: #fff;
    padding: 4mm;
    border-radius: 3mm;
    border: 0.6mm solid #e4d8c3;
    line-height: 0;
  }}

  .qr svg {{ display: block; width: 52mm; height: 52mm; }}

  .scan {{
    font-size: 15pt;
    font-weight: 750;
    margin: 5mm 0 1mm;
  }}

  .url {{
    font-size: 10pt;
    color: #6b5f56;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}

  .or {{
    font-size: 11pt;
    color: #6b5f56;
    margin: 4mm 0 2mm;
  }}

  .handle {{
    display: inline-block;
    background: #d9772e;
    color: #fff;
    font-size: 15pt;
    font-weight: 750;
    padding: 3mm 7mm;
    border-radius: 99mm;
  }}

  .steps {{
    display: flex;
    gap: 5mm;
    margin-bottom: 5mm;
  }}

  .step {{
    flex: 1;
    background: #fff;
    border: 0.4mm solid #e4d8c3;
    border-radius: 3mm;
    padding: 4mm 5mm;
  }}

  .step b {{ display: block; font-size: 11.5pt; margin-bottom: 1mm; }}
  .step span {{ font-size: 10pt; color: #6b5f56; line-height: 1.35; }}

  /* Tear-off tabs. The dashed rule is the cut line; each tab carries its
     own QR so a torn strip is still useful on its own. */
  .tear {{
    border-top: 0.5mm dashed #b9a88c;
    display: flex;
    height: 34mm;
  }}

  .tab {{
    flex: 1;
    border-left: 0.4mm dashed #d6c8ae;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2mm;
    padding: 3mm 0;
  }}

  .tab:first-child {{ border-left: 0; }}

  .tab-qr svg {{ display: block; width: 15mm; height: 15mm; }}

  .tab-text {{
    writing-mode: vertical-rl;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #b45c1c;
  }}
</style>
</head>
<body>
  <div class="poster">
    <div class="kicker">אוניברסיטת בן-גוריון · באר שבע</div>
    <h1>כולם מכירים את חתולי הקמפוס.<br><em>אף אחד לא יודע איך קוראים להם.</em></h1>
    <p class="lede">
      בערך חמישים חתולים חיים בקמפוס הזה. אנחנו בונים תיעוד אמיתי של מי הם —
      ובשביל זה אנחנו צריכים את התמונות שלכם.
    </p>

    <div class="middle">
      <div class="photo">
        <img src="data:image/webp;base64,{hero_data}" alt="חתול מהקמפוס">
      </div>

      <div class="ask">
        <div class="qr">{big_qr}</div>
        <div class="scan">סרקו אותי</div>
        <div class="url" dir="ltr">{site_url}</div>
        <div class="or">או חפשו את הבוט בטלגרם</div>
        <div class="handle" dir="ltr">{bot_handle}</div>
      </div>
    </div>

    <div class="steps">
      <div class="step">
        <b>1 · רואים חתול</b>
        <span>בכל מקום בקמפוס. הם לא קשים למציאה.</span>
      </div>
      <div class="step">
        <b>2 · שולחים תמונות</b>
        <span>כמה זוויות של חתול אחד שוות יותר מתמונה מושלמת.</span>
      </div>
      <div class="step">
        <b>3 · וזהו</b>
        <span>אנחנו ממיינים ונותנים שמות. לוקח עשר שניות.</span>
      </div>
    </div>
  </div>

  <div class="tear">
{tabs}
  </div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        help="URL the QR code should point at. Defaults to the site_url Terraform output.",
    )
    args = parser.parse_args()
    build(args.url or site_url_from_terraform())


if __name__ == "__main__":
    main()
