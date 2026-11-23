"""The Swift iPhone app (native/swift/): what can be held to from Linux.

Nothing here compiles Swift: the `swift` job of .github/workflows/ios.yml
does, on a Mac, and walks the app through its screens. These hold the
things that job cannot see or that a text edit breaks quietly: the project
file's references, the one iOS version, that nothing is signed, that the
pictures come out under the names the tests gave them, and that the upload
to TestFlight is this app, archived the way every pull request archived it.
"""

import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

import ios_archive
import ios_screenshots

REPO = Path(__file__).resolve().parents[2]
SWIFT = REPO / "native" / "swift"
PROJECT = (SWIFT / "BGUCats.xcodeproj" / "project.pbxproj").read_text()
SCHEME = SWIFT / "BGUCats.xcodeproj" / "xcshareddata" / "xcschemes" / "BGUCats.xcscheme"
ID = r"\b[0-9A-F]{24}\b"


def settings(name):
    return set(re.findall(rf"\b{name} = ([^;]+);", PROJECT))


# ------------------------------------------------------------ the project


def test_every_reference_in_the_project_file_is_defined():
    # The file is written by hand: nobody here has Xcode to write it.
    defined = set(re.findall(rf"^\t\t({ID[2:-2]})(?: /\*.*?\*/)? = \{{", PROJECT, re.MULTILINE))
    used = set(re.findall(ID, PROJECT))
    assert used - defined == set()
    assert PROJECT.count("{") == PROJECT.count("}") and PROJECT.count("(") == PROJECT.count(")")


def test_the_scheme_names_targets_the_project_has():
    targets = dict(
        re.findall(rf"^\t\t({ID[2:-2]}) /\* (\w+) \*/ = \{{\n\t\t\tisa = PBXNativeTarget;", PROJECT, re.MULTILINE)
    )
    assert sorted(targets.values()) == ["BGUCats", "BGUCatsUITests"]
    refs = ET.parse(SCHEME).getroot().iter("BuildableReference")
    named = {(ref.get("BlueprintIdentifier"), ref.get("BlueprintName")) for ref in refs}
    assert named == set(targets.items())
    # The UI tests are what `xcodebuild test -scheme BGUCats` runs.
    testable = ET.parse(SCHEME).getroot().find("TestAction/Testables/TestableReference/BuildableReference")
    assert testable.get("BlueprintName") == "BGUCatsUITests"


def test_both_folders_are_read_whole_so_a_new_file_needs_no_project_edit():
    groups = re.findall(r"isa = PBXFileSystemSynchronizedRootGroup;\n\t\t\tpath = (\w+);", PROJECT)
    assert groups == ["BGUCats", "BGUCatsUITests"]
    for folder in groups:
        assert any((SWIFT / folder).glob("*.swift")), folder


def test_one_ios_version_exactly_and_iphone_only():
    # The owner, issue 99: one version, the newest.
    assert settings("IPHONEOS_DEPLOYMENT_TARGET") == {"26.0"}
    assert settings("TARGETED_DEVICE_FAMILY") == {"1"}
    assert "macos-26" in (REPO / ".github" / "workflows" / "ios.yml").read_text()


def test_it_is_the_same_app_to_apple_and_nothing_in_the_project_signs_it():
    # The same bundle id as the packed app: on TestFlight the Swift app is
    # an update of it (the owner, 2026-11-23: the same app, not a second
    # one), and Cognito still answers at org.arip.bgucats://signin.
    assert settings("PRODUCT_BUNDLE_IDENTIFIER") == {"org.arip.bgucats", "org.arip.bgucats.uitests"}
    assert ios_archive.BUNDLE_ID == "org.arip.bgucats"
    # A version above the packed app's, so TestFlight offers it as newer.
    packed = (REPO / "native" / "ios" / "App" / "App.xcodeproj" / "project.pbxproj").read_text()
    newest_packed = max(tuple(map(int, v.split("."))) for v in re.findall(r"MARKETING_VERSION = ([\d.]+);", packed))
    (ours,) = {v for v in settings("MARKETING_VERSION") if v.count(".") == 2}
    assert tuple(map(int, ours.split("."))) > newest_packed
    for never in ("DEVELOPMENT_TEAM", "PROVISIONING_PROFILE", "CODE_SIGN_IDENTITY", "CODE_SIGN_ENTITLEMENTS"):
        assert never not in PROJECT, never
    # App Store Connect asks about encryption on every build without it.
    assert settings("INFOPLIST_KEY_ITSAppUsesNonExemptEncryption") == {"NO"}
    owners = (REPO / ".github" / "CODEOWNERS").read_text()
    assert "/native/swift/BGUCats.xcodeproj/" in owners


# -------------------------------------------------------------- the trail


def test_the_trail_keeps_what_the_web_apps_keeps():
    trail = (SWIFT / "BGUCats" / "Trail.swift").read_text()
    page = (REPO / "web" / "app.html").read_text()
    assert "static let limit = 80" in trail and "static let lineLimit = 200" in trail
    assert 'static let key = "bgucats.trail"' in trail and '"bgucats.trail"' in page


# --------------------------------------------------------------- the job


def workflow():
    return yaml.safe_load((REPO / ".github" / "workflows" / "ios.yml").read_text())


def test_the_swift_job_builds_and_looks_with_no_secret():
    job = workflow()["jobs"]["swift"]
    text = yaml.safe_dump(job)
    assert "secrets." not in text and "environment" not in job
    # Signed to run locally, as any simulator build: nothing to hold.
    assert "CODE_SIGN" not in text and "DEVELOPMENT_TEAM" not in text
    test = next(step for step in job["steps"] if "xcodebuild test" in step.get("run", ""))
    assert "-scheme BGUCats" in test["run"] and "-resultBundlePath" in test["run"]
    kept = next(step for step in job["steps"] if step.get("name") == "keep the pictures")
    assert kept["if"] == "always()" and kept["with"]["name"] == "ios-swift"


def test_the_upload_to_testflight_is_the_swift_app():
    # The owner, 2026-11-23: the native app ships now, in the same
    # TestFlight app, and its screens arrive one by one.
    jobs = workflow()["jobs"]
    upload = jobs["testflight"]
    assert upload["needs"] == "swift" and upload["environment"] == "testflight"
    assert upload["if"] == "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"
    text = yaml.safe_dump(upload)
    # Nothing of the packed app: no web/ copied in, no Capacitor.
    for packed in ("native_bundle", "cap sync", "npm ", "setup-node", "$PROJECT"):
        assert packed not in text, packed
    archive = next(step for step in upload["steps"] if step.get("name") == "archive")
    assert "scripts/ios_archive.py" in archive["run"]
    assert '--build "$GITHUB_RUN_NUMBER"' in archive["run"] and '--team "$TEAM_ID"' in archive["run"]
    assert "BGUCats.xcarchive" in archive["run"]
    export = next(step for step in upload["steps"] if "-exportArchive" in step.get("run", ""))
    assert '-archivePath "$RUNNER_TEMP/BGUCats.xcarchive"' in export["run"]


def test_every_pull_request_archives_the_app_as_the_upload_will():
    jobs = workflow()["jobs"]
    # Before an upload too: the upload needs this job, so it has no `if`.
    assert "if" not in jobs["swift"]
    check = next(step for step in jobs["swift"]["steps"] if step.get("name") == "archive it as the upload will")
    assert "scripts/ios_archive.py" in check["run"] and "if" not in check
    assert "scripts/ios_archive.py" in workflow()[True]["pull_request"]["paths"]
    # The packed app is checked on a pull request and uploaded by nothing.
    assert jobs["simulator"]["if"] == "github.event_name == 'pull_request'"
    assert "native/swift" not in yaml.safe_dump(jobs["simulator"])


# ------------------------------------------------------------ the archive


def test_both_jobs_run_one_archive_line_unsigned_for_a_real_iphone():
    line = ios_archive.command("out.xcarchive", 41)
    assert line[:2] == ["xcodebuild", "archive"]
    assert line[line.index("-project") + 1] == "native/swift/BGUCats.xcodeproj"
    assert line[line.index("-scheme") + 1] == "BGUCats"
    assert line[line.index("-configuration") + 1] == "Release"
    assert line[line.index("-destination") + 1] == "generic/platform=iOS"
    assert "CURRENT_PROJECT_VERSION=41" in line and "CODE_SIGNING_ALLOWED=NO" in line
    assert not any(part.startswith("DEVELOPMENT_TEAM") for part in line)
    assert ios_archive.command("out.xcarchive", 41, team="ABCDE12345")[-1] == "DEVELOPMENT_TEAM=ABCDE12345"
    assert (REPO / ios_archive.PROJECT).is_dir()


def built_app(tmp_path, **changes):
    """An app folder as Xcode leaves one, from this repository's own files."""
    app = tmp_path / "BGUCats.app"
    app.mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "org.arip.bgucats",
        "CFBundleVersion": "41",
        "CFBundleShortVersionString": "0.2.0",
        "MinimumOSVersion": "26.0",
        "ITSAppUsesNonExemptEncryption": False,
        "CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconName": "AppIcon"}},
    }
    info.update(changes)
    (app / "Info.plist").write_bytes(plistlib.dumps({k: v for k, v in info.items() if v is not None}))
    (app / "Assets.car").write_bytes(b"car")
    (app / "PrivacyInfo.xcprivacy").write_bytes((SWIFT / "BGUCats" / "PrivacyInfo.xcprivacy").read_bytes())
    return app


def test_a_whole_app_passes_the_look_inside_the_archive(tmp_path):
    assert ios_archive.faults(built_app(tmp_path), 41) == []


def test_the_look_inside_the_archive_names_what_is_wrong(tmp_path):
    def said(**changes):
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        folder.mkdir()
        return " ".join(ios_archive.faults(built_app(folder, **changes), 41))

    assert "CFBundleIdentifier is 'org.example.other'" in said(CFBundleIdentifier="org.example.other")
    assert "CFBundleVersion is '1', not '41'" in said(CFBundleVersion="1")
    assert "MinimumOSVersion" in said(MinimumOSVersion="18.0")
    assert "ITSAppUsesNonExemptEncryption" in said(ITSAppUsesNonExemptEncryption=None)
    assert "names no icon" in said(CFBundleIcons=None)

    app = built_app(tmp_path / "bare")
    (app / "PrivacyInfo.xcprivacy").unlink()
    (app / "Assets.car").unlink()
    wrong = " ".join(ios_archive.faults(app, 41))
    assert "No PrivacyInfo.xcprivacy" in wrong and "No Assets.car" in wrong
    assert "holds no app" in ios_archive.faults(tmp_path / "nothing.app", 41)[0]


def test_the_privacy_manifest_gives_a_reason_for_what_the_app_reads():
    # The trail is kept in UserDefaults, which Apple wants a reason for.
    assert "UserDefaults.standard" in (SWIFT / "BGUCats" / "Trail.swift").read_text()
    privacy = plistlib.loads((SWIFT / "BGUCats" / "PrivacyInfo.xcprivacy").read_bytes())
    assert privacy["NSPrivacyTracking"] is False and privacy["NSPrivacyTrackingDomains"] == []
    reasons = {api["NSPrivacyAccessedAPIType"]: api["NSPrivacyAccessedAPITypeReasons"] for api in privacy["NSPrivacyAccessedAPITypes"]}
    assert reasons == {ios_archive.USER_DEFAULTS: ["CA92.1"]}
    # Nothing is collected while the app calls no server. The first screen
    # that signs in or reads the API changes this file with it
    # (docs/privacy-data.md has the answers).
    sources = "".join(path.read_text() for path in (SWIFT / "BGUCats").glob("*.swift"))
    if "URLSession" not in sources:
        assert privacy["NSPrivacyCollectedDataTypes"] == []
    else:
        assert privacy["NSPrivacyCollectedDataTypes"], "the app calls a server: say what it collects"


# ----------------------------------------------------------- the pictures


def test_every_screen_is_kept_in_light_and_in_dark():
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert 'walk(look: "light")' in tests and 'walk(look: "dark")' in tests
    # The look is asked of the app, and each picture is checked to be it.
    assert 'app.launchArguments = ["-uiTesting", "-look", look]' in tests
    assert 'name.hasSuffix("-dark")' in tests and "XCTAssertLessThan(bright" in tests
    # Home, the three other tabs, and App info.
    assert 'keep(app, "home-\\(look)")' in tests and 'keep(app, "app-info-\\(look)")' in tests
    assert '[("Cats", "cats"), ("Scan a cat", "scan"), ("Profile", "profile")]' in tests
    # The app under test reads no network and keeps nothing.
    assert 'arguments.contains("-uiTesting")' in (SWIFT / "BGUCats" / "BGUCatsApp.swift").read_text()


def test_pictures_come_out_under_the_names_their_tests_gave_them():
    uuid = "0A1B2C3D-0000-4000-8000-00000000ABCD"
    manifest = [
        {
            "testIdentifier": "ScreensUITests/testEveryScreenInLight()",
            "attachments": [
                {"exportedFileName": "one.png", "suggestedHumanReadableName": f"home-light_0_{uuid}.png"},
                {"exportedFileName": "two.png", "suggestedHumanReadableName": f"app-info-light_1_{uuid}.png"},
                # The same name twice: both are kept.
                {"exportedFileName": "three.png", "suggestedHumanReadableName": f"home-light_0_{uuid}.png"},
                # No name from Xcode: the exported one.
                {"exportedFileName": "four.png"},
                {"suggestedHumanReadableName": "nothing-exported.png"},
            ],
        },
        {"testIdentifier": "a test that kept nothing"},
    ]
    assert ios_screenshots.named(manifest) == {
        "one.png": "home-light.png",
        "two.png": "app-info-light.png",
        "three.png": "home-light-2.png",
        "four.png": "four.png",
    }
