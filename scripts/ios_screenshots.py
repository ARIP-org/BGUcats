"""The pictures a UI test kept, out of Xcode's result bundle.

The Swift app's UI tests (native/swift/BGUCatsUITests) attach a screenshot
of every screen to their result, under a name ("home-light"). Xcode keeps
attachments inside the `.xcresult` bundle under names of its own;
`xcresulttool` exports them with a manifest that says which is which. This
puts each under the name its test gave it, so a run's artifact reads like
`build/screenshots/` does for the web app.

    python3 scripts/ios_screenshots.py <Tests.xcresult> <out-dir>

Fails if there is no picture: a run that kept none showed nobody anything.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Xcode adds "_<n>_<UUID>" to the name a test gave an attachment.
ADDED = re.compile(r"_\d+_[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?=\.\w+$)")


def named(manifest):
    """{exported file: the name its test gave it}, for every attachment."""
    found = {}
    for test in manifest:
        for attachment in test.get("attachments", []):
            exported = attachment.get("exportedFileName")
            if not exported:
                continue
            given = attachment.get("suggestedHumanReadableName") or exported
            name = ADDED.sub("", Path(given).name)
            # Two attachments with one name: keep both, the later numbered.
            taken, n = set(found.values()), 2
            unique = name
            while unique in taken:
                unique = f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            found[exported] = unique
    return found


def main(argv):
    bundle, out = Path(argv[1]), Path(argv[2])
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["xcrun", "xcresulttool", "export", "attachments", "--path", str(bundle), "--output-path", str(raw)],
        check=True,
    )
    names = named(json.loads((raw / "manifest.json").read_text()))
    pictures = 0
    for exported, name in sorted(names.items(), key=lambda pair: pair[1]):
        if not (raw / exported).is_file():
            continue
        shutil.copyfile(raw / exported, out / name)
        pictures += name.lower().endswith((".png", ".jpg", ".jpeg", ".heic"))
        print(name)
    shutil.rmtree(raw)
    if not pictures:
        sys.exit("No picture in the result: the UI tests kept none.")


if __name__ == "__main__":
    main(sys.argv)
