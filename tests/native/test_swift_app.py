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
    # A walk grows with every screen. At three minutes a test, the cold
    # walk (281 s with five launches of the app) was failed with every
    # step passed (2026-11-24); at eight, Profile took the one walk past
    # it on a slow Mac (#150, 2026-11-27), and the walk was cut by launch
    # into tests of their own. The limit is there for a hang: it is well
    # over what a test takes, the step's limit holds every test of
    # ScreensUITests at its longest (the account's and every screen's
    # walks in each look, then Scan a cat's three tests), and the job's
    # holds the step with the warm-up and the build before it and the
    # archive after.
    job = workflow()["jobs"]["swift"]
    test = next(step for step in job["steps"] if step.get("name") == "walk through every screen")
    assert "-test-timeouts-enabled YES" in test["run"]
    default = int(re.search(r"-default-test-execution-time-allowance (\d+)", test["run"]).group(1))
    most = int(re.search(r"-maximum-test-execution-time-allowance (\d+)", test["run"]).group(1))
    assert 420 <= default <= most
    walks = re.findall(
        r"^    func (test\w+)\(\)", (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text(), flags=re.MULTILINE
    )
    assert {"testAccountInLight", "testAccountInDark", "testEveryScreenInLight", "testEveryScreenInDark"} <= set(walks), walks
    assert len(walks) * most <= test["timeout-minutes"] * 60, (walks, test["timeout-minutes"])
    wake = next(step for step in job["steps"] if step.get("name") == "wake the simulator")
    assert test["timeout-minutes"] + wake["timeout-minutes"] + 20 <= job["timeout-minutes"]


def test_a_walk_cut_in_two_keeps_both_looks():
    # The walk is cut by launch into tests of their own (#150,
    # 2026-11-27), and each part is still walked in both looks: a test
    # for one look has its twin for the other, calling the same walk.
    text = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    calls = dict(re.findall(r"^    func (test\w+)\(\) \{\n\s+(\w+)\(look: \"(?:light|dark)\"\)", text, flags=re.MULTILINE))
    looks = {name: walk for name, walk in calls.items() if name.endswith(("InLight", "InDark"))}
    assert {"testAccountInLight", "testEveryScreenInLight", "testScanInLight"} <= set(looks), looks
    for name, walk in looks.items():
        twin = name.replace("InLight", "InDark") if name.endswith("InLight") else name.replace("InDark", "InLight")
        assert looks.get(twin) == walk, (name, twin, looks)
    for name, walk in looks.items():
        look = "light" if name.endswith("InLight") else "dark"
        assert f'    func {name}() {{\n        {walk}(look: "{look}")' in text, name


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
    assert 'keep(app, "profile-\\(look)")' in tests
    # Cats (issue 143): the gallery, a search with one cat and with none, a
    # cat's page and its post, and the page of the cat with no name.
    for name in ("cats", "cats-search", "cats-search-none", "cat", "cat-post", "cat-unnamed"):
        assert f'keep(app, "{name}-\\(look)")' in tests, name
    assert "cats(app, look: look)" in tests.split("private func walk(")[1].split("private func cats(")[0]
    # Scan a cat, in its four states (issue 125), then the cat, the post,
    # "Posted" and the feed with the post first (issue 133).
    assert 'func testScanInLight()' in tests and 'func testScanInDark()' in tests
    for name in (
        "scan-empty",
        "scan-photos",
        "scan-retrying",
        "scan-sent",
        "scan-which-cat",
        "scan-post",
        "scan-posted",
        "home-after-post",
        # A cat that isn't here: the form, "Posted" after "Add & post", and
        # the feed with that post first (issue 141).
        "scan-new-cat",
        "scan-new-cat-posted",
        "home-after-new-cat",
    ):
        assert f'keep(app, "{name}-\\(look)")' in tests, name
    # The name poll on a cat's page (issue 146): as it is, after a vote,
    # and after a name suggested under -termsRequired.
    for name in ("cat-poll", "cat-poll-voted"):
        assert f'keep(app, "{name}-\\(look)")' in tests, name
    assert 'keep(naming, "cat-poll-suggested-\\(look)")' in tests
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


# ------------------------------------------------ Scan a cat, the second half


def test_the_pick_and_the_post_go_by_the_routes_of_the_capture_flow():
    # docs/app-plan/04-api.md, "The capture flow", rows 6 and 9, and
    # GET /cats; the pick on the desk's API, the post and the cats on the
    # member's, as web/outbox.js and web/social/scan.js call them.
    code = sources()
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    assert '"POST", "/encounters/\\(Auth.encode(encounterId))/pick", base: "/api", body: pick.body' in live
    assert 'exchange("POST", "/posts", body: post.body, as: "post", quiet: true)' in live
    assert 'call("GET", "/cats", as: "cats")' in live
    post = live.split("struct PostBody")[1].split("struct Presigned")[0]
    for key in ("postId", "sessionId", "photoIds", "claim", "shareRegion"):
        assert f'"{key}": ' in post, key
    # A cat chosen, else a new cat's proposal, else nothing ("Not sure").
    claim = '"claim": catId.map { ["catId": $0] as Any } ?? proposalId.map { ["proposalId": $0] as Any } ?? NSNull()'
    assert claim in post
    assert 'body["text"] = text' in post


def test_a_pick_with_no_model_is_what_the_server_takes():
    # src/admin/handler.py, `_record_pick`: `shown` lists one to five cats
    # and `ranked` may be empty. With no model, the cat chosen is the one
    # shown, as web/social/scan.js does; "Not sure" shows nothing and so
    # sends no pick at all.
    import re as regex

    handler = (REPO / "src" / "admin" / "handler.py").read_text()
    assert "not 0 < len(shown) <= PICK_SHOWN" in handler
    web = (REPO / "web" / "social" / "scan.js").read_text()
    no_model = regex.search(r'const NO_MODEL = "(\w+)"', web)[1]
    pick = sources()["Backend.swift"].split("struct PickBody")[1].split("struct PostBody")[0]
    assert f'static let noModel = "{no_model}"' in pick
    assert regex.fullmatch(r"[a-z0-9][a-z0-9.-]{0,39}", no_model)
    for line in ('"choice": "cat"', '"shown": [catId]', '"ranked": [Any]()', '"photoCount": max(1, photoCount)'):
        assert line in pick, line
    flow = sources()["ScanFlow.swift"]
    assert "let pick = unsure ? nil : catId.map { PickBody(catId: $0, photoCount: photos.count) }" in flow
    assert "catId: unsure ? nil : catId," in flow
    # Every photo of the encounter, in the order they were taken.
    assert "photoIds: photos.map(\\.id)," in flow


def test_the_pick_and_the_post_wait_for_every_photo_and_go_once():
    outbox = sources()["Outbox.swift"]
    one_pass = outbox.split("private func pass()")[1].split("private func sendOne")[0]
    # After the photos of the pass, and only for an encounter none of whose
    # photos is still in the queue.
    assert one_pass.index("withTaskGroup") < one_pass.index("await sendAfter()")
    after = outbox.split("private func sendAfter()")[1].split("private func changeAfter")[0]
    assert "let waiting = Set(index.items.map(\\.encounterId))" in after
    assert "encounter.created && !waiting.contains(encounter.id)" in after
    # The pick before the post; each marked sent in the index once it went.
    assert after.index("backend.pick(") < after.index("backend.post(")
    assert "$0.pickSent = true" in after and "postWent(encounter.id, post)" in after
    # not_ready is "again later", never shown; already_posted is success.
    ready = after.split('failure.code == "not_ready"')[1].split("} catch {")[0]
    assert "again = true" in ready and "posts[" not in ready
    posted = after.split('failure.code == "already_posted"')[1].split("} catch let")[0]
    assert "postWent(encounter.id, post)" in posted
    # An encounter is forgotten only when nothing follows it any more, and
    # not while its post's refusal is what its flow shows.
    assert outbox.count("!(encounter.after?.kept ?? false)") == 2
    assert "pending ?? false" not in outbox
    assert "pending || postFailed != nil" in outbox


def test_a_post_refused_for_good_outlives_a_launch_until_its_flow_ends():
    # The refusal lives in the index alone. Forgotten in the pass that got it,
    # a launch read the kept "Posted" flow as sent: "It is in your feed".
    outbox = sources()["Outbox.swift"]
    opened = outbox.split("func open()")[1].split("func send(")[0]
    assert opened.index("posts[encounter.id] = .failed(failed)") < opened.index("openFlow()")
    assert opened.index("openFlow()") < opened.index("dropRefused(keeping: flow?.encounterId)")
    ended = outbox.split("func endFlow()")[1].split("private func dropRefused")[0]
    assert "dropRefused(keeping: nil)" in ended
    dropped = outbox.split("private func dropRefused")[1].split("private func openFlow")[0]
    assert "after.postFailed != nil, !after.pending" in dropped
    assert "encounter.id != encounterId && !waiting.contains(encounter.id)" in dropped


def test_the_terms_come_before_post_sends_anything():
    page = sources()["ScanPages.swift"].split("struct PostPage")[1]
    action = page.split("private func post() async")[1]
    assert action.index("session.termsFirst()") < action.index("outbox.finish(")
    # The post's id is made once and kept before the post is queued.
    assert "flow.postId = flow.postId ?? Ulid.make()" in action
    assert action.index("flow.postId = flow.postId ?? Ulid.make()") < action.index("outbox.keepFlow(flow)")


def test_a_kept_flow_is_checked_before_it_is_used():
    code = sources()
    flow = code["ScanFlow.swift"]
    assert "guard let flow = try? JSONDecoder().decode(ScanFlow.self, from: data), flow.whole else { return nil }" in flow
    for check in ("ScanFlow.isUlid(encounterId)", "!ids.isEmpty", "Set(ids).count == ids.count", "!(unsure && catId != nil)"):
        assert check in flow, check
    opened = code["Outbox.swift"].split("private func openFlow()")[1].split("private func setFlowThumb")[0]
    assert "guard let kept = ScanFlow.read(data) else {" in opened
    assert 'trail.mark("scan: kept flow dropped, not whole")' in opened and "endFlow()" in opened
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert '["-uiTesting", "-look", "light", "-keepQueue", "-flowBroken"]' in tests
    assert 'arguments.contains("-flowBroken")' in code["BGUCatsApp.swift"]
    # The limits are the server's.
    assert "static let textLimit = 280" in flow and "static let photoLimit = 50" in flow
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert "POST_TEXT_MAX = 280" in handler and "POST_PHOTOS_MAX = 50" in handler


def test_a_description_is_counted_as_the_server_counts_it():
    # The server counts code points after NFKC (src/common/text.py); Swift's
    # String.count counts characters, and "❤️" is one of those and two code
    # points. Counted the Swift way, 200 of them passed on the phone and the
    # post was refused for good.
    code = sources()
    flow, page = code["ScanFlow.swift"], code["ScanPages.swift"]
    assert "text.precomposedStringWithCompatibilityMapping.unicodeScalars.count" in flow
    assert "ScanFlow.length(text) <= ScanFlow.textLimit" in flow
    assert "text.count <= ScanFlow.textLimit" not in flow
    assert "ScanFlow.length(now) > ScanFlow.textLimit" in page and "text = ScanFlow.cut(now)" in page
    assert 'Text("\\(ScanFlow.length(text))/\\(ScanFlow.textLimit)")' in page
    assert "flow.text = ScanFlow.cut(text)" in page
    assert "prefix(ScanFlow.textLimit)" not in page and "text.count" not in page


def test_a_post_sent_before_a_launch_says_it_was_sent_after_it():
    # A sent post's encounter is forgotten once nothing of it waits; a kept
    # "Posted" (or "Added") flow with no state for its post was sent.
    opened = sources()["Outbox.swift"].split("private func openFlow()")[1].split("private func setFlowThumb")[0]
    assert "if kept.ended, posts[kept.encounterId] == nil {" in opened
    assert "posts[kept.encounterId] = .sent" in opened
    assert "step == .posted || step == .added" in sources()["ScanFlow.swift"]


def test_the_post_pages_use_the_web_apps_words():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    page = sources()["ScanPages.swift"]
    for key in ("scan.which", "scan.location", "scan.locationOn", "scan.locationOff", "scan.post", "scan.descriptionHint", "feed.search", "cat.noName"):
        assert f'"{words[key]}"' in page, key


def test_a_post_made_a_moment_ago_says_just_now_as_the_web_app_does():
    # A post's time is the server's, a second ahead of the phone's now and
    # then: the post at the top of Home read "in 0s" (2026-11-26). Under a
    # minute either way is "Just now", in the web app's word.
    feed = (SWIFT / "BGUCats" / "FeedView.swift").read_text()
    assert "abs(at.timeIntervalSince(now)) < 60" in feed
    assert 'return "Just now"' in feed
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    assert words["time.justNow"] == "Just now"
    assert "Math.abs(seconds) < 60" in (REPO / "web" / "social" / "i18n.js").read_text()
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert '" · Just now"' in tests and '" · in "' in tests


# ------------------------------------------------- Scan a cat, a new cat


def swift_strings(text, call):
    """The (id, words) pairs of every `call(id: "...", name: "...")`."""
    return re.findall(rf'{call}\(id: "([^"]+)", name: "([^"]+)"\)', text)


def test_the_new_cats_choices_are_the_servers_with_the_web_apps_words():
    # src/common/proposals.py is what the server takes, web/regions.json the
    # places it knows; the app holds a copy of both, in the web app's words.
    import importlib.util

    spec = importlib.util.spec_from_file_location("proposals", REPO / "src" / "common" / "proposals.py")
    proposals = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proposals)
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    models = sources()["Models.swift"].split("enum Campus")[1].split("struct FeedPage")[0]
    coats = models.split("static let coats")[1].split("static let traits")[0]
    traits = models.split("static let traits")[1].split("static let places")[0]
    places = models.split("static let places")[1].split("static let elsewhere")[0]
    assert swift_strings(coats, "Choice") == [(c, words[f"coat.{c}"]) for c in proposals.COATS]
    assert swift_strings(traits, "Choice") == [(t, words[f"trait.{t}"]) for t in proposals.TRAITS]
    regions = json.loads((REPO / "web" / "regions.json").read_text())["regions"]
    assert swift_strings(places, "Choice") == [(r["id"], r["names"]["en"]) for r in regions]
    assert f'static let elsewhere = Choice(id: "{proposals.ELSEWHERE}", name: "{words["scan.elsewhere"]}")' in models


def test_a_proposal_goes_by_its_route_with_the_body_the_server_takes():
    # docs/app-plan/04-api.md, POST /proposals, and row 8 of the capture flow.
    code = sources()
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    assert 'exchange("POST", "/proposals", body: proposal.body, as: "proposal", quiet: true)' in live
    body = live.split("struct ProposalBody")[1].split("struct PostBody")[0]
    for key in ("proposalId", "sessionId"):
        assert f'"{key}": {key},' in body, key
    for key in ("nameIdea", "coat", "regionId", "traits"):
        assert f'body["{key}"] = {key}' in body, key
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert 'text.clean(body.get("nameIdea"), "nameIdea", 24, required=False)' in handler
    flow = code["ScanFlow.swift"]
    assert "static let nameLimit = 24" in flow
    # The id is made on the phone, once, and is what the post names.
    assert "proposalId: proposed?.proposalId," in flow


def test_a_new_cat_sends_no_pick():
    # With no model nothing was shown, and a pick that shows nothing is
    # refused (400); the web app sends none either (`endingWrites`).
    web = (REPO / "web" / "social" / "scan.js").read_text()
    assert "if (!writes.pick.shown.length) writes.pick = null;" in web
    code = sources()
    flow = code["ScanFlow.swift"]
    # A new cat has no catId: the one line that makes a pick makes none.
    assert "proposal == nil || (catId == nil && !unsure && proposal?.whole == true)" in flow
    assert "let pick = unsure ? nil : catId.map { PickBody(catId: $0, photoCount: photos.count) }" in flow
    adding = code["ScanPages.swift"].split("private func add() async")[1]
    assert "outbox.finish(encounterId: flow.encounterId, pick: nil, proposal: proposal, post: nil)" in adding


def test_the_proposal_waits_for_every_photo_and_the_post_for_the_proposal():
    outbox = sources()["Outbox.swift"]
    after = outbox.split("private func sendAfter()")[1].split("private func changeAfter")[0]
    # After the pick and before the post, in the pass that waits for every
    # photo of the encounter.
    assert after.index("backend.pick(") < after.index("backend.propose(") < after.index("backend.post(")
    proposing = after.split("backend.propose(")[1].split("backend.post(")[0]
    # Tried again: the post waits for it, in order.
    again = proposing.split("if outcome.again {")[1].split("}")[0]
    assert "again = true" in again and "continue" in again
    # already_proposed is sent.
    assert 'failure.code == "already_proposed"' in proposing
    taken = proposing.split('failure.code == "already_proposed"')[1].split("} catch {")[0]
    assert "again" not in taken and "postFailed" not in taken
    # Refused for good: the post that names it cannot go, and the screen
    # says why.
    assert "$0.postFailed = outcome.words" in proposing and "posts[encounter.id] = .failed(outcome.words)" in proposing
    assert "$0.proposalDone = true" in proposing
    # Kept until it has gone; an index from before it existed still reads.
    assert "(proposal != nil && proposalDone != true)" in outbox
    assert "var proposal: ProposalBody?" in outbox and "var proposalDone: Bool?" in outbox
    assert "from.proposal != after.proposal" in outbox
    # Ten a day: refused, not tried again all day.
    assert 'case 429 where step == "proposal":' in outbox
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert "PROPOSALS_PER_DAY = 10" in handler


def test_the_terms_come_before_just_add_sends_anything():
    page = sources()["ScanPages.swift"].split("struct NewCatPage")[1].split("struct PostPage")[0]
    adding = page.split("private func add() async")[1]
    assert adding.index("session.termsFirst()") < adding.index("outbox.finish(")
    # The proposal's id is made once and kept before it is queued.
    made = "flow.proposalId = flow.proposalId ?? Ulid.make()"
    assert made in adding and adding.index(made) < adding.index("outbox.keepFlow(flow)") < adding.index("outbox.finish(")
    # "Add & post" asks nothing yet: "Post" asks, and queues both.
    post = sources()["ScanPages.swift"].split("struct PostPage")[1].split("private func post() async")[1]
    assert made in post and post.index("session.termsFirst()") < post.index(made) < post.index("outbox.finish(")
    assert "proposal: writes.proposal, post: made" in post


def test_a_kept_new_cat_form_is_checked_before_it_is_used():
    code = sources()
    flow = code["ScanFlow.swift"]
    proposal = flow.split("struct Proposal")[1].split("/// The name idea")[0]
    for check in (
        "ScanFlow.length(nameIdea) <= ScanFlow.nameLimit",
        "Campus.coats.contains",
        "region == Campus.elsewhere.id || Campus.places.contains",
        "Set(traits).count == traits.count",
        "Campus.traits.contains",
    ):
        assert check in proposal, check
    assert "proposalId.map(ScanFlow.isUlid) ?? true" in flow
    whole = flow.split("var whole: Bool {")[2]
    assert "case .new:\n            return proposal != nil" in whole
    assert "case .added:\n            return proposal != nil && proposed" in whole
    # The walk's broken flow reads as one, on the form, with a coat the
    # server does not take.
    app = code["BGUCatsApp.swift"]
    assert '"step":"new"' in app and '"coat":"purple"' in app


def test_the_new_cat_form_uses_the_web_apps_words():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    code = sources()
    page = code["ScanPages.swift"].split("struct NewCatPage")[1].split("struct PostPage")[0]
    for key in ("scan.newCatTitle", "scan.nameIdeaHint", "scan.coat", "scan.where", "scan.traits", "scan.newCatNote", "scan.addOnly", "scan.addAndPost"):
        assert f'"{words[key]}"' in page, key
    assert f'"{words["scan.nameIdea"]} {words["scan.optional"]}"' in page
    assert f'"{words["scan.newCat"]}"' in code["ScanPages.swift"].split("struct PostPage")[1]
    assert f'"{words["scan.doneNew"]}"' in code["ScanView.swift"]
    # The row on "Which cat?" opens it, and no longer says it is not built.
    which = code["ScanPages.swift"].split("struct WhichCatPage")[1].split("struct CatRow")[0]
    assert "Not built yet" not in which and "newCat()" in which


def test_the_trail_marks_a_new_cats_steps_and_never_its_answers():
    code = sources()
    page = code["ScanPages.swift"]
    for mark in ("scan: new cat", "scan: new cat, to the post", "scan: new cat added, no post"):
        assert f'world.trail.mark("{mark}")' in page, mark
    outbox = code["Outbox.swift"]
    assert 'trail.mark("upload: proposal \\(status)")' in outbox
    marks = re.findall(r"trail\.mark\((.*)\)", page + outbox)
    for mark in marks:
        for answer in ("nameIdea", "coat", "regionId", "traits", "proposalId", "name"):
            assert answer not in mark.replace("new cat", ""), mark


# ------------------------------------------------------------------- Cats


def test_the_cats_tab_is_built_on_the_systems_own_controls():
    code = sources()
    root = code["RootView.swift"]
    tab = root.split('Tab("Cats"')[1].split("}")[0]
    assert "CatsView(world: world, session: session)" in tab and "NotBuiltYet" not in tab
    gallery = code["CatsView.swift"]
    for control in ("NavigationStack {", ".navigationDestination(for: CatRoute.self)", ".searchable(", "LazyVGrid(", ".refreshable {", "Menu {", "Picker("):
        assert control in gallery, control
    page = code["CatView.swift"]
    assert ".tabViewStyle(.page)" in page
    # The posts are the feed's own card, with its like, menu and sheets.
    assert "PostCard(post: post, world: world, model: posts)" in page
    assert ".postActions(posts, world: world)" in page
    assert "FeedModel(world: world, session: session, source: .cat(catId))" in page
    assert ".postActions(model, world: world)" in code["FeedView.swift"]


def test_the_cats_go_by_the_routes_of_the_api():
    # docs/app-plan/04-api.md: GET /cats, GET /cats/{catId}, GET
    # /cats/{catId}/posts. Each call is named for the trail by its kind,
    # never by its address, which carries the cat's id.
    live = sources()["Backend.swift"].split("final class StandInBackend")[0]
    assert 'call("GET", "/cats", as: "cats")' in live
    assert 'call("GET", "/cats/\\(Auth.encode(id))", as: "cat")' in live
    assert 'call("GET", "/cats/\\(Auth.encode(id))/posts", cursor: cursor, as: "cat posts")' in live
    # "Which cat?" reads the same answer.
    assert "try await catList().cats" in live
    plan = (REPO / "docs" / "app-plan" / "04-api.md").read_text()
    for route in ("| `GET /cats` |", "| `GET /cats/{catId}` |", "| `GET /cats/{catId}/posts` |"):
        assert route in plan, route


def test_a_cat_is_read_field_by_field_as_the_server_writes_it():
    import ast

    handler = (REPO / "src" / "app" / "handler.py").read_text()
    tree = ast.parse(handler)
    public = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "public_cat")
    sent = {k.value for n in ast.walk(public) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant)}
    models = sources()["Models.swift"]
    reader = models.split("static func cat(_ json")[1].split("static func cats(")[0]
    for key in ("catId", "name", "cover", "nameSource", "regionId", "coat", "gpa", "posts", "likes", "lastSeenAt", "firstSeenAt"):
        assert key in sent, key
        assert f'json["{key}"]' in reader, key
    # A number the server did not send is nil, never a zero.
    for key in ("posts", "likes"):
        assert f'number(json["{key}"])' in reader, key
    detail = models.split("static func catDetail")[1]
    for key in ("met", "bio", "photos", "encounters", "days", "firstDay", "lastDay"):
        assert f'"{key}"' in detail, key
    assert '"catOfTheDay": cat_of_the_day(listed, today)' in handler
    assert 'text(json["catOfTheDay"])' in models
    for key in ('"bio"', '"met": _met(user, cat_id)', '"photos"'):
        assert key in handler.split("def _get_cat(")[1].split("def _met(")[0], key


def test_which_cat_still_reads_the_cat_it_read():
    # Cat is widened with defaults, so "Which cat?" builds it as before and
    # stays as it is (issue 143).
    code = sources()
    cat = code["Models.swift"].split("struct Cat: Equatable, Identifiable {")[1].split("\n}\n")[0]
    for kept in ("let id: String", "let name: String?", "let cover: URL?"):
        assert kept in cat, kept
    widened = re.findall(r"^    var (\w+): [^=]+= nil$", cat, re.MULTILINE)
    assert set(widened) >= {"coverMedium", "nameSource", "regionId", "coat", "gpa", "posts", "likes", "lastSeenAt", "firstSeenAt"}
    which = code["ScanPages.swift"].split("struct WhichCatPage")[1].split("struct CatRow")[0]
    assert "world.backend.cats()" in which


def test_the_sorts_are_the_web_apps_in_its_order_with_its_words():
    gallery_js = (REPO / "web" / "social" / "gallery.js").read_text()
    sorts = re.findall(r"^  (\w+): ", gallery_js.split("export const SORTS = {")[1].split("};")[0], re.MULTILINE)
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    view = sources()["CatsView.swift"]
    assert f"case {', '.join(sorts)}" in view
    for sort in sorts:
        assert f'case .{sort}: "{words["gallery.sort." + sort]}"' in view, sort
    # GPA only when there are grades, first, as in the web app.
    assert "cats.contains { $0.gpa != nil } ? allCases : allCases.filter { $0 != .gpa }" in view


def test_the_cats_screens_use_the_web_apps_words():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    code = sources()
    gallery, page, models = code["CatsView.swift"], code["CatView.swift"], code["Models.swift"]
    for key in ("feed.cotd", "feed.search", "gallery.empty", "gallery.failed", "gallery.sort", "gallery.sortBy"):
        assert f'"{words[key]}"' in gallery, key
    assert '"No cat called “\\(words)”."' in gallery and words["gallery.noMatch"] == "No cat called “{search}”."
    assert f'static let noName = "{words["cat.noName"]}"' in models
    for key in ("cat.namedByVote", "cat.namedByAdmins", "cat.notNamed"):
        assert f'"{words[key]}"' in models, key
    for key in ("cat.lastSeen", "cat.recentPosts", "cat.gpa"):
        assert f'"{words[key]}"' in page, key
    assert words["cat.usuallyNear"] == "Usually near {place}" and '"Usually near \\(area)"' in page
    assert f'"{words["cat.met"]["one"]}"' in page
    assert words["cat.met"]["other"] == "You met this cat {count} times." and '"You met this cat \\(met.encounters) times."' in page
    for key in ("posts", "likes"):
        assert f'"{words["cat." + key]["one"]}" : "{words["cat." + key]["other"]}"' in page, key


def test_a_field_the_server_left_out_is_left_out_of_the_page():
    about = sources()["CatView.swift"].split("private struct CatAbout")[1]
    for shown in (
        # What named it: the poll's answer once read, else the cat's
        # (issue 146).
        "if let named = CatAbout.named(cat, poll: poll)",
        "guard let poll, let source = poll.nameSource else { return cat.named }",
        "if let area = cat.area",
        "if let coat = cat.coatName",
        "if let bio = detail.bio",
        "if let met = detail.met",
        "if let posts = cat.posts",
        "if let likes = cat.likes",
        "if let seen = cat.lastSeenAt",
        "if let first = cat.firstSeenAt",
        "if let gpa = cat.gpa",
    ):
        assert shown in about, shown
    # Nothing stands in for a missing number.
    assert '"—"' not in about and "?? 0" not in about


def test_the_stand_in_campus_has_what_the_pictures_need():
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    campus = stand_in.split("static let campus = [")[1].split("    ]\n")[0]
    assert campus.count("Cat(") == 3 and 'id: "c3", name: nil' in campus
    assert campus.count("regionId:") == 2 and campus.count("coat:") == 2
    detail = stand_in.split("func cat(id: String)")[1].split("func catPosts")[0]
    # The member met one cat, twice, and the unnamed one never.
    assert detail.count("Met(") == 1 and "Met(encounters: 2" in detail
    assert "return CatDetail(cat: cat, bio: nil, met: nil" in detail
    assert 'catOfTheDay: "c2"' in stand_in


def test_the_trail_marks_the_cats_and_never_which():
    code = sources()
    for mark in ("cats: opened a cat",):
        assert f'world.trail.mark("{mark}")' in code["CatView.swift"], mark
    assert 'world.trail.mark("cats: \\(list.cats.count) listed")' in code["CatsView.swift"]
    marks = re.findall(r"trail\.mark\((.*)\)", code["CatsView.swift"] + code["CatView.swift"] + code["FeedView.swift"])
    for mark in marks:
        for taken in re.findall(r"\\\((.*?)\)", mark):
            for who in ("catId", "id", "name", "search", "words"):
                assert who not in taken.replace("kind", ""), mark


# ------------------------------------------------------- Cats, the name poll


def test_the_poll_goes_by_the_routes_of_the_api():
    # docs/app-plan/04-api.md: GET and POST /cats/{catId}/names, PUT and
    # DELETE /cats/{catId}/vote, each answering the poll as it now is.
    # Named for the trail by kind, never by the address.
    live = sources()["Backend.swift"].split("final class StandInBackend")[0]
    assert 'call("GET", "/cats/\\(Auth.encode(catId))/names", as: "names")' in live
    assert 'call("POST", "/cats/\\(Auth.encode(catId))/names", body: ["name": name], as: "suggest")' in live
    assert 'call("PUT", "/cats/\\(Auth.encode(catId))/vote", body: ["nameKey": nameKey], as: "vote")' in live
    assert 'call("DELETE", "/cats/\\(Auth.encode(catId))/vote", as: "unvote")' in live
    protocol = live.split("protocol Backend {")[1].split("\n}\n")[0]
    for call in (
        "func names(catId: String) async throws -> Poll",
        "func suggest(catId: String, name: String) async throws -> Poll",
        "func vote(catId: String, nameKey: String) async throws -> Poll",
        "func unvote(catId: String) async throws -> Poll",
    ):
        assert call in protocol, call
    plan = (REPO / "docs" / "app-plan" / "04-api.md").read_text()
    for route in (
        "| `GET /cats/{catId}/names` |",
        "| `POST /cats/{catId}/names` |",
        "| `PUT /cats/{catId}/vote` |",
        "| `DELETE /cats/{catId}/vote` |",
    ):
        assert route in plan, route


def test_the_poll_is_read_field_by_field_as_the_server_writes_it():
    import ast

    handler = (REPO / "src" / "app" / "handler.py").read_text()
    tree = ast.parse(handler)
    view = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_names_view")
    sent = {k.value for n in ast.walk(view) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant)}
    reader = sources()["Models.swift"].split("static func poll(_ json")[1].split("static func page(")[0]
    for key in ("name", "nameSource", "options", "total", "locked"):
        assert key in sent, key
        assert f'json["{key}"]' in reader, key
    for key in ("nameKey", "name", "votes", "leading", "mine"):
        assert key in sent, key
        assert f'option["{key}"]' in reader, key
    # The member's own pending name is marked by the keyword `pending`.
    assert "pending=True" in handler.split("def _names_view")[1].split("def _get_names")[0]
    assert 'option["pending"]' in reader
    # A total the server did not send is nil, never a zero.
    assert 'total: number(json["total"])' in reader


def test_the_poll_uses_the_web_apps_words():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    poll = sources()["NamePoll.swift"].split("enum PollWords {")[1].split("\n}\n")[0]
    for key in (
        "title",
        "lead",
        "leading",
        "checking",
        "suggest",
        "suggestButton",
        "suggested",
        "notAccepted",
        "tryAgain",
        "slowDown",
    ):
        assert f"static let {key} = {json.dumps(words['poll.' + key])}" in poll, key
    assert words["poll.locked"] == "The people who look after the cats have set the name: {name}. The poll goes on."
    assert '"The people who look after the cats have set the name: \\(name). The poll goes on."' in poll
    assert words["poll.votes"] == {"one": "{count} vote", "other": "{count} votes"}
    assert 'count == 1 ? "1 vote" : "\\(count) votes"' in poll
    assert words["error.generic"] == "Something went wrong: {message}"
    assert '"Something went wrong: \\(message)"' in poll
    assert words["cat.namedByVoteOf"] == "Named by vote · {votes} of {total}"
    assert '"Named by vote · \\(leader.votes) of \\(total)"' in sources()["CatView.swift"]


def test_the_poll_says_each_refusal_in_the_web_apps_words_never_as_a_code():
    poll = sources()["NamePoll.swift"].split("final class PollModel")[1].split("struct NamePollSection")[0]
    send = poll.split("private func send(")[1].split("private func isUnvote")[0]
    # The web app's REFUSED in poll.js, word for word.
    refused = (REPO / "web" / "social" / "poll.js").read_text().split("export const REFUSED = {")[1].split("};")[0]
    for code, key in (("not_accepted", "notAccepted"), ("try_again", "tryAgain"), ("rate_limited", "slowDown")):
        assert f'{code}: "poll.{key}"' in refused, code
        assert f'"{code}"' in send and f"note = PollWords.{key}" in send, code
    # The poll changed: it is read again before the words are said.
    changed = send.split('case "try_again", "gone":')[1].split("case ")[0]
    assert changed.index("await read()") < changed.index("note = PollWords.tryAgain")
    # Nothing is drawn but the server's answer.
    assert "poll = now" in send and "moved(" not in poll


def test_the_terms_come_before_a_vote_or_a_suggestion_and_not_before_taking_one_back():
    poll = sources()["NamePoll.swift"].split("final class PollModel")[1].split("struct NamePollSection")[0]
    send = poll.split("private func send(")[1].split("private func isUnvote")[0]
    assert "if changed || !isUnvote(write) {" in send
    assert "guard try await session.termsFirst(changed: changed) else { return false }" in send
    # A refusal for the terms asks once more instead of showing the code.
    assert 'case "terms_required" where !changed:' in send
    # The stand-in refuses a vote and a suggestion without them, and asks
    # nothing to take a vote back, as the API (`_unvote`).
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    for call in ("func suggest(catId", "func vote(catId"):
        assert "try termsFirst()" in stand_in.split(call)[1].split("    func ")[0], call
    assert "termsFirst" not in stand_in.split("func unvote(catId")[1].split("    func ")[0]
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert "require_terms" not in handler.split("def _unvote(")[1].split("\ndef ")[0]


def test_the_poll_is_built_on_the_systems_own_controls():
    page = sources()["CatView.swift"]
    assert "NamePollSection(model: poll)" in page
    assert "PollModel(world: world, session: session, catId: catId)" in page
    poll = sources()["NamePoll.swift"]
    for control in ("GroupBox {", "TextField(PollWords.suggest", ".buttonStyle(.bordered)", ".buttonStyle(.plain)", ".alert("):
        assert control in poll, control
    assert "glass" not in poll.lower()
    # A total or a lock the server left out is left out.
    assert "if let total = poll.total {" in poll and "if let locked = poll.locked {" in poll
    # The field takes what the server takes: 24 characters as it counts.
    assert "ScanFlow.cut(now, to: ScanFlow.nameLimit)" in poll
    assert "NAME_MAX = 24" in (REPO / "src" / "common" / "polls.py").read_text()


def test_the_stand_in_poll_has_what_the_pictures_need():
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    polls = stand_in.split("private static let madeUpPolls")[1].split("    ]\n")[0]
    mitzi = polls.split('"c1": [')[1].split("],")[0]
    # Three options: one leads, one is the member's own name being checked.
    assert mitzi.count("Option(") == 3 and mitzi.count("pending: true") == 1
    assert 'Option(key: "mitzi", name: "Mitzi", votes: 5' in mitzi


def test_the_trail_marks_the_poll_and_never_a_name_a_key_or_a_cat():
    poll = sources()["NamePoll.swift"]
    for line in ('"poll: voted"', '"poll: vote taken back"', '"poll: suggested, \\(state)"'):
        assert line in poll, line
    assert 'world.trail.mark("poll: \\(write.kind) refused (\\(status))")' in poll
    marks = re.findall(r"trail\.mark\((.*)\)", poll)
    assert len(marks) == 2, marks
    for mark in marks:
        for taken in re.findall(r"\\\((.*?)\)", mark):
            for who in ("catId", "name", "key", "typed", "option"):
                assert who not in taken, mark
    # What a suggestion's line says of the answer: its state, never which.
    done = poll.split("private static func done(")[1].split("\n}\n")[0]
    assert "nameKey" not in done and ".name" not in done
    # The walk reads them back, with the made-up server's record.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert '["vote pilpel", "vote mitzi from pilpel", "unvote mitzi"]' in tests
    assert '["suggest Hummus, new"]' in tests
    assert 'naming.launchArguments = ["-uiTesting", "-look", look, "-termsRequired"]' in tests
    missing = (SWIFT / "README.md").read_text().split("## Not here yet")[1]
    assert "name poll" not in missing


# ------------------------------------------------------------- the profile


def test_the_profile_goes_by_the_routes_of_the_api():
    code = sources()
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    # docs/app-plan/04-api.md, the rows PATCH /me, PUT /me/username,
    # GET /me/posts and DELETE /me, word for word.
    assert 'call("PATCH", "/me", body: ["displayName": displayName], as: "rename")' in live
    assert 'call("PUT", "/me/username", body: ["username": username], as: "username")' in live
    assert 'call("GET", "/me/posts", as: "my posts")' in live
    assert 'call("DELETE", "/me", body: ["confirm": confirm], as: "delete account")' in live
    assert '(json["deleting"] as? Bool) == true' in live
    # What the app sends as `confirm` is the one word the server takes.
    assert code["Session.swift"].count('deleteAccount(confirm: "delete")') == 1
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    for route in (
        '("PATCH", r"^/api/v1/me$", _update_me, "user")',
        '("DELETE", r"^/api/v1/me$", _delete_me, "user")',
        '("PUT", r"^/api/v1/me/username$", _choose_username, "user")',
    ):
        assert route in handler, route
    assert "_my_posts" in handler and r"/api/v1/me/posts$" in handler
    assert 'if body.get("confirm") != "delete":' in handler and 'return {"deleting": True}' in handler
    api = (REPO / "docs" / "app-plan" / "04-api.md").read_text()
    for row in ("| `PATCH /me` |", "| `PUT /me/username` |", "| `GET /me/posts` |", "| `DELETE /me` |"):
        assert row in api, row


def test_the_account_and_a_post_are_read_as_the_server_writes_them():
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert '"namePending": bool(user.get("pendingName"))' in handler
    # Only its author is told a post waits for a new cat: its proposal.
    assert 'card["proposal"] = {' in handler and '"status": proposal["status"],' in handler
    assert '"status": "open",' in handler
    models = sources()["Models.swift"]
    assert 'namePending: (json["namePending"] as? Bool) ?? false' in models
    assert 'heldForNewCat: text((json["proposal"] as? [String: Any])?["status"]) == "open"' in models


def test_the_profile_uses_the_web_apps_words_and_the_plans_for_deleting():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    profile = sources()["ProfileView.swift"]
    for name, key in (
        ("name", "profile.name"),
        ("nameLabel", "profile.nameLabel"),
        ("namePlaceholder", "profile.namePlaceholder"),
        ("nameChecking", "profile.nameChecking"),
        ("nameLimit", "profile.nameLimit"),
        ("username", "profile.username"),
        ("usernameSaved", "profile.usernameSaved"),
        ("usernameTaken", "profile.usernameTaken"),
        ("usernameRule", "profile.usernameRule"),
        ("usernameLimit", "profile.usernameLimit"),
        ("myPosts", "home.myPosts"),
    ):
        assert f'static let {name} = "{words[key]}"' in profile, name
    # The web app has no deletion yet: the plan's sentence (D14), and that
    # the photos stay, with nothing that points to the person.
    decisions = (REPO / "docs" / "app-plan" / "DECISIONS.md").read_text()
    said = '"Your posts, badges, points and friends will be removed for\ngood."'
    assert said in decisions and "nothing left that points to the person" in decisions
    body = re.search(r'static let deleteBody = "([^"]+)"', profile)[1]
    assert body.startswith("Your posts, badges, points and friends will be removed for good. ")
    assert "cat photos you took stay" in body and "nothing left that points to you" in body
    mine = sources()["MyPostsView.swift"]
    assert f'static let none = "{words["home.noPosts"]}"' in mine
    assert f'static let failed = "{words["home.postsFailed"]}"' in mine
    # A post's state, as the web app says it.
    models = sources()["Models.swift"]
    for state in ("pending", "hidden", "removed"):
        assert f'case "{state}": return "{words["post.state." + state]}"' in models, state
    assert f'return "{words["post.waitingNewCat"]}"' in models
    # The sentence the sign-in screen says after.
    assert 'nonisolated static let deletedNote = "Your account is being deleted."' in sources()["Session.swift"]


def test_the_profile_says_each_refusal_in_the_web_apps_words_never_as_a_code():
    profile = sources()["ProfileView.swift"]
    words = profile.split("static func words(")[1].split("private func setNote")[0]
    # `said` in the web app's Profile, code for code.
    web = (REPO / "web" / "social" / "home.js").read_text().split("const said = {")[1].split("};")[0]
    for code, name in (
        ("rate_limited", "usernameLimit"),
        ("name_taken", "usernameTaken"),
        ("bad_username", "usernameRule"),
    ):
        assert f"{code}:" in web and f'case "{code}"' in words and f"ProfileWords.{name}" in words, code
    assert "ProfileWords.nameLimit" in words
    # A name refused is put back as it was; a username refused keeps what
    # was typed, under its reason.
    commit = profile.split("private func commit(")[1].split("private var noteShown")[0]
    assert "if field == .name && !saved {" in commit and "name = session.me?.displayName ?? now" in commit
    assert "username = " not in commit.split("sending = field")[1]


def test_a_field_finished_while_the_other_is_sent_waits_and_is_not_dropped():
    # The username finished while the name is on its way is sent once the
    # name is answered, against the account that answer left; the same
    # field again ("done", then leaving it) sends nothing more.
    profile = sources()["ProfileView.swift"]
    assert "@State private var waiting: ProfileModel.Field?" in profile
    commit = profile.split("private func commit(")[1].split("private var noteShown")[0]
    busy = commit.split("guard sending == nil else {")[1].split("return\n")[0]
    assert "if sending != field {" in busy and "waiting = field" in busy
    assert "let account = session.me ?? me" in commit
    answered = commit.split("let saved = await model.save(field, typed)")[1]
    assert "sending = nil" in answered
    assert answered.index("sending = nil") < answered.index("if let next = waiting {")
    assert "waiting = nil" in answered and "commit(next)" in answered


def test_the_name_and_the_username_ask_for_the_terms_and_deleting_does_not():
    profile = sources()["ProfileView.swift"]
    save = profile.split("func save(_ field: Field")[1].split("static func words(")[0]
    assert "guard try await session.termsFirst(changed: changed) else { return false }" in save
    assert 'if refusal?.code == "terms_required" && !changed {' in save
    delete = profile.split("func deleteAccount() async {")[1]
    assert "termsFirst" not in delete
    session = sources()["Session.swift"].split("func deleteAccount() async throws {")[1].split("private func endDeleted")[0]
    assert "termsFirst" not in session
    # The server: the name and the username need them, deleting does not.
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert "require_terms(user)" in handler.split("def _choose_username(")[1].split("\ndef ")[0]
    assert "require_terms(user)" in handler.split("def _update_me(")[1].split("\ndef ")[0]
    assert "require_terms" not in handler.split("def _delete_me(")[1].split("\ndef ")[0]
    # The stand-in refuses the two without them, as the API.
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    for call in ("func rename(", "func chooseUsername("):
        assert "try termsFirst()" in stand_in.split(call)[1].split("    func ")[0], call


def test_an_account_being_deleted_ends_the_session_with_its_own_sentence():
    code = sources()
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    gone = live.split('if status == 403 && (json["code"] as? String) == "gone" {')[1].split("}")[0]
    assert "auth.accountGone()" in gone and "Session.deletedNote" in gone
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert 'raise ApiError(403, "this account is being deleted", code="gone")' in handler
    session = code["Session.swift"]
    assert "world.gate.onGone = { [weak self] in" in session
    ended = session.split("private func endDeleted()")[1].split("\n    }\n")[0]
    for step in ("world.gate.signOut()", "world.outbox.dropEverything()", "phase = .signedOut(note: Session.deletedNote)"):
        assert step in ended, step
    assert "error.status == 403 && error.code == \"gone\"" in session
    # A screen says nothing of its own over it: the feed's test for an
    # ended sign-in counts the account going too.
    assert "return refusal.status == 401 || Session.isGone(refusal)" in code["FeedView.swift"]
    # The upload queue and the kept flow leave the phone.
    drop = code["Outbox.swift"].split("func dropEverything()")[1].split("\n    }\n")[0]
    for part in ("index = Index()", "flow = nil", "try? FileManager.default.removeItem(at: folder)"):
        assert part in drop, part
    assert "var onGone: (() -> Void)? { get set }" in code["Auth.swift"]


def test_my_posts_says_each_state_and_deletes_as_the_feed_does():
    mine = sources()["MyPostsView.swift"]
    for state in ("case .loading:", "case .failed(let why):", "case .loaded:", "model.posts.isEmpty"):
        assert state in mine, state
    assert 'Button("Try again")' in mine
    assert "FeedModel(world: world, session: session, source: .mine)" in mine
    assert "PostCard(post: post, world: world, model: model)" in mine
    assert ".postActions(model, world: world)" in mine
    feed = sources()["FeedView.swift"]
    assert "case .mine:\n            try await world.backend.myPosts()" in feed
    assert "if let words = post.stateWords {" in feed
    # The mark is one element read as its words: on a bare Label the
    # identifier reached the symbol, which answered "Clock".
    mark = feed.split("if let words = post.stateWords {")[1].split('.accessibilityIdentifier("post.state.')[0]
    assert ".accessibilityElement(children: .ignore)" in mark
    assert ".accessibilityLabel(words)" in mark
    # The stand-in's member has one public post and one being checked.
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    my_posts = stand_in.split("func myPosts()")[1].split("    func ")[0]
    assert 'state: "visible"' in my_posts and "madeUp.filter(\\.mine)" in my_posts
    made_up = stand_in.split("private var madeUp: [Post]")[1]
    assert made_up.count("mine: true") == 1 and 'state: "pending"' in made_up


def test_the_profile_is_built_on_the_systems_own_controls():
    profile = sources()["ProfileView.swift"]
    for control in ("List {", "TextField(ProfileWords.namePlaceholder", "TextField(ProfileWords.username", ".alert(ProfileWords.deleteTitle", "NavigationLink {"):
        assert control in profile, control
    assert "glass" not in profile.lower()
    # Delete account is last in the list, and destructive.
    rows = profile.split("List {")[1].split(".navigationTitle(")[0]
    assert re.sub(r"[\s}]+$", "", rows).endswith('.accessibilityIdentifier("profile.delete-account")')
    assert "Button(role: .destructive) {" in rows.split("profile.sign-out")[1]
    assert "struct ProfileView" not in sources()["RootView.swift"]


def test_the_trail_marks_the_profile_and_never_a_name_or_an_id():
    code = sources()
    profile, session = code["ProfileView.swift"], code["Session.swift"]
    for line in (
        'world.trail.mark("profile: \\(field.rawValue) saved")',
        'world.trail.mark("profile: \\(field.rawValue) refused (\\(why))")',
        'world.trail.mark("account: delete asked")',
        'world.trail.mark("account: delete cancelled")',
    ):
        assert line in profile, line
    assert 'world.trail.mark("account: deleting")' in session
    for mark in re.findall(r"trail\.mark\((.*)\)", profile):
        for taken in re.findall(r"\\\((.*?)\)", mark):
            assert taken in ("field.rawValue", "why", "status", "kb"), mark
    # The walk reads them back, with the made-up server's record.
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    for line in ('"profile: name saved"', '"profile: username refused (name_taken)"', '"account: delete asked"', '"account: deleting"'):
        assert line in tests, line


def test_the_walk_deletes_the_account_once_and_cancel_sends_nothing():
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    walk = tests.split("private func walk(")[1].split("\n    private func ")[0]
    # In the account's walk, in the launch that accepted the terms (#154).
    account = tests.split("private func account(")[1].split("\n    private func ")[0]
    assert "profile(naming, look: look)" in account
    assert "profile(" not in walk
    profile = tests.split("private func profile(")[1].split("\n    private func ")[0]
    assert profile.index('asked.buttons["Cancel"].firstMatch.tap()') < profile.index('asked.buttons["Delete account"].firstMatch.tap()')
    assert 'XCTAssertFalse(served(cancelled).contains { $0.hasPrefix("delete me") }' in profile
    assert '["delete me confirm delete"]' in profile
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    assert 'keep("delete me confirm \\(confirm)")' in stand_in
    # Each picture the issue asks for, in both looks.
    for name in ("profile-name-pending", "profile-username-taken", "my-posts", "delete-account", "signed-out-deleted"):
        assert f'keep(app, "{name}-\\(look)")' in profile, name
    assert 'keep(app, "profile-\\(look)")' in walk
    # Behind the system's dialog the screen is dimmed, as for the terms.
    assert 'name.hasPrefix("delete-account-")' in tests
    # The sentence is over XCUITest's 128 characters for an identifier:
    # it is found by its label.
    assert 'asked.staticTexts[sentence]' not in profile
    assert 'NSPredicate(format: "label == %@", sentence)' in profile
    # My posts is mostly photos; its light bar is lower, still far above dark.
    assert 'let photos = name.hasPrefix("my-posts-")' in tests


# ------------------------------------------------------- the profile photo


def test_the_profile_photo_is_made_with_the_web_apps_and_the_servers_numbers():
    # web/social/avatar.js and src/common/media.py: a square of 512 px at
    # most, a JPEG of 200,000 bytes at most, the quality stepped down the
    # same way, and the same segments refused.
    avatar = sources()["Avatar.swift"]
    web = (REPO / "web" / "social" / "avatar.js").read_text()
    media = (REPO / "src" / "common" / "media.py").read_text()
    side = re.search(r"const SIDE = (\d+);", web)[1]
    most = re.search(r"const MAX_BYTES = ([\d_]+);", web)[1]
    qualities = re.search(r"const QUALITIES = \[([^\]]+)\];", web)[1]
    smallest = re.search(r"side >= (\d+);", web)[1]
    assert f"static let side = {side}" in avatar and side == "512"
    assert f"static let maxBytes = {most}" in avatar and most == "200_000"
    assert f"AVATAR_MAX_BYTES = {most}" in media
    assert f"static let qualities: [Double] = [{qualities}]" in avatar
    assert f"static let smallest = {smallest}" in avatar
    assert 'static let type = "image/jpeg"' in avatar and 'AVATAR_TYPE = "image/jpeg"' in media
    assert 'canvas.toBlob(resolve, "image/jpeg", quality)' in web
    assert "UTType.jpeg.identifier" in avatar.split("private static func encode(")[1]
    markers = re.search(r"_METADATA_MARKERS = \{([^}]+)\}", media)[1]
    assert '0xE1: "EXIF or XMP", 0xED: "IPTC"' in markers
    assert 'static let metadata: [UInt8: String] = [0xE1: "EXIF or XMP", 0xED: "IPTC"]' in avatar
    # Cut to a centred square, turned upright, drawn anew, and checked the
    # way the server will check it before it is sent. Core Graphics and
    # ImageIO, no third-party code.
    assert "kCGImageSourceCreateThumbnailWithTransform: true" in avatar
    assert "image.cropping(to: CGRect(" in avatar and "(image.width - cut) / 2" in avatar
    assert "jpeg.count <= maxBytes, problem(jpeg) == nil" in avatar
    assert "edge = Int((Double(edge) * 0.75).rounded())" in avatar and "side = Math.round(side * 0.75)" in web
    imports = set(re.findall(r"^import (\w+)$", avatar, flags=re.MULTILINE))
    assert imports == {"CoreGraphics", "Foundation", "ImageIO", "UniformTypeIdentifiers"}, imports
    # The stand-in hands the screen a picture with made-up EXIF, TIFF and
    # GPS in it, larger than a profile photo and not square.
    drawn = sources()["Photos.swift"].split("static func cameraFile(")[1]
    for part in ("kCGImagePropertyExifDictionary", "kCGImagePropertyGPSDictionary", "kCGImagePropertyTIFFDictionary"):
        assert part in drawn, part
    assert "CGSize(width: 1200, height: 900)" in drawn


def test_the_profile_photo_goes_by_the_three_routes_and_removing_by_the_fourth():
    code = sources()
    live = code["Backend.swift"].split("final class StandInBackend")[0]
    # docs/app-plan/04-api.md, the three avatar rows, as web/social/data.js
    # calls them: the file last in the presigned POST.
    assert 'call("POST", "/me/avatar", body: [:], as: "avatar")' in live
    assert 'call("POST", "/me/avatar/\\(Auth.encode(avatarId))/complete", body: [:], as: "avatar complete")' in live
    assert 'call("DELETE", "/me/avatar", as: "remove avatar")' in live
    assert "LiveBackend.form(target.fields, data: jpeg, boundary: boundary)" in live
    upload = live.split("final class LiveBackend")[1].split("func uploadAvatar(")[1].split("func completeAvatar(")[0]
    assert "request.timeoutInterval = 20" in upload
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert '("POST", r"^/api/v1/me/avatar$", _start_avatar, "user")' in handler
    assert "/complete$\",\n        _complete_avatar," in handler
    assert '("DELETE", r"^/api/v1/me/avatar$", _remove_avatar, "user")' in handler
    assert 'return {"avatarId": avatar_id, "upload": upload}' in handler
    api = (REPO / "docs" / "app-plan" / "04-api.md").read_text()
    for row in ("| `POST /me/avatar` |", "| `POST /me/avatar/{avatarId}/complete` |", "| `DELETE /me/avatar` |"):
        assert row in api, row
    web = (REPO / "web" / "social" / "data.js").read_text()
    assert 'post("/v1/me/avatar")' in web and 'del("/v1/me/avatar")' in web
    # The account says a new photo waits to be checked.
    assert '"avatarPending": bool(user.get("pendingAvatarKey"))' in handler
    assert 'avatarPending: (json["avatarPending"] as? Bool) ?? false' in code["Models.swift"]
    # The three calls in order, then the account is the session's.
    send = code["ProfileView.swift"].split("func sendPhoto() async {")[1].split("static func photoWords(")[0]
    assert send.index("backend.startAvatar()") < send.index("backend.uploadAvatar(") < send.index("backend.completeAvatar(")
    assert send.index("backend.completeAvatar(") < send.index("session.update(now)")


def test_the_terms_come_before_a_photo_and_not_before_removing_one():
    code = sources()
    profile = code["ProfileView.swift"]
    send = profile.split("func sendPhoto() async {")[1].split("static func photoWords(")[0]
    assert send.index("session.termsFirst(changed: changed)") < send.index("backend.startAvatar()")
    assert 'if code == "terms_required" && !changed {' in send
    remove = profile.split("func removePhoto() async {")[1].split("/// \"Delete account\", confirmed.")[0]
    assert "termsFirst" not in remove
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    assert "require_terms(user)" in handler.split("def _start_avatar(")[1].split("\ndef ")[0]
    assert "require_terms" not in handler.split("def _remove_avatar(")[1].split("\ndef ")[0]
    stand_in = code["Backend.swift"].split("final class StandInBackend")[1]
    assert "try termsFirst()" in stand_in.split("func startAvatar(")[1].split("    func ")[0]
    assert "termsFirst" not in stand_in.split("func removeAvatar(")[1].split("    func ")[0]
    # Removing asks first, with the system's alert.
    assert ".alert(ProfileWords.photoRemoveTitle, isPresented: $removeAsked) {" in profile


def test_the_profile_photo_uses_the_web_apps_words_and_never_a_code():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    profile = sources()["ProfileView.swift"]
    for name, key in (
        ("photoChange", "profile.photoChange"),
        ("photoMenu", "profile.photoMenu"),
        ("photoRemove", "profile.photoRemove"),
        ("photoRemoved", "profile.photoRemoved"),
        ("photoChecking", "profile.photoChecking"),
        ("photoLimit", "profile.photoLimit"),
        ("photoBad", "profile.photoBad"),
    ):
        assert f'static let {name} = "{words[key]}"' in profile, name
    # The issue's words for the menu's one way to choose: there is no
    # camera here, so not the web app's "Choose from library".
    assert 'static let photoChoose = "Choose a photo"' in profile
    said = profile.split("static func photoWords(")[1].split("func removePhoto()")[0]
    assert 'case "bad_photo": ProfileWords.photoBad' in said
    assert 'case "rate_limited": ProfileWords.photoLimit' in said
    web = (REPO / "web" / "social" / "home.js").read_text().split("const photoPicked = ")[1].split("const removePhoto")[0]
    assert 'err.code === "rate_limited"' in web and 't("profile.photoBad")' in web
    # A picture the phone cannot open says so and sends nothing.
    choose = profile.split("func choosePhoto(_ file: Data?) async {")[1].split("func sendPhoto()")[0]
    unread = choose.split("guard let made else {")[1].split("}")[0]
    assert "photoNote = ProfileWords.photoBad" in unread and "return" in unread
    assert choose.index("guard let made else {") < choose.index("await sendPhoto()")
    # A failure to reach the server or storage keeps the picture for
    # "Try again"; a refusal for good does not.
    send = profile.split("func sendPhoto() async {")[1].split("static func photoWords(")[0]
    for_good = send.split('case "bad_photo", "rate_limited":')[1].split("default:")[0]
    assert "ready = nil" in for_good and "photoRetry" not in for_good
    assert "photoRetry = true" in send.split('case "bad_photo", "rate_limited":')[1].split("default:")[1]
    assert 'Button("Try again") {\n                    Task { await model.sendPhoto() }' in profile
    # Until the server takes the new one, the account (and its photo) is
    # not changed.
    assert send.count("session.update(") == 1


def test_the_profile_photo_is_the_systems_menu_and_picker():
    profile = sources()["ProfileView.swift"]
    menu = profile.split("private var photoMenu: some View {")[1].split("private var photoNotes")[0]
    assert "Menu {" in menu and "if me.avatar != nil {" in menu
    assert menu.index("ProfileWords.photoChoose") < menu.index("ProfileWords.photoRemove")
    assert '.accessibilityIdentifier("profile.photo")' in menu
    assert ".photosPicker(isPresented: $picking, selection: $picked, matching: .images)" in profile
    assert "item.loadTransferable(type: Data.self)" in profile
    # Under UI tests there is no picker to drive: a drawn picture instead.
    choose = profile.split("private func choose() {")[1].split("\n    }\n")[0]
    assert "if world.drawn {" in choose and "DrawnPhotos.cameraFile(" in choose and "picking = true" in choose


def test_the_trail_marks_the_profile_photo_and_never_a_file_an_id_or_a_place():
    profile = sources()["ProfileView.swift"]
    for line in (
        'world.trail.mark("avatar: chosen")',
        'world.trail.mark("avatar: made ready, \\(kb) KB")',
        'world.trail.mark("avatar: refused (\\(why))")',
        'world.trail.mark("avatar: removed")',
        'world.trail.mark("avatar: could not be read")',
    ):
        assert line in profile, line
    live = sources()["Backend.swift"].split("final class StandInBackend")[0]
    assert 'trail.mark("api: avatar upload \\(status) in' in live
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    for line in ('"avatar: chosen"', '"avatar: made ready, "', '"avatar: refused (bad_photo)"', '"avatar: removed"'):
        assert line in tests, line


def test_the_walk_chooses_a_photo_has_it_refused_and_removes_it():
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    profile = tests.split("private func profile(")[1].split("\n    private func ")[0]
    for name in ("profile-photo-pending", "profile-photo-menu", "profile-photo-refused", "profile-photo-removed"):
        assert f'keep(app, "{name}-\\(look)")' in profile, name
    assert profile.index("profile-photo-pending") < profile.index("profile-photo-menu") < profile.index("profile-photo-refused")
    assert profile.index("profile-photo-refused") < profile.index("profile-photo-removed") < profile.index("profile.delete-account")
    # The three calls in order, once each, from the stand-in's record; and
    # what storage was sent, read from its bytes.
    assert '"avatar start 1", "avatar upload 1", "avatar complete 1"' in profile
    assert '"avatar complete 2 bad_photo", "avatar remove"' in profile
    for check in ('words[3], "jpeg"', "200_000", "sides.first, sides.last", "512", 'words[8], "none"'):
        assert check in profile, check
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    upload = stand_in.split("func uploadAvatar(")[1].split("    func ")[0]
    assert 'keep("avatar upload \\(number) \\(kind) \\(jpeg.count) bytes \\(size) metadata \\(metadata)")' in upload
    assert "Avatar.problem(jpeg) == nil" in upload and "Avatar.pixels(jpeg)" in upload
    # The open menu dims the screen behind it, as a dialog does.
    assert 'name.hasPrefix("profile-photo-menu-")' in tests


# ------------------------------------------------------------- friends


def test_friends_go_by_the_routes_of_the_api():
    live = sources()["Backend.swift"].split("final class StandInBackend")[0]
    # docs/app-plan/04-api.md, the rows for /friends, /users/{userId},
    # /users/{userId}/posts and /blocks, word for word.
    for call in (
        'call("GET", "/friends?period=\\(period.rawValue)", as: "friends")',
        'call("GET", "/users/\\(Auth.encode(userId))", as: "person")',
        'call("GET", "/users/\\(Auth.encode(userId))/posts", cursor: cursor, as: "person posts")',
        'call("DELETE", "/friends/\\(Auth.encode(userId))", as: "remove friend")',
        'call("PUT", "/blocks/\\(Auth.encode(userId))", as: "block")',
    ):
        assert call in live, call
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    for route in (
        '("GET", r"^/api/v1/friends$", _get_friends, "user")',
        '("PUT", rf"^/api/v1/blocks/(?P<user_id>{ID})$", _block, "user")',
        '("DELETE", rf"^/api/v1/friends/(?P<user_id>{ID})$", _remove_friend, "user")',
        '("GET", rf"^/api/v1/users/(?P<user_id>{ID})$", _get_user, "user")',
        '("GET", rf"^/api/v1/users/(?P<user_id>{ID})/posts$", _user_posts, "user")',
    ):
        assert route in handler, route
    assert 'PERIODS = ("month", "all")' in handler
    api = (REPO / "docs" / "app-plan" / "04-api.md").read_text()
    for row in (
        "| `GET /friends?period=month\\|all` |",
        "| `GET /users/{userId}` |",
        "| `GET /users/{userId}/posts` |",
        "| `DELETE /friends/{userId}` |",
        "| `PUT /blocks/{userId}`,",
    ):
        assert row in api, row
    # A person's posts are a list of posts like the feed's.
    feed = sources()["FeedView.swift"]
    assert "case .person(let id):\n            try await world.backend.personPosts(userId: id, cursor: cursor)" in feed


def test_a_person_is_read_field_by_field_as_the_server_writes_them():
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    person = handler.split("def person(profile, friendship, me):")[1].split("\ndef ")[0]
    for key in ('"userId"', '"username"', '"displayName"', '"avatar"', '"friend": "yes" if friendship else "no"', '"friendSince"', '"me"'):
        assert key in person, key
    assert 'row["found"] = ' in handler and '"mutual": mutual,' in handler
    assert 'return {"period": period, "people": people, "requests": 0}' in handler
    models = sources()["Models.swift"]
    for read in (
        'json["people"] as? [[String: Any]]',
        'found: int(row["found"])',
        'me: (row["me"] as? Bool) ?? false',
        'json["person"] as? [String: Any]',
        'friend: text(body["friend"]) == "yes"',
        'friendSince: date(body["friendSince"])',
        'mutual: number(body["mutual"])',
    ):
        assert read in models, read
    # A name to show: the display name, or the username (the web app's
    # `displayName || username`).
    assert 'displayName.isEmpty ? (username ?? "") : displayName' in models
    assert "person.displayName || person.username" in (REPO / "web" / "social" / "friends.js").read_text()


def test_friends_use_the_web_apps_words():
    words = json.loads((REPO / "web" / "i18n" / "en.json").read_text())
    friends = sources()["FriendsView.swift"]
    for name, key in (
        ("title", "home.friends"),
        ("you", "home.you"),
        ("period", "friends.period"),
        ("month", "friends.period.month"),
        ("allTime", "friends.period.all"),
        ("catsOne", ("friends.cats", "one")),
        ("catsOther", ("friends.cats", "other")),
        ("foundOne", ("home.found", "one")),
        ("foundOther", ("home.found", "other")),
        ("search", "friends.search"),
        ("all", "friends.all"),
        ("countOne", ("friends.count", "one")),
        ("countOther", ("friends.count", "other")),
        ("noMatch", "friends.noMatch"),
        ("empty", "friends.empty"),
        ("failed", "friends.failed"),
        ("optionsFor", "friends.optionsFor"),
        ("remove", "friends.remove"),
        ("removeTitle", "friends.removeTitle"),
        ("removeBody", "friends.removeBody"),
        ("removeButton", "friends.removeButton"),
        ("block", "block.block"),
        ("blockTitle", "block.title"),
        ("blockBody", "block.body"),
        ("blockButton", "block.button"),
        ("report", "report.report"),
        ("generic", "error.generic"),
        ("personFoundOne", ("person.found", "one")),
        ("personFoundOther", ("person.found", "other")),
        ("friendsSince", "person.friendsSince"),
        ("mutualOne", ("person.mutual", "one")),
        ("mutualOther", ("person.mutual", "other")),
        ("thisIsYou", "person.you"),
        ("posts", "person.posts"),
        ("noPosts", "person.noPosts"),
        ("gone", "person.gone"),
    ):
        said = words[key[0]][key[1]] if isinstance(key, tuple) else words[key]
        assert f'static let {name} = "{said}"' in friends, name
    # The report sheet's title for a person is the web app's `report.title`.
    report = sources()["ReportView.swift"]
    assert words["report.title"] == "Report {name}"
    assert 'title = "Report \\(person.shownName)"' in report


def test_friends_are_built_on_the_systems_own_controls():
    code = sources()
    friends, person = code["FriendsView.swift"], code["PersonView.swift"]
    for control in ("List {", ".pickerStyle(.segmented)", ".searchable(", "Menu {", ".navigationDestination(item: $opened)"):
        assert control in friends, control
    # The confirmations are the system's alerts, with the web app's words.
    assert ".alert(\n                FriendsWords.fill(FriendsWords.removeTitle" in friends
    assert ".alert(\n                FriendsWords.fill(FriendsWords.blockTitle" in friends
    assert "Button(FriendsWords.removeButton, role: .destructive)" in friends
    assert "Button(FriendsWords.blockButton, role: .destructive)" in friends
    # Each menu: Remove, Block, then Report, last and red; on a person's
    # page Remove only while they are friends.
    for menu in (friends.split("Menu {")[1].split("} label:")[0], person.split("Menu {")[1].split("} label:")[0]):
        assert menu.index("FriendsWords.remove") < menu.index("FriendsWords.block") < menu.index("FriendsWords.report")
        assert 'Button(FriendsWords.report, systemImage: "flag", role: .destructive)' in menu
    assert "if detail.friend {" in person.split("Menu {")[1].split("FriendsWords.block")[0]
    # Report is the app's own sheet, with a person as its target.
    assert "ReportView(person: person, world: world)" in friends
    report = code["ReportView.swift"]
    assert 'targetType = "user"' in report and "targetId = person.userId" in report
    assert "PostCard(post: post, world: world, model: posts)" in person
    assert "glass" not in friends.lower().replace(".glassprominent", "")
    # Profile has the row.
    assert "FriendsView(world: world, session: session)" in code["ProfileView.swift"]
    assert '.accessibilityIdentifier("row.friends")' in code["ProfileView.swift"]


def test_removing_and_blocking_take_a_person_off_at_once_and_ask_no_terms():
    code = sources()
    friends = code["FriendsView.swift"]
    model = friends.split("final class FriendsModel")[1].split("\nenum People")[0]
    for action in ("func remove(_ person: Person) async {", "func block(_ person: Person) async {"):
        body = model.split(action)[1].split("\n    }\n")[0]
        # Off the list before the call; back where it was if it fails.
        assert body.index("takeOut(person)") < body.index("try await world.backend.")
        assert "putBack(row, at: index)" in body.split("} catch {")[1]
        assert "termsFirst" not in body
    # A block takes their posts off the lists of posts on screen.
    assert "People.post(person.userId, .blocked)" in model
    feed = code["FeedView.swift"]
    assert "NotificationCenter.default.publisher(for: People.changed)" in feed
    assert "change.kind == .blocked" in feed and "model.keepApart(change.userId)" in feed
    # The server needs no terms for either.
    handler = (REPO / "src" / "app" / "handler.py").read_text()
    for name in ("def _remove_friend(", "def _block("):
        assert "require_terms" not in handler.split(name)[1].split("\ndef ")[0], name
    # The stand-in plays both, and the feed leaves the blocked out.
    stand_in = code["Backend.swift"].split("final class StandInBackend")[1]
    assert 'kept.append("unfriend \\(userId)")' in stand_in and 'kept.append("block \\(userId)")' in stand_in
    assert 'keep("report user \\(report.targetId) \\(report.reason.rawValue)")' in stand_in
    assert "!apart.contains($0.author.userId)" in stand_in.split("func feed(cursor:")[1].split("    func ")[0]


def test_the_trail_marks_friends_and_never_a_name_a_username_or_an_id():
    code = sources()
    friends, person, report = code["FriendsView.swift"], code["PersonView.swift"], code["ReportView.swift"]
    assert 'world.trail.mark("friends: \\(answer.count) people (\\(period.rawValue))")' in friends
    for line in ('"friends: removed"', '"block: sent"'):
        assert f"world.trail.mark({line})" in friends and f"world.trail.mark({line})" in person
    assert 'world.trail.mark("person: opened")' in person
    assert 'world.trail.mark("report: sent (\\(targetType))")' in report
    for text in (friends, person):
        for mark in re.findall(r"trail\.mark\((.*)\)", text):
            for taken in re.findall(r"\\\((.*?)\)", mark):
                assert taken in ("answer.count", "period.rawValue", "(error as? ApiError", "(error as? ApiError)?.status ?? 0"), mark


def test_the_friends_walk_is_a_launch_of_its_own_in_both_looks():
    tests = (SWIFT / "BGUCatsUITests" / "ScreensUITests.swift").read_text()
    assert 'func testFriendsInLight() {\n        friends(look: "light")' in tests
    assert 'func testFriendsInDark() {\n        friends(look: "dark")' in tests
    walk = tests.split("private func friends(look: String) {")[1].split("\n    private func ")[0]
    assert 'app.launchArguments = ["-uiTesting", "-look", look]' in walk
    # Each picture the issue asks for, in both looks.
    for name in ("friends", "friends-all-time", "friends-search-none", "friends-menu", "friends-remove", "person", "person-gone"):
        assert f'keep(app, "{name}-\\(look)")' in walk, name
    # Cancel first, then the call, each once, from the stand-in's record.
    assert walk.index('removing.buttons["Cancel"]') < walk.index('removing.buttons["Remove"]')
    assert walk.index('blocking.buttons["Cancel"]') < walk.index('blocking.buttons["Block"]')
    for record in ('["unfriend u-c"]', '["block u-b"]', '["report user u-a harassment"]'):
        assert record in walk, record
    # The menus and the confirmation dim the screen, as a dialog does.
    assert 'name.hasPrefix("friends-menu-")' in tests and 'name.hasPrefix("friends-remove-")' in tests
    # The made-up friends have no real names.
    stand_in = sources()["Backend.swift"].split("final class StandInBackend")[1]
    friends = stand_in.split("private static let madeUpFriends = [")[1].split("]\n")[0]
    assert re.findall(r'displayName: "(\w+ Tester)"', friends) == ["First Tester", "Second Tester", "Third Tester", "Fourth Tester"]
