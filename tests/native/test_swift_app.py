"""The Swift iPhone app (native/swift/): what can be held to from Linux.

Nothing here compiles Swift: the `swift` job of .github/workflows/ios.yml
does, on a Mac, and walks the app through its screens. These hold the
things that job cannot see or that a text edit breaks quietly: the project
file's references, the one iOS version, that nothing is signed, that the
pictures come out under the names the tests gave them, and that the upload
to TestFlight is this app, archived the way every pull request archived it.
"""

import json
import plistlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

import ios_archive
import ios_screenshots
import privacy_table

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
    test = next(step for step in job["steps"] if step.get("name") == "walk through every screen")
    assert "xcodebuild test-without-building" in test["run"]
    assert "-scheme BGUCats" in test["run"] and "-resultBundlePath" in test["run"]
    kept = next(step for step in job["steps"] if step.get("name") == "keep the pictures")
    assert kept["if"] == "always()" and kept["with"]["name"] == "ios-swift"


def test_the_walks_time_limits_hold_every_test_at_its_longest():
    # A walk is one test and grows with every screen. At three minutes a
    # test, the cold walk (281 s with five launches of the app) was failed
    # with every step passed (2026-11-24). The limit is there for a hang:
    # it is well over what a test takes, the step's limit holds every test
    # of ScreensUITests at its longest (two walks, then Scan a cat's three
    # tests), and the job's holds the step with the warm-up and the build
    # before it and the archive after.
    job = workflow()["jobs"]["swift"]
    test = next(step for step in job["steps"] if step.get("name") == "walk through every screen")
    assert "-test-timeouts-enabled YES" in test["run"]
    default = int(re.search(r"-default-test-execution-time-allowance (\d+)", test["run"]).group(1))
    most = int(re.search(r"-maximum-test-execution-time-allowance (\d+)", test["run"]).group(1))
    assert 420 <= default <= most
    walks = re.findall(
        r"^    func (test\w+)\(\)", (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text(), flags=re.MULTILINE
    )
    assert {"testEveryScreenInLight", "testEveryScreenInDark"} <= set(walks), walks
    assert len(walks) * most <= test["timeout-minutes"] * 60, (walks, test["timeout-minutes"])
    wake = next(step for step in job["steps"] if step.get("name") == "wake the simulator")
    assert test["timeout-minutes"] + wake["timeout-minutes"] + 20 <= job["timeout-minutes"]


def test_the_simulator_is_woken_before_the_walk_and_that_is_not_counted():
    # Whatever runs first on a simulator that has just started pays for
    # its first minutes. The first walk failed three Mac runs in a row
    # with the app right, each time somewhere else (a launch of 118 s, a
    # question of 29 s, an app the simulator could not close), and the
    # second walk passed every time (2026-11-24). So the first thing to
    # run opens and closes the app and is no test: it asserts nothing,
    # its step cannot fail the job, and the walk runs the walk alone.
    job = workflow()["jobs"]["swift"]
    names = [step.get("name") for step in job["steps"]]
    assert names.index("build it") < names.index("wake the simulator") < names.index("walk through every screen")
    wake = job["steps"][names.index("wake the simulator")]
    assert wake["continue-on-error"] is True and wake["run"].rstrip().endswith("exit 0")
    assert "-only-testing:BGUCatsUITests/WarmUpUITests" in wake["run"]
    assert "-resultBundlePath" not in wake["run"]
    walk = job["steps"][names.index("walk through every screen")]
    assert "-only-testing:BGUCatsUITests/ScreensUITests" in walk["run"]
    assert "continue-on-error" not in walk
    warm = (SWIFT / "BGUCatsUITests" / "WarmUpUITests.swift").read_text()
    assert "final class WarmUpUITests: XCTestCase" in warm
    assert len(re.findall(r"^    func test\w+\(\)", warm, flags=re.MULTILINE)) == 1
    assert "XCTAssert" not in warm.split("final class")[1] and "XCTFail" not in warm
    # It takes the road the walk takes: the same made-up world, no network.
    assert '["-uiTesting", "-signedOut"]' in warm and '"sign-in.google"' in warm
    # Every class of UI tests is run by one step or the other.
    classes = sorted(
        name
        for file in (SWIFT / "BGUCatsUITests").glob("*.swift")
        for name in re.findall(r"final class (\w+): XCTestCase", file.read_text())
    )
    assert classes == ["ScreensUITests", "WarmUpUITests"]


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


def test_the_packed_apps_check_waits_for_the_page_not_for_a_clock():
    # It slept thirty seconds and then looked; a slow runner made a late
    # start read as a crash (2026-11-23).
    look = next(step for step in workflow()["jobs"]["simulator"]["steps"] if step.get("name") == "start it and look")
    run = look["run"]
    assert "sleep 30" not in run
    wait = run.split("console=$!")[1].split("simctl io")[0]
    assert 'grep -q "WebView loaded" build/ios/app.log' in wait and "for _ in $(seq 1 90)" in wait
    # The look comes after the wait, and still fails a page that never loaded.
    assert run.index("for _ in $(seq 1 90)") < run.index("screenshot build/ios/launch.png")
    assert "The web view never finished loading the page." in run


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
        "NSCameraUsageDescription": "The camera takes the photos.",
        "NSLocationWhenInUseUsageDescription": "A photo carries where it was taken.",
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
    assert "no NSCameraUsageDescription" in said(NSCameraUsageDescription=None)
    assert "no NSLocationWhenInUseUsageDescription" in said(NSLocationWhenInUseUsageDescription="  ")

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


def sources():
    return {path.name: path.read_text() for path in (SWIFT / "BGUCats").glob("*.swift")}


def test_the_privacy_manifest_says_what_this_app_sends_off_the_phone():
    # Apple's names for the kinds in docs/privacy-data.md (the output of
    # scripts/privacy_table.py). The manifest lists what this app can send
    # today; a kind joins it with the screen that first sends it.
    apple = {
        privacy_table.EMAIL: "EmailAddress",
        privacy_table.NAME: "Name",
        privacy_table.USER_ID: "UserID",
        privacy_table.CONTENT: "OtherUserContent",
        privacy_table.USAGE: "OtherUsageData",
        privacy_table.DIAGNOSTICS: "OtherDiagnosticData",
        privacy_table.PHOTOS: "PhotosorVideos",
        privacy_table.LOCATION: "PreciseLocation",
        privacy_table.CONTACTS: "Contacts",
        privacy_table.DEVICE_ID: "DeviceID",
    }
    assert set(apple) == set(privacy_table.KINDS)
    privacy = plistlib.loads((SWIFT / "BGUCats" / "PrivacyInfo.xcprivacy").read_bytes())
    declared = {}
    for kind in privacy["NSPrivacyCollectedDataTypes"]:
        # Every kind: tied to the account, for the app to work, never to track.
        assert kind["NSPrivacyCollectedDataTypeLinked"] is True
        assert kind["NSPrivacyCollectedDataTypeTracking"] is False
        assert kind["NSPrivacyCollectedDataTypePurposes"] == ["NSPrivacyCollectedDataTypePurposeAppFunctionality"]
        declared[kind["NSPrivacyCollectedDataType"].removeprefix("NSPrivacyCollectedDataType")] = kind

    code = "".join(sources().values())
    # It signs in and reads the feed: an account, a like, and the servers'
    # logs and counters that follow from any call.
    expected = {"EmailAddress", "Name", "UserID", "OtherUserContent", "OtherUsageData", "OtherDiagnosticData"}
    # What later screens bring. Each of these words in the code without its
    # kind in the manifest fails here, in the pull request that adds it.
    if re.search(r"CLLocation|CoreLocation", code):
        expected.add("PreciseLocation")
    if re.search(r"PhotosPicker|PHPicker|UIImagePickerController|AVCapture", code):
        expected.add("PhotosorVideos")
    if "/friends" in code or "/blocks" in code:
        expected.add("Contacts")
    if "registerForRemoteNotifications" in code:
        expected.add("DeviceID")
    assert set(declared) == expected
    assert set(declared) <= set(apple.values())


# ------------------------------------------------- signing in and the API


def test_the_app_belongs_to_the_deployment_the_builds_are_for():
    site = sources()["Site.swift"]
    assert f'URL(string: "{workflow()["env"]["SITE"]}")!' in site
    # Cognito answers the sign-in at the bundle id as a scheme, and the
    # user pool's client lists exactly that address.
    assert f'static let scheme = "{ios_archive.BUNDLE_ID}"' in site
    redirect = re.search(r'native_app_redirect = "([^"]+)"', (REPO / "infra" / "main" / "api.tf").read_text())[1]
    assert f'static let redirect = "{redirect}"' in site and redirect == f"{ios_archive.BUNDLE_ID}://signin"
    assert "local.native_app_redirect" in (REPO / "infra" / "main" / "cognito.tf").read_text()


def test_signing_in_is_the_web_apps_in_the_systems_own_sheet():
    auth = sources()["Auth.swift"]
    # Authorization code with PKCE, straight to Google, the account chooser
    # every time: web/lib/auth.js, line for line.
    web = (REPO / "web" / "lib" / "auth.js").read_text()
    for name, value in (
        ("response_type", "code"),
        ("scope", "openid email profile"),
        ("code_challenge_method", "S256"),
        ("identity_provider", "Google"),
        ("prompt", "select_account"),
    ):
        assert f'URLQueryItem(name: "{name}", value: "{value}")' in auth, name
        assert f'{name}: "{value}"' in web, name
    assert "/oauth2/authorize" in auth and "/oauth2/token" in auth
    # Google refuses a sign-in inside an app's own web view.
    code = "".join(sources().values())
    assert "webAuthenticationSession.authenticate(using: url, callbackURLScheme: Site.scheme)" in code
    assert "WKWebView" not in code and "SFSafariViewController" not in code
    # The tokens are in the keychain, on this phone only; nowhere else.
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in auth
    assert not re.search(r"defaults\.set\([^)]*[Tt]oken", code)


def test_a_sign_in_that_ends_puts_the_sign_in_screen_up():
    # Found in review: the server refused the token, the tokens were
    # dropped, and the tabs stayed up over calls that could only fail.
    code = sources()
    backend = code["Backend.swift"].split("final class StandInBackend")[0]
    assert 'auth.ended("the API answered 401")' in backend and "auth.signOut()" not in backend
    assert "world.gate.onEnded = { [weak self] in" in code["Session.swift"]
    assert 'phase = .signedOut(note: "Your sign-in ended. Sign in again.")' in code["Session.swift"]
    # Only Cognito refusing the grant itself ends a sign-in. A 429 or a 5xx
    # from it, or no connection, keeps the sign-in and sends no stale token.
    auth = code["Auth.swift"]
    assert "status == 400 || status == 401" in auth
    renew = auth.split("func pass() async -> Pass")[1].split("private func exchange")[0]
    assert renew.count("return .notNow") == 2 and renew.count("ended(") == 2
    assert "tokens.idToken)" in renew and renew.count("tokens.idToken") == 1  # only while it is still good
    # The feed leaves it to the session to say: no alert over the sign-in screen.
    # Reading the feed, a like, accepting the terms before one, and deleting a post.
    assert code["FeedView.swift"].count("if FeedModel.signInEnded(error) { return }") == 4
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert 'ending.launchArguments = ["-uiTesting", "-look", look, "-signInEnds"]' in tests
    assert 'keep(ending, "sign-in-ended-\\(look)")' in tests


def test_a_ui_test_reads_no_network_and_keeps_nothing():
    code = sources()
    stand_in = code["BGUCatsApp.swift"].split("static func standIn")[1]
    for made_up in ("MemoryStore()", "StandInGate(", "StandInBackend(", "DrawnPhotos()"):
        assert made_up in stand_in, made_up
    for real in ("KeychainVault", "LiveBackend", "NetPhotos", "Auth("):
        assert real not in stand_in, real
    # The network is reached from three places, each behind a protocol the
    # stand-in world replaces.
    assert {name for name, text in code.items() if "URLSession" in text} == {
        "Auth.swift",
        "Backend.swift",
        "Photos.swift",
    }
    assert 'arguments.contains("-signedOut")' in code["BGUCatsApp.swift"]


def test_the_trail_says_what_happened_and_never_who():
    # A line of the trail is copied by its owner to whoever is fixing the
    # app: no name, no address, no token, nothing anyone wrote.
    marks = re.findall(r"trail\.mark\((.*)\)\s*$", "\n".join(sources().values()), re.MULTILINE)
    assert len(marks) > 15
    for mark in marks:
        # What a line takes from the running app is what it interpolates.
        for taken in re.findall(r"\\\((.*?)\)", mark):
            for who in ("displayName", "username", "email", "userId", "oken", "text", "url", "path", "callback", "message"):
                assert who not in taken, mark
    # A call is named by its kind, never by its address, which carries ids.
    backend = sources()["Backend.swift"]
    assert 'trail.mark("api: \\(name) \\(status) in' in backend


def test_every_screen_says_what_it_is_from_the_first_moment():
    root = sources()["RootView.swift"]
    for state in ("case .starting:", "case .signedOut(let note):", "case .failed(let why):", "case .signedIn(let me):"):
        assert state in root, state
    # A call gives up, so "Loading" ends; and a start that failed offers
    # the way on, App info and the way out.
    assert "request.timeoutInterval = 20" in sources()["Backend.swift"]
    failed = root.split("struct FailedView")[1].split("struct ")[0]
    assert '"Try again"' in failed and "AppInfoView(world: world)" in failed and '"Sign out"' in failed


def test_a_posts_menu_deletes_ones_own_and_reports_anyone_elses():
    code = sources()
    feed = code["FeedView.swift"]
    menu = feed.split("private var menu: some View")[1].split("/// ")[0]
    assert "if post.mine {" in menu and '"Delete post"' in menu and '"Report"' in menu
    assert 'accessibilityIdentifier("menu.\\(post.id)")' in menu
    # Delete asks first, with the system's own alert.
    assert '.alert("Delete this post?", isPresented: deleteAsked, presenting: model.toDelete)' in feed
    # The routes of docs/app-plan/04-api.md, word for word.
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    assert 'call("DELETE", "/posts/\\(Auth.encode(postId))", as: "delete post")' in live
    assert 'call("POST", "/reports", body: body, as: "report")' in live
    for key in ("reportId", "targetType", "targetId", "reason"):
        assert f'"{key}": report.' in live, key
    assert 'body["note"] = note' in live
    # Neither asks for the terms: the API needs them for neither.
    report = code["ReportView.swift"]
    assert "termsRequired" not in report and "termsRequired" not in feed
    # A report's id is made once, when the sheet opens, so a retry is the
    # same report.
    assert "@State private var reportId = Ulid.make()" in report
    assert report.count("Ulid.make(") == 1


def test_the_reasons_are_the_servers_with_the_web_apps_words():
    from common import reports

    report = sources()["ReportView.swift"]
    cases = re.findall(r"^    case (\w+)(?: = \"(\w+)\")?$", report, re.MULTILINE)
    assert tuple(raw or name for name, raw in cases) == reports.REASONS
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    for name, raw in cases:
        assert f'case .{name}: "{words["report.reason." + (raw or name)]}"' in report, name
    assert f"static let noteLimit = {reports.NOTE_MAX}" in report
    assert f'Text("{words["report.lead"]}")' in report
    assert f'TextField("{words["report.note"]}"' in report
    assert words["report.sent"] == "Thank you. Someone looks at every report within a day."
    assert 'Text("Someone looks at every report within a day.")' in report


def test_an_id_made_on_the_phone_is_a_ulid():
    ulid = sources()["Ulid.swift"]
    # Crockford's base 32: no I, L, O or U. Ten characters of time, first,
    # then sixteen random ones: 26 in all.
    assert 'Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")' in ulid
    assert "for _ in 0..<10 {" in ulid and "for _ in 0..<16 {" in ulid
    assert "String(head.reversed()) + tail" in ulid
    assert "timeIntervalSince1970 * 1000" in ulid


# ----------------------------------------------------------- the pictures


def test_every_screen_is_kept_in_light_and_in_dark():
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert 'walk(look: "light")' in tests and 'walk(look: "dark")' in tests
    # The look is asked of the app, and each picture is checked to be it.
    assert 'app.launchArguments = ["-uiTesting", "-look", look]' in tests
    assert 'name.hasSuffix("-dark")' in tests and "XCTAssertLessThan(bright" in tests
    # The sign-in screen, Home with the feed, the three other tabs, and
    # App info.
    assert 'signedOut.launchArguments = ["-uiTesting", "-look", look, "-signedOut"]' in tests
    assert 'keep(signedOut, "sign-in-\\(look)")' in tests and 'keep(app, "home-liked-\\(look)")' in tests
    assert 'keep(app, "home-\\(look)")' in tests and 'keep(app, "app-info-\\(look)")' in tests
    assert '[("Cats", "cats"), ("Profile", "profile")]' in tests
    # Scan a cat, in its four states (issue 125).
    assert 'func testScanInLight()' in tests and 'func testScanInDark()' in tests
    for name in ("scan-empty", "scan-photos", "scan-retrying", "scan-sent"):
        assert f'keep(app, "{name}-\\(look)")' in tests, name
    # A post's menu, both ways, and the report sheet.
    for picture in ("post-menu-own", "post-menu-other", "report"):
        assert f'keep(app, "{picture}-\\(look)")' in tests, picture
    assert 'shown.contains("post: deleted")' in tests and 'shown.contains("report: sent (spam)")' in tests
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
                # What a failed test attaches: a name GitHub would refuse.
                {"exportedFileName": "five.txt", "suggestedHumanReadableName": f'Debug description for `"like.p1" Any`_0_{uuid}.txt'},
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
        "five.txt": "Debug description for -like.p1- Any-.txt",
    }
    # Nothing GitHub refuses in an artifact's file names.
    for name in ios_screenshots.named(manifest).values():
        assert not set(name) & set('"<>:|*?\r\n\\/`'), name


# ------------------------------------------------------------ Scan a cat


def test_the_app_says_why_it_asks_for_the_camera_and_the_place():
    # Asking without the sentence ends the app; the archive's look checks
    # the built app too (ios_archive.PERMISSIONS).
    app_configs = [
        block
        for block in re.findall(r"buildSettings = \{(.*?)\n\t\t\t\};", PROJECT, re.DOTALL)
        if "PRODUCT_BUNDLE_IDENTIFIER = org.arip.bgucats;" in block
    ]
    assert len(app_configs) == 2  # Debug and Release
    for key in ios_archive.PERMISSIONS:
        for block in app_configs:
            sentence = re.search(rf'INFOPLIST_KEY_{key} = "([^"]+)";', block)
            assert sentence and len(sentence[1]) > 20, key
    code = "".join(sources().values())
    assert "requestWhenInUseAuthorization" in code and "requestAlwaysAuthorization" not in code
    assert "sourceType = .camera" in code and "PhotosPicker(" in code


def test_scan_sends_by_the_web_apps_routes_in_its_write_order():
    code = sources()
    backend = code["Backend.swift"].split("final class StandInBackend")[0]
    # docs/app-plan/04-api.md, "The capture flow", rows 1 to 4, on the
    # desk's API, as web/outbox.js calls them.
    assert '"POST", "/encounters", base: "/api"' in backend
    assert '"/encounters/\\(Auth.encode(photo.encounterId))/media"' in backend
    assert '"/photos/\\(Auth.encode(photoId))/complete", base: "/api"' in backend
    assert '"contentType": "image/jpeg"' in backend and '"origin": gallery ? "gallery" : "camera"' in backend
    # A gallery photo sends no place at all, not even an empty one.
    start = backend.split("struct PhotoStart")[1].split("struct Presigned")[0]
    assert "if !gallery, let place {" in start
    # The file goes last in the presigned POST, as S3 wants.
    form = backend.split("static func form(")[1].split("\n    }\n")[0]
    assert form.index("for name in fields.keys.sorted()") < form.index('name=\\"file\\"')

    outbox = code["Outbox.swift"]
    # The encounter before any photo, and only an encounter with photos.
    one_pass = outbox.split("private func pass()")[1].split("private func sendOne")[0]
    assert one_pass.index("backend.createEncounter") < one_pass.index("withTaskGroup")
    assert "index.encounters.filter(\\.created)" in one_pass
    # Each photo: record, bytes, confirmation; three at a time.
    one = outbox.split("private func sendOne")[1].split("struct Outcome")[0]
    assert one.index("backend.startPhoto") < one.index("backend.upload") < one.index("backend.complete")
    assert "static let parallel = 3" in outbox
    # The bytes are on the phone before the index names them, and leave it
    # only once the server has confirmed them.
    send = outbox.split("func send(_ photos")[1].split("func retryFailed")[0]
    assert send.index("photo.jpeg.write") < send.index("save()")
    assert one.index("backend.complete") < one.index("forget(item.id)")
    # 20 MB at most, JPEG only.
    assert "static let limit = 20 * 1024 * 1024" in code["ScanView.swift"]
    assert "jpegData(compressionQuality:" in code["ScanView.swift"]
    # Ids are ULIDs made on the phone, by the app's one maker (Ulid.swift),
    # in web/outbox.js's alphabet.
    assert "Encounter(id: Ulid.make()," in outbox and "id: Ulid.make()," in code["ScanView.swift"]
    assert "enum ULID" not in outbox and "enum Ulid" not in outbox
    assert 'Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")' in code["Ulid.swift"]
    assert '"0123456789ABCDEFGHJKMNPQRSTVWXYZ"' in (REPO / "web" / "outbox.js").read_text()


def test_the_queue_is_kept_where_the_app_keeps_its_own_and_a_test_keeps_nothing_real():
    code = sources()
    app = code["BGUCatsApp.swift"]
    live = app.split("static func current")[1].split("static func standIn")[0]
    assert "Outbox(folder: Outbox.home" in live and "DevicePlaces()" in live
    stand_in = app.split("static func standIn")[1]
    assert "temporaryDirectory" in stand_in and "StandInPlaces()" in stand_in and "Outbox.home" not in stand_in
    assert ".applicationSupportDirectory" in code["Outbox.swift"]
    # The queue goes on at the start, signed in, with no tap.
    assert "world.outbox.open()" in code["RootView.swift"]
    # The queue reaches the server only through Backend: no network of its own.
    assert "URLSession" not in code["Outbox.swift"] + code["ScanView.swift"]


# --------------------------------------------------------------- the terms


def test_the_terms_are_asked_before_the_first_like_in_the_web_apps_words():
    code = sources()
    # The words are the web app's, in English (web/i18n/en.json, terms.*).
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    terms = code["Terms.swift"]
    for key, name in (("terms.title", "title"), ("terms.body", "body"), ("terms.accept", "accept")):
        assert f"static let {name} = {json.dumps(words[key])}" in terms, key
    # Accepting sends the version in force, read from GET /me.
    backend = code["Backend.swift"].split("final class StandInBackend")[0]
    assert 'call("POST", "/me/terms", body: ["version": version], as: "terms")' in backend
    assert 'termsCurrent: text(terms?["current"])' in code["Models.swift"]
    # The like asks first; a refusal for the terms asks once more.
    feed = code["FeedView.swift"]
    assert "try await session.termsFirst(changed: termsChanged)" in feed
    assert '(error as? ApiError)?.code == "terms_required" && !termsChanged' in feed
    assert ".termsDialog(session)" in code["RootView.swift"]
    session = code["Session.swift"]
    for mark in ("terms: asked", "terms: declined", "terms: accepted"):
        assert f'world.trail.mark("{mark}")' in session, mark
    # Its pictures, and the made-up member who has not accepted them.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert 'asking.launchArguments = ["-uiTesting", "-look", look, "-termsRequired"]' in tests
    assert 'changed.launchArguments = ["-uiTesting", "-look", look, "-termsChanged"]' in tests
    assert 'keep(asking, "terms-\\(look)")' in tests
    app = code["BGUCatsApp.swift"]
    assert 'arguments.contains("-termsRequired")' in app and 'arguments.contains("-termsChanged")' in app
    # The README no longer lists it as missing.
    missing = (SWIFT / "README.md").read_text().split("## Not here yet")[1]
    assert "accepting the terms" not in missing


def test_no_name_is_declared_twice_in_one_function_of_the_ui_tests():
    # Swift refuses it ("invalid redeclaration"), and only a Mac says so:
    # #127 added a second `again` to the walk and main stopped compiling
    # (2026-11-24). The walk is one long function that every screen's pull
    # request adds to, so two of them choosing one name is the likely way
    # for it to happen again. This reads the names declared at a function's
    # own level; one inside a loop or a closure is its own scope.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    functions = re.split(r"^    (?:private )?func ", tests, flags=re.MULTILINE)[1:]
    assert len(functions) >= 5
    for body in functions:
        name = body.split("(")[0]
        declared = re.findall(r"^        (?:let|var) (\w+)\b", body, flags=re.MULTILINE)
        twice = sorted({one for one in declared if declared.count(one) > 1})
        assert not twice, f"{name} declares {twice} more than once"


def test_a_dialogs_button_is_tapped_as_the_first_of_its_matches():
    # iOS 26 reports each button of a system dialog twice: a button inside
    # a button, with the same name and the same identifier. Asking whether
    # it exists is fine with two; a tap wants exactly one and fails with
    # "Multiple matching elements found" (2026-11-24: the terms' walk, the
    # first time it ran on a Mac). Only a Mac says so, so this reads the
    # walk: a button of a dialog is tapped through `.firstMatch`.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    dialogs = set(re.findall(r"let (\w+) = \w+\.alerts\[", tests))
    assert {"terms", "asked"} <= dialogs
    bare = re.compile(r"\.buttons\[[^\]]+\]\.tap\(\)")
    wrong = [
        line.strip()
        for line in tests.splitlines()
        if bare.search(line)
        and (".alerts" in line or any(re.search(rf"\b{one}\.buttons\[", line) for one in dialogs))
    ]
    assert not wrong, f"tapped without .firstMatch: {wrong}"
    assert 'terms.buttons["Cancel"].firstMatch.tap()' in tests


def test_the_walk_waits_with_one_patience_for_what_it_expects():
    # A wait is for "never", not for "slowly". The first walk runs on a
    # simulator still busy starting up: one question to it took nine
    # seconds, a wait of ten gave up on a post that was already deleted,
    # and the walk failed with the app right (2026-11-24). Every wait for
    # something expected takes the walk's one `patience`; a number of its
    # own is only for a wait that must not be met.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    patience = int(re.search(r"private let patience: TimeInterval = (\d+)", tests).group(1))
    assert patience >= 30
    assert tests.count("timeout: patience)") >= 30
    own = [line.strip() for line in tests.splitlines() if re.search(r"timeout: \d", line)]
    assert len(own) == 1 and own[0].startswith("XCTAssertFalse("), own
    # Nor a helper whose default is a number of its own (Scan a cat's
    # `expect` waited ten seconds unless told otherwise).
    assert not re.search(r"(?i)timeout: TimeInterval = \d", tests)
