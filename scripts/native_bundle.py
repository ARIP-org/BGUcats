"""Packs web/ for the iPhone app (native/, Capacitor).

The PWA downloads web/ from its own address every time it opens. The iPhone
app carries a copy inside it, made here at build time, so two things the
page takes for granted in a browser have to be told to it:

* which deployment it belongs to: `config.json` is not in git, Terraform
  writes it per account (infra/main/web.tf). The copy packed into the app
  is downloaded from that deployment's public address;
* where the API is: in a browser `/api/` is the page's own address. Inside
  the app the page's address is capacitor://localhost, so the config gains
  `apiBase`, which web/app.js puts in front of every API call.

    python scripts/native_bundle.py --site https://d2rysfyl47qmmz.cloudfront.net

leaves native/www, which `npx cap sync ios` copies into the Xcode project.
Standard library only: it runs on a macOS runner before anything is
installed. Nothing here is a secret; config.json is public by design.
"""

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
OUT = REPO / "native" / "www"

# What the page needs to reach sign-in. The keys infra/main/web.tf writes.
REQUIRED = ("userPoolClientId", "cognitoDomain", "redirectUri")
LOCAL = {"127.0.0.1", "localhost"}


def site_origin(site):
    """https://host from whatever was typed. Plain http only for a test
    server on this machine."""
    url = urlsplit(site)
    if not url.hostname or url.scheme not in ("https", "http"):
        raise ValueError(f"not a site address: {site!r}")
    if url.scheme == "http" and url.hostname not in LOCAL:
        raise ValueError(f"the app talks to its API over https only: {site!r}")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError(f"the site's address, without a path: {site!r}")
    return f"{url.scheme}://{url.netloc}"


def fetch_config(origin):
    with urllib.request.urlopen(f"{origin}/config.json", timeout=20) as res:
        return json.load(res)


def bundle(site, config, out=OUT, web=WEB):
    """Copy web/ to `out` and write its config.json. Returns the config."""
    origin = site_origin(site)
    missing = [key for key in REQUIRED if not config.get(key)]
    if missing:
        raise ValueError(f"{origin}/config.json has no {', '.join(missing)}")

    out = Path(out)
    if out.exists():
        # It is about to be deleted: only ever a bundle this script made.
        if any(out.iterdir()) and not (out / "index.html").is_file():
            raise ValueError(f"{out} exists and is not a bundle; not deleting it")
        shutil.rmtree(out)
    shutil.copytree(web, out)

    packed = {**config, "apiBase": origin}
    (out / "config.json").write_text(json.dumps(packed, indent=2) + "\n")
    return packed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--site",
        required=True,
        help="the deployment's app address, e.g. https://d2rysfyl47qmmz.cloudfront.net",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    try:
        origin = site_origin(args.site)
        packed = bundle(origin, fetch_config(origin), args.out)
    except (ValueError, OSError) as err:
        print(f"native bundle: {err}", file=sys.stderr)
        return 1
    files = sum(1 for path in args.out.rglob("*") if path.is_file())
    print(f"{args.out}: {files} files from web/, API at {packed['apiBase']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
