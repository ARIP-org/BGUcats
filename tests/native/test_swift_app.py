"""The Swift iPhone app (native/swift/): what can be held to from Linux.

Nothing here compiles Swift: the `swift` job of .github/workflows/ios.yml
does, on a Mac, and walks the app through its screens. These hold the
things that job cannot see or that a text edit breaks quietly: the project
file's references, the one iOS version, that nothing is signed, and that
the pictures come out under the names the tests gave them.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

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
    # The same bundle id as the packed app: when the Swift app replaces it
    # on TestFlight, it is an update, and Cognito still answers at
    # org.arip.bgucats://signin.
    assert settings("PRODUCT_BUNDLE_IDENTIFIER") == {"org.arip.bgucats", "org.arip.bgucats.uitests"}
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


def test_the_upload_to_testflight_is_still_the_packed_app_alone():
    jobs = workflow()["jobs"]
    assert jobs["testflight"]["needs"] == "simulator"
    assert jobs["testflight"]["environment"] == "testflight"
    assert "native/swift" not in yaml.safe_dump(jobs["testflight"])
    assert "native/swift" not in yaml.safe_dump(jobs["simulator"])


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
