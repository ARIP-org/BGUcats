"""Fetch the member app's third-party files into web/vendor/ (milestone E0).

The page holds sign-in tokens and the iPhone app must open with no signal,
so nothing is loaded from a CDN (docs/app-plan/05-client.md, "The
renderer"). Each file comes out of an npm tarball whose sha512 is the one
the registry published, the way scripts/publish_model.py takes ONNX Runtime
Web; tests/web/test_vendor.py then pins each file's own sha256, so a file
changed by hand, or a different version, fails CI.

    python scripts/vendor_web.py          # writes web/vendor/, prints the pins

Run it only to change a version: the files are committed.
"""

import base64
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "web" / "vendor"

# name in web/vendor/ -> (tarball, the registry's sha512 of it, path inside)
FILES = {
    # Preact 10 with hooks and htm's tagged templates, in one 13 KB module:
    # the renderer A4 chose. htm is Apache-2.0, Preact MIT.
    "preact-htm.js": (
        "https://registry.npmjs.org/htm/-/htm-3.1.1.tgz",
        "983Vyg8NwUE7JkZ6NmOqpCZ+sh1bKv2iYTlUkzlWmA5JD2acKoxd4KVxbMmxX/85mtfdnDmTFoNKcg5DGAvxNQ==",
        "package/preact/standalone.module.js",
    ),
    # Inter, the prototype's font, every weight in one variable file, Latin
    # only (Hebrew, Russian and Arabic fall back to the system font until
    # E10 decides). SIL Open Font License 1.1.
    "inter-latin-wght-normal.woff2": (
        "https://registry.npmjs.org/@fontsource-variable/inter/-/inter-5.1.0.tgz",
        "Wj2dUGP0vUpxRGQTXQTCNJO+aLcFcQm+gUPXfj/aS877bQkEPBPv9JvZJpwdm2vzelt8NTZ+ausKlBCJjh2XIg==",
        "package/files/inter-latin-wght-normal.woff2",
    ),
}


def fetch(url, sha512):
    data = urllib.request.urlopen(url, timeout=60).read()
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != sha512:
        raise SystemExit(f"{url}: sha512 is not the registry's")
    return data


def main():
    VENDOR.mkdir(exist_ok=True)
    tarballs = {}
    for name, (url, sha512, inside) in FILES.items():
        if url not in tarballs:
            tarballs[url] = fetch(url, sha512)
        with tarfile.open(fileobj=io.BytesIO(tarballs[url])) as archive:
            data = archive.extractfile(inside).read()
        (VENDOR / name).write_bytes(data)
        print(f'    "{name}": "{hashlib.sha256(data).hexdigest()}",')


if __name__ == "__main__":
    sys.exit(main())
