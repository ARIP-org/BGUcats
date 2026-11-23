"""Archives the Swift iPhone app as App Store Connect takes it, and checks it.

Two jobs of .github/workflows/ios.yml run this, so they cannot drift apart:
`swift`, on every pull request that touches the iPhone app, and
`testflight`, before the upload. The archive is a Release build for a real
iPhone, unsigned: the upload signs it with a certificate Apple keeps. A
simulator build can pass while this one fails, and without the check on the
pull request that would be found by the owner's upload.

    python3 scripts/ios_archive.py <out.xcarchive> --build 123 [--team ABCDE12345]

After the build it reads the app inside the archive and fails, naming each
thing, if it is not what Apple and the phone expect: the bundle id the
TestFlight app has, the build number asked for, the one iOS version, an
icon, the answer about encryption, and the privacy manifest.
"""

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

PROJECT = "native/swift/BGUCats.xcodeproj"
SCHEME = "BGUCats"
BUNDLE_ID = "org.arip.bgucats"
IOS = "26.0"
# Reading UserDefaults (the trail, Trail.swift) is one of the things Apple
# wants a stated reason for; CA92.1 is "the app's own data".
USER_DEFAULTS = "NSPrivacyAccessedAPICategoryUserDefaults"


def command(archive, build, team=None):
    """The one xcodebuild line both jobs run."""
    line = [
        "xcodebuild",
        "archive",
        "-quiet",
        "-project",
        PROJECT,
        "-scheme",
        SCHEME,
        "-configuration",
        "Release",
        "-destination",
        "generic/platform=iOS",
        "-archivePath",
        str(archive),
        # App Store Connect wants a new number every time; the upload gives
        # its run's number, which also says which run made a build.
        f"CURRENT_PROJECT_VERSION={build}",
        # Unsigned on purpose. Signing an archive by itself needs a
        # development certificate and a registered device; the export signs
        # it for distribution, so no certificate or profile is stored.
        "CODE_SIGNING_ALLOWED=NO",
    ]
    if team:
        line.append(f"DEVELOPMENT_TEAM={team}")
    return line


def faults(app, build):
    """What is wrong with the built app, as sentences. Empty: nothing."""
    app = Path(app)
    if not (app / "Info.plist").is_file():
        return [f"{app} has no Info.plist: the archive holds no app."]
    info = plistlib.loads((app / "Info.plist").read_bytes())
    wrong = []

    def expect(key, value):
        if info.get(key) != value:
            wrong.append(f"Info.plist: {key} is {info.get(key)!r}, not {value!r}.")

    # The same app to Apple as the one TestFlight has: an update, not a
    # second app.
    expect("CFBundleIdentifier", BUNDLE_ID)
    expect("CFBundleVersion", str(build))
    expect("MinimumOSVersion", IOS)
    # Without it App Store Connect asks about encryption on every build.
    expect("ITSAppUsesNonExemptEncryption", False)
    if not info.get("CFBundleShortVersionString"):
        wrong.append("Info.plist: no CFBundleShortVersionString.")
    icons = info.get("CFBundleIcons", {}).get("CFBundlePrimaryIcon", {})
    if not (info.get("CFBundleIconName") or icons.get("CFBundleIconName")):
        wrong.append("Info.plist names no icon: App Store Connect refuses a build without one.")
    if not (app / "Assets.car").is_file():
        wrong.append("No Assets.car: the icon and the colours were not compiled in.")

    manifest = app / "PrivacyInfo.xcprivacy"
    if not manifest.is_file():
        wrong.append("No PrivacyInfo.xcprivacy in the app: the privacy manifest was not copied in.")
    else:
        privacy = plistlib.loads(manifest.read_bytes())
        stated = {api.get("NSPrivacyAccessedAPIType") for api in privacy.get("NSPrivacyAccessedAPITypes", [])}
        if USER_DEFAULTS not in stated:
            wrong.append(f"PrivacyInfo.xcprivacy gives no reason for {USER_DEFAULTS}, which the trail uses.")
        if privacy.get("NSPrivacyTracking") is not False:
            wrong.append("PrivacyInfo.xcprivacy does not say the app tracks nobody.")
    return wrong


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive")
    parser.add_argument("--build", required=True)
    parser.add_argument("--team")
    args = parser.parse_args(argv)

    subprocess.run(["xcodebuild", "-version"], check=True)
    subprocess.run(command(args.archive, args.build, args.team), check=True)

    app = Path(args.archive) / "Products" / "Applications" / f"{SCHEME}.app"
    wrong = faults(app, args.build)
    for sentence in wrong:
        print(f"::error::{sentence}")
    if wrong:
        return 1
    info = plistlib.loads((app / "Info.plist").read_bytes())
    print(f"Archived {info['CFBundleIdentifier']} {info['CFBundleShortVersionString']} ({info['CFBundleVersion']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
