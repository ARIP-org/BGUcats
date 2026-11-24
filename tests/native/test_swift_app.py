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
    assert code["FeedView.swift"].count("if FeedModel.signInEnded(error) { return }") == 3
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
    assert '[("Cats", "cats"), ("Scan a cat", "scan"), ("Profile", "profile")]' in tests
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
