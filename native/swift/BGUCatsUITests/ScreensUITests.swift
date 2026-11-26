import UIKit
import XCTest

/// Opens every screen in a simulator and keeps a picture of each, in light
/// and in dark: the same job tests/web does for the web app. Swift cannot be
/// compiled on Linux, so this run on a Mac is how anyone, an agent or a
/// person, sees a screen before it is merged.
///
/// The app is started with `-uiTesting`: it reads nothing from the network
/// and keeps nothing on the phone, its member and its posts are made up,
/// and its clock stands still, so two pictures of one screen are the same
/// picture. `-signedOut` starts it with nobody signed in; `-termsRequired`
/// with the terms not accepted, `-termsChanged` with terms that changed
/// after the account was read. `-look` names the look
/// to draw, and every picture is checked to be that look: on this job's
/// first run all ten came out light and nothing noticed.
final class ScreensUITests: XCTestCase {
    /// How long the walk waits for something it expects. It is the time
    /// after which the answer is "never", not "slowly": a wait that is met
    /// costs nothing, and the first walk runs on a simulator still busy
    /// starting up. There one question to it ("is the deleted post still
    /// there?") took nine seconds, a wait of ten gave up, and the next
    /// look showed the post gone (2026-11-24). The one short wait left is
    /// for something that must not come.
    private let patience: TimeInterval = 30

    override func setUp() {
        continueAfterFailure = false
    }

    func testEveryScreenInLight() {
        walk(look: "light")
    }

    func testEveryScreenInDark() {
        walk(look: "dark")
    }

    private func walk(look: String) {
        // Nobody signed in: the sign-in screen, with its one button. The
        // sheet behind it is Google's and is not opened here.
        let signedOut = XCUIApplication()
        signedOut.launchArguments = ["-uiTesting", "-look", look, "-signedOut"]
        signedOut.launch()
        let google = signedOut.descendants(matching: .any)["sign-in.google"].firstMatch
        XCTAssertTrue(google.waitForExistence(timeout: patience), "With nobody signed in, the app did not show the sign-in screen.")
        XCTAssertTrue(signedOut.buttons["App info"].exists, "The sign-in screen has no way to App info.")
        keep(signedOut, "sign-in-\(look)")
        signedOut.terminate()

        // A sign-in that ends while the app is open (the server refuses
        // the token): the sign-in screen comes up and says why, instead of
        // a feed whose every tap fails.
        let ending = XCUIApplication()
        ending.launchArguments = ["-uiTesting", "-look", look, "-signInEnds"]
        ending.launch()
        let heart = ending.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(heart.waitForExistence(timeout: patience), "The feed did not show its first post. \(onScreen(ending))")
        heart.tap()
        let again = ending.descendants(matching: .any)["sign-in.google"].firstMatch
        XCTAssertTrue(again.waitForExistence(timeout: patience), "The sign-in ended and the sign-in screen did not come up. \(onScreen(ending))")
        XCTAssertTrue(ending.staticTexts["Your sign-in ended. Sign in again."].exists, "The sign-in screen does not say why it is there. \(onScreen(ending))")
        keep(ending, "sign-in-ended-\(look)")
        ending.terminate()

        // The terms not accepted yet: the first like asks for them, in the
        // system's dialog over the feed, before anything is sent.
        let asking = XCUIApplication()
        asking.launchArguments = ["-uiTesting", "-look", look, "-termsRequired"]
        asking.launch()
        let mitzi = asking.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(mitzi.waitForExistence(timeout: patience), "The feed did not show its first post. \(onScreen(asking))")
        XCTAssertEqual(mitzi.label, "Like, 3")
        mitzi.tap()
        let terms = asking.alerts["Before you post"]
        XCTAssertTrue(terms.waitForExistence(timeout: patience), "A like before the terms did not ask for them. \(onScreen(asking))")
        XCTAssertTrue(terms.buttons["Accept and go on"].exists, "The terms' dialog has no way to accept. \(onScreen(asking))")
        keep(asking, "terms-\(look)")

        // "Cancel": nothing is sent, and the like is not counted. The
        // first match: iOS 26 reports a dialog's button twice, a button
        // inside a button with the same name, and a tap that wants exactly
        // one refuses both (2026-11-24, the first time this ran on a Mac).
        terms.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(gone(terms), "The terms' dialog stayed after Cancel.")
        XCTAssertEqual(mitzi.value as? String, "not liked", "A declined like was counted.")
        XCTAssertEqual(mitzi.label, "Like, 3", "A declined like changed the count.")

        // Asked again at the next like; accepting lets the like through.
        mitzi.tap()
        XCTAssertTrue(terms.waitForExistence(timeout: patience), "The next like did not ask for the terms again. \(onScreen(asking))")
        terms.buttons["Accept and go on"].firstMatch.tap()
        let counted = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [counted], timeout: patience), .completed, "After accepting the terms the like was not counted. \(onScreen(asking))")
        XCTAssertEqual(mitzi.value as? String, "liked")

        // Accepted once: taking the like back and liking again asks nothing.
        mitzi.tap()
        let undone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 3"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [undone], timeout: patience), .completed, "Taking the like back did not count. \(onScreen(asking))")
        mitzi.tap()
        XCTAssertFalse(asking.alerts.firstMatch.waitForExistence(timeout: 2), "A like after the terms were accepted asked again. \(onScreen(asking))")
        let recounted = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: mitzi)
        XCTAssertEqual(XCTWaiter().wait(for: [recounted], timeout: patience), .completed, "The second like was not counted. \(onScreen(asking))")

        // The trail says what was asked and answered, never who.
        asking.tabBars.buttons["Profile"].tap()
        let info = asking.descendants(matching: .any)["row.app-info"].firstMatch
        XCTAssertTrue(info.waitForExistence(timeout: patience), "Profile has no App info row.")
        info.tap()
        let told = asking.descendants(matching: .any)["app-info.text"].firstMatch
        XCTAssertTrue(told.waitForExistence(timeout: patience), "App info did not open.")
        let lines = told.label + "\n" + (told.value as? String ?? "")
        for line in ["terms: asked", "terms: declined", "terms: accepted"] {
            XCTAssertTrue(lines.contains(line), "App info did not keep \"\(line)\".")
        }
        asking.terminate()

        // The terms changed after the account was read: the server refuses
        // the like, and the app asks once more instead of showing its word.
        let changed = XCUIApplication()
        changed.launchArguments = ["-uiTesting", "-look", look, "-termsChanged"]
        changed.launch()
        let late = changed.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(late.waitForExistence(timeout: patience), "The feed did not show its first post. \(onScreen(changed))")
        late.tap()
        let asked = changed.alerts["Before you post"]
        XCTAssertTrue(asked.waitForExistence(timeout: patience), "A like refused for the terms did not ask for them. \(onScreen(changed))")
        asked.buttons["Accept and go on"].firstMatch.tap()
        let through = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: late)
        XCTAssertEqual(XCTWaiter().wait(for: [through], timeout: patience), .completed, "After accepting the changed terms the like was not counted. \(onScreen(changed))")
        XCTAssertFalse(changed.alerts["That did not work"].exists, "The server's refusal was shown. \(onScreen(changed))")
        changed.terminate()

        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting", "-look", look]
        app.launch()

        // Signed in, it opens on Home: the feed.
        XCTAssertTrue(app.navigationBars["Home"].waitForExistence(timeout: patience), "The app did not open on Home.")
        let first = app.descendants(matching: .any)["like.p1"].firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: patience), "The feed did not show its first post. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["By the library steps again, asleep in the sun."].exists, "The first post's words are not on screen. \(onScreen(app))")
        keep(app, "home-\(look)")

        // A like counts at once and stays.
        XCTAssertEqual(first.value as? String, "not liked")
        first.tap()
        let liked = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "liked"), object: first)
        XCTAssertEqual(XCTWaiter().wait(for: [liked], timeout: patience), .completed, "Tapping the heart did not like the post.")
        keep(app, "home-liked-\(look)")

        // A post's menu. On the member's own post (the second): Delete,
        // with the system's confirmation; the card leaves the feed.
        let own = app.descendants(matching: .any)["menu.p2"].firstMatch
        reveal(own, in: app)
        own.tap()
        let delete = app.buttons["Delete post"].firstMatch
        XCTAssertTrue(delete.waitForExistence(timeout: patience), "The menu on one's own post has no Delete. \(onScreen(app))")
        XCTAssertFalse(app.buttons["Report"].exists, "The menu on one's own post offers Report. \(onScreen(app))")
        keep(app, "post-menu-own-\(look)")
        delete.tap()
        let confirm = app.alerts.buttons["Delete"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: patience), "Delete did not ask first. \(onScreen(app))")
        confirm.tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: own)
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: patience), .completed, "The deleted post is still in the feed. \(onScreen(app))")
        // Two cards are left: the first and the third.
        reveal(app.descendants(matching: .any)["menu.p1"].firstMatch, in: app)
        let other = app.descendants(matching: .any)["menu.p3"].firstMatch
        reveal(other, in: app)
        XCTAssertFalse(app.descendants(matching: .any)["like.p2"].firstMatch.exists, "The deleted post came back. \(onScreen(app))")

        // On anyone else's: Report, a sheet with the six reasons, and thanks.
        other.tap()
        let report = app.buttons["Report"].firstMatch
        XCTAssertTrue(report.waitForExistence(timeout: patience), "The menu on another's post has no Report. \(onScreen(app))")
        XCTAssertFalse(app.buttons["Delete post"].exists, "The menu on another's post offers Delete. \(onScreen(app))")
        keep(app, "post-menu-other-\(look)")
        report.tap()
        for reason in ["spam", "offensive", "harassment", "privacy", "not_cat", "other"] {
            let row = app.descendants(matching: .any)["reason.\(reason)"].firstMatch
            XCTAssertTrue(row.waitForExistence(timeout: patience), "The report sheet has no reason \(reason). \(onScreen(app))")
        }
        // The button itself, asked for as a button. Asked for as "any
        // element", the first to answer was something around it in the
        // bar, which is always enabled: the walk said a report could be
        // sent with no reason, on a sheet whose button was greyed out
        // (#126 merged with that failing, 2026-11-24).
        let send = app.buttons["report.send"].firstMatch
        XCTAssertTrue(send.waitForExistence(timeout: patience), "The report sheet has no Send. \(onScreen(app))")
        keep(app, "report-\(look)")
        XCTAssertFalse(send.isEnabled, "A report can be sent with no reason. \(onScreen(app))")
        app.descendants(matching: .any)["reason.spam"].firstMatch.tap()
        XCTAssertTrue(send.isEnabled, "Choosing a reason did not let the report go.")
        send.tap()
        let thanks = app.descendants(matching: .any)["report.thanks"].firstMatch
        XCTAssertTrue(thanks.waitForExistence(timeout: patience), "Sending a report did not say thank you. \(onScreen(app))")
        app.descendants(matching: .any)["report.done"].firstMatch.tap()
        XCTAssertTrue(thanks.waitForNonExistence(timeout: patience), "Done did not close the report. \(onScreen(app))")

        // Scan a cat has its own walk below.
        for (tab, name) in [("Cats", "cats"), ("Profile", "profile")] {
            app.tabBars.buttons[tab].tap()
            XCTAssertTrue(app.navigationBars[tab].waitForExistence(timeout: patience), "The tab \(tab) did not open.")
            keep(app, "\(name)-\(look)")
        }

        // Profile says who is signed in.
        XCTAssertTrue(app.staticTexts["Test Member"].exists || app.descendants(matching: .any)["profile.me"].firstMatch.exists, "Profile does not say who is signed in.")
        XCTAssertTrue(app.descendants(matching: .any)["profile.sign-out"].firstMatch.exists, "Profile has no way to sign out.")

        // Profile, then "App info".
        let row = app.descendants(matching: .any)["row.app-info"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: patience), "Profile has no App info row.")
        row.tap()
        let text = app.descendants(matching: .any)["app-info.text"].firstMatch
        XCTAssertTrue(text.waitForExistence(timeout: patience), "App info did not open.")
        // Selectable text may be read out as a value, not a label.
        let shown = text.label + "\n" + (text.value as? String ?? "")
        XCTAssertTrue(shown.contains("kind: iPhone app (Swift)"), "App info does not say what kind of app this is.")
        XCTAssertTrue(shown.contains("start: ready"), "App info does not show what the app was doing.")
        XCTAssertTrue(shown.contains("tab: profile"), "App info did not keep the tab that was opened.")
        XCTAssertTrue(shown.contains("feed: 3 posts"), "App info did not keep that the feed was read.")
        XCTAssertTrue(shown.contains("post: deleted"), "App info did not keep that a post was deleted.")
        XCTAssertTrue(shown.contains("report: sent (spam)"), "App info did not keep that a report was sent.")
        XCTAssertFalse(shown.contains("p2") || shown.contains("p3"), "App info names a post.")
        keep(app, "app-info-\(look)")

        let copy = app.descendants(matching: .any)["app-info.copy"].firstMatch
        copy.tap()
        XCTAssertTrue(app.buttons["Copied"].waitForExistence(timeout: patience), "Copying did not say it copied.")

        app.terminate()
    }

    func testScanInLight() {
        scan(look: "light")
    }

    func testScanInDark() {
        scan(look: "dark")
    }

    /// Scan a cat: six photos, two of them from the gallery, sent as one
    /// encounter, with the second photo's upload failing once; then "Which
    /// cat?", the post, and the feed with the post first, the server
    /// answering `not_ready` to the first try. Then a second encounter, of
    /// a cat that isn't here: the new-cat form, "Add & post", and the feed
    /// with that post first. What the made-up server was asked is read back
    /// from App info.
    private func scan(look: String) {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting", "-look", look, "-uploadFailsOnce", "-postNotReadyOnce"]
        app.launch()
        openScan(app)
        let take = find(app, "scan.take")
        XCTAssertTrue(take.waitForExistence(timeout: patience), "Scan a cat has no way to take a photo. \(onScreen(app))")
        XCTAssertTrue(find(app, "scan.gallery").exists, "Scan a cat has no way to choose from the gallery. \(onScreen(app))")
        XCTAssertFalse(app.staticTexts["Not built yet"].exists, "Scan a cat still says it is not built.")
        keep(app, "scan-empty-\(look)")

        // Four from the (stand-in) camera, then two from the gallery.
        for taken in 1...4 {
            find(app, "scan.take").tap()
            expect(app, "scan.count", taken == 1 ? "1 photo" : "\(taken) photos")
        }
        find(app, "scan.gallery").tap()
        expect(app, "scan.count", "6 photos")
        XCTAssertEqual(app.staticTexts.matching(identifier: "scan.mark.gallery").count, 2, "The two gallery photos are not marked. \(onScreen(app))")
        keep(app, "scan-photos-\(look)")

        // One can be taken out before sending.
        find(app, "scan.take").tap()
        expect(app, "scan.count", "7 photos")
        find(app, "scan.remove.7").tap()
        expect(app, "scan.count", "6 photos")

        find(app, "scan.send").tap()
        // The second photo's upload fails once: the screen says so in
        // words, and the other five go on.
        let retrying = find(app, "scan.retrying")
        XCTAssertTrue(retrying.waitForExistence(timeout: patience), "A failed upload is not said on screen. \(onScreen(app))")
        // The other five are not held up: they are sent while the second
        // still waits for its retry. Said by the screen's own state, not
        // by a clock: a short wait failed on a busy simulator.
        expect(app, "scan.progress", "5 of 6 sent")
        XCTAssertTrue(retrying.exists, "Five were sent only once the second was retried: the others were held up. \(onScreen(app))")
        XCTAssertTrue(retrying.label.contains("took too long"), "The screen does not say why it is retrying: \(retrying.label)")
        keep(app, "scan-retrying-\(look)")

        expect(app, "scan.sent", "Sent: 6 photos")
        XCTAssertFalse(find(app, "scan.retrying").exists, "Sent, and still retrying. \(onScreen(app))")
        keep(app, "scan-sent-\(look)")

        // Which cat? The made-up campus's three cats, a search field, "Not
        // sure", and a cat that isn't here.
        find(app, "scan.which").tap()
        XCTAssertTrue(app.navigationBars["Which cat?"].waitForExistence(timeout: patience), "Which cat? did not open. \(onScreen(app))")
        for cat in ["c1", "c2", "c3"] {
            XCTAssertTrue(find(app, "cat.\(cat)").waitForExistence(timeout: patience), "Which cat? does not list cat \(cat). \(onScreen(app))")
        }
        XCTAssertTrue(app.searchFields.firstMatch.exists, "Which cat? has no search field. \(onScreen(app))")
        XCTAssertTrue(find(app, "which.unsure").exists, "Which cat? has no Not sure. \(onScreen(app))")
        let newCat = find(app, "which.new")
        XCTAssertTrue(newCat.exists, "Which cat? has no row for a cat that isn't here. \(onScreen(app))")
        XCTAssertFalse(newCat.label.contains("Not built yet"), "The new cat's row still says it is not built: \(newCat.label)")
        keep(app, "scan-which-cat-\(look)")

        // A cat: the post, with the six photos, a line typed, the switch on.
        find(app, "cat.c2").tap()
        let words = find(app, "post.text")
        XCTAssertTrue(words.waitForExistence(timeout: patience), "Choosing a cat did not open the post. \(onScreen(app))")
        XCTAssertEqual(find(app, "post.photos").label, "6 photos", "The post does not hold the six photos.")
        let region = app.switches["post.region"].firstMatch
        XCTAssertTrue(region.exists, "The post has no Add location. \(onScreen(app))")
        XCTAssertEqual(region.value as? String, "1", "Add location is not on by default.")
        words.tap()
        words.typeText("Asleep by the fountain.")
        keep(app, "scan-post-\(look)")
        app.buttons["post.send"].firstMatch.tap()
        expect(app, "scan.posted", "Posted")
        keep(app, "scan-posted-\(look)")

        // Home: the post first, once the server has it. The first try was
        // answered `not_ready`, and it went again with no tap.
        app.tabBars.buttons["Home"].tap()
        let mine = app.staticTexts["Asleep by the fountain."].firstMatch
        XCTAssertTrue(mine.waitForExistence(timeout: patience), "The post is not in the feed. \(onScreen(app))")
        let older = app.staticTexts["By the library steps again, asleep in the sun."].firstMatch
        XCTAssertTrue(!older.exists || mine.frame.minY < older.frame.minY, "The new post is not first. \(onScreen(app))")
        // Made a moment ago: "Just now", never "in 0s".
        let fresh = app.staticTexts.matching(NSPredicate(format: "label ENDSWITH %@", " · Just now")).firstMatch
        XCTAssertTrue(fresh.exists, "The new post does not say \"Just now\". \(onScreen(app))")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", " · in ")).firstMatch.exists, "A post's age is in the future. \(onScreen(app))")
        keep(app, "home-after-post-\(look)")

        // A second encounter, of a cat that isn't here: one photo, the
        // form with every kind of answer given, then "Add & post".
        app.tabBars.buttons["Scan a cat"].tap()
        let another = find(app, "scan.another")
        XCTAssertTrue(another.waitForExistence(timeout: patience), "Posted has no way to scan another cat. \(onScreen(app))")
        another.tap()
        XCTAssertTrue(find(app, "scan.take").waitForExistence(timeout: patience), "Scan another cat did not open an empty scan. \(onScreen(app))")
        find(app, "scan.take").tap()
        expect(app, "scan.count", "1 photo")
        find(app, "scan.send").tap()
        expect(app, "scan.sent", "Sent: 1 photo")
        find(app, "scan.which").tap()
        let notHere = find(app, "which.new")
        XCTAssertTrue(notHere.waitForExistence(timeout: patience), "Which cat? has no row for a cat that isn't here. \(onScreen(app))")
        notHere.tap()
        let nameIdea = find(app, "new.name")
        XCTAssertTrue(nameIdea.waitForExistence(timeout: patience), "A cat that isn't here did not open the new-cat form. \(onScreen(app))")
        XCTAssertTrue(app.navigationBars["New cat"].exists, "The form is not called New cat. \(onScreen(app))")
        XCTAssertEqual(find(app, "new.photos").label, "1 photo", "The form does not hold the encounter's photo.")
        nameIdea.tap()
        nameIdea.typeText("Hummus\n")
        choose(app, "new.coat", "Tabby")
        choose(app, "new.where", "Aranne Library")
        let friendly = find(app, "new.trait.friendly")
        reveal(friendly, in: app)
        friendly.tap()
        let traitChosen = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "chosen"), object: friendly)
        XCTAssertEqual(XCTWaiter().wait(for: [traitChosen], timeout: patience), .completed, "Tapping a trait did not choose it. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["An admin looks at every new cat before anyone else sees it."].exists, "The form does not say an admin looks first. \(onScreen(app))")
        XCTAssertTrue(find(app, "new.add").exists, "The form has no Just add. \(onScreen(app))")
        keep(app, "scan-new-cat-\(look)")

        // "Add & post": the post, naming the new cat by its name idea.
        app.buttons["new.post"].firstMatch.tap()
        let caption = find(app, "post.text")
        XCTAssertTrue(caption.waitForExistence(timeout: patience), "Add & post did not open the post. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["New cat: Hummus"].exists, "The post does not name the new cat. \(onScreen(app))")
        caption.tap()
        caption.typeText("A new face by the gym.")
        app.buttons["post.send"].firstMatch.tap()
        expect(app, "scan.posted", "Posted")
        keep(app, "scan-new-cat-posted-\(look)")

        app.tabBars.buttons["Home"].tap()
        let newest = app.staticTexts["A new face by the gym."].firstMatch
        XCTAssertTrue(newest.waitForExistence(timeout: patience), "The new cat's post is not in the feed. \(onScreen(app))")
        let before = app.staticTexts["Asleep by the fountain."].firstMatch
        XCTAssertTrue(!before.exists || newest.frame.minY < before.frame.minY, "The new cat's post is not first. \(onScreen(app))")
        keep(app, "home-after-new-cat-\(look)")

        let shown = appInfo(app)
        // The two encounters' calls, each from its own "encounter".
        let both = served(shown)
        let split = both.lastIndex(of: "encounter place") ?? both.count
        let record = Array(both[..<split])
        let second = Array(both[split...])
        XCTAssertEqual(record.first, "encounter place", "The encounter was not asked for first: \(record)")
        for photo in 1...6 {
            let media = record.firstIndex { $0.hasPrefix("media \(photo) ") }
            let upload = record.lastIndex(of: "upload \(photo)")
            let complete = record.firstIndex(of: "complete \(photo)")
            XCTAssertNotNil(media, "Photo \(photo) was never recorded: \(record)")
            XCTAssertNotNil(upload, "Photo \(photo) was never uploaded: \(record)")
            XCTAssertNotNil(complete, "Photo \(photo) was never confirmed: \(record)")
            if let media, let upload, let complete {
                XCTAssertTrue(0 < media && media < upload && upload < complete, "Photo \(photo) went out of order: \(record)")
            }
        }
        XCTAssertTrue(record.contains("upload 2 timed out"), "The made-up failure did not happen: \(record)")
        let started = record.filter { $0.hasPrefix("media ") }
        let gallery = started.filter { $0.contains(" gallery ") }
        XCTAssertEqual(gallery.count, 2, "Not two gallery photos: \(record)")
        XCTAssertTrue(gallery.allSatisfy { $0.hasSuffix(" no-place") }, "A gallery photo carried a place: \(record)")
        XCTAssertTrue(started.filter { $0.contains(" camera ") }.allSatisfy { $0.hasSuffix(" place") }, "A camera photo went without the place: \(record)")

        // The trail says each step by its kind and status, never an id.
        XCTAssertTrue(shown.contains("upload: media 200"), "The trail does not mark the uploads.")
        XCTAssertTrue(shown.contains("upload: retry, timed out"), "The trail does not mark the retry.")
        XCTAssertNil(shown.range(of: "[0-9A-HJKMNP-TV-Z]{26}", options: .regularExpression), "The trail holds an id.")

        // The pick, then the post: after the last photo's confirmation,
        // once each, with the cat chosen. The pick is what the server takes
        // from an app with no model: the one cat shown, nothing ranked.
        let lastComplete = record.lastIndex { $0.hasPrefix("complete ") } ?? -1
        let picks = record.indices.filter { record[$0].hasPrefix("pick ") }
        let notReady = record.indices.filter { record[$0] == "post not_ready" }
        let posts = record.indices.filter { record[$0].hasPrefix("post claim") || record[$0].hasPrefix("post no-claim") }
        XCTAssertEqual(picks.map { record[$0] }, ["pick c2 shown c2 ranked 0"], "Not one pick of the cat chosen: \(record)")
        XCTAssertEqual(notReady.count, 1, "The made-up not_ready did not happen once: \(record)")
        XCTAssertEqual(posts.count, 1, "Not one post: \(record)")
        if let pick = picks.first, let refused = notReady.first, let post = posts.first {
            XCTAssertTrue(lastComplete < pick && pick < refused && refused < post, "The pick and the post did not follow the photos: \(record)")
            let line = record[post]
            XCTAssertTrue(line.hasPrefix("post claim c2 photos ") && line.hasSuffix(" text region"), "The post is not the one written: \(line)")
            let numbers = line.dropFirst("post claim c2 photos ".count).dropLast(" text region".count).split(separator: " ")
            XCTAssertEqual(Set(numbers.map(String.init)), Set((1...6).map(String.init)), "The post does not hold every photo once: \(line)")
            XCTAssertEqual(numbers.count, 6, "The post does not hold every photo once: \(line)")
        }
        for line in ["scan: cat chosen", "upload: pick 200", "upload: post 425, not ready yet", "upload: post 201"] {
            XCTAssertTrue(shown.contains(line), "App info did not keep \"\(line)\".")
        }
        XCTAssertFalse(shown.contains("fountain") || shown.contains("Shachor"), "App info holds what was written or a cat's name.")

        // The new cat: its proposal after the photo's confirmation, once,
        // with the answers given; then the post, naming that proposal (the
        // stand-in takes a claim only of a proposal it has, for this
        // encounter); and no pick, since nothing was shown.
        XCTAssertGreaterThan(second.count, 0, "The second encounter asked the server nothing: \(both)")
        let confirmed = second.lastIndex { $0.hasPrefix("complete ") }
        let proposals = second.indices.filter { second[$0].hasPrefix("proposal ") }
        let named = second.indices.filter { second[$0].hasPrefix("post ") }
        XCTAssertEqual(proposals.map { second[$0] }, ["proposal 1 name coat tabby region library traits friendly"], "Not one proposal with the answers given: \(second)")
        XCTAssertEqual(named.map { second[$0] }, ["post proposal 1 photos 7 text region"], "Not one post naming the new cat: \(second)")
        if let confirmed, let proposal = proposals.first, let post = named.first {
            XCTAssertTrue(confirmed < proposal && proposal < post, "The proposal and the post did not follow the photo: \(second)")
        } else {
            XCTFail("The photo, the proposal or the post is missing: \(second)")
        }
        XCTAssertFalse(second.contains { $0.hasPrefix("pick") }, "A new cat sent a pick: \(second)")
        for line in ["scan: new cat", "upload: proposal 200", "scan: post queued, a new cat"] {
            XCTAssertTrue(shown.contains(line), "App info did not keep \"\(line)\".")
        }
        // The trail names no new cat, no place and nothing written.
        let trail = shown.components(separatedBy: "stand-in server:").first ?? shown
        for word in ["Hummus", "gym", "library", "Library", "tabby"] {
            XCTAssertFalse(trail.contains(word), "The trail holds \"\(word)\".")
        }
        XCTAssertFalse(shown.contains("Hummus"), "App info holds the name idea.")
        app.terminate()
    }

    /// Photos still waiting when the app is closed go at the next launch,
    /// with no tap on Send.
    func testPhotosLeftWaitingGoAtTheNextLaunch() {
        let first = XCUIApplication()
        first.launchArguments = ["-uiTesting", "-look", "light", "-offline"]
        first.launch()
        openScan(first)
        find(first, "scan.take").tap()
        expect(first, "scan.count", "1 photo")
        find(first, "scan.gallery").tap()
        expect(first, "scan.count", "3 photos")
        find(first, "scan.send").tap()
        XCTAssertTrue(find(first, "scan.retrying").waitForExistence(timeout: patience), "With no server, the screen does not say it will retry. \(onScreen(first))")
        // Not sure which cat: the post is made, with no claim and no pick,
        // and waits on the phone with the photos.
        find(first, "scan.which").tap()
        let unsure = find(first, "which.unsure")
        XCTAssertTrue(unsure.waitForExistence(timeout: patience), "Which cat? has no Not sure. \(onScreen(first))")
        unsure.tap()
        let post = first.buttons["post.send"].firstMatch
        XCTAssertTrue(post.waitForExistence(timeout: patience), "Not sure did not open the post. \(onScreen(first))")
        XCTAssertEqual(find(first, "post.photos").label, "3 photos", "The post does not hold the three photos.")
        post.tap()
        expect(first, "scan.posted", "Posted")
        first.terminate()

        let second = XCUIApplication()
        second.launchArguments = ["-uiTesting", "-look", "light", "-keepQueue"]
        second.launch()
        // Only looked at: nothing on the Scan screen is tapped. The flow
        // kept comes back on the page it was left on.
        openScan(second)
        expect(second, "scan.sent", "Sent: 3 photos")
        expect(second, "scan.posted", "Posted")
        let shown = appInfo(second)
        XCTAssertTrue(shown.contains("upload: 3 waiting from before"), "The second launch did not find the queue.")
        XCTAssertTrue(shown.contains("scan: kept flow back (posted)"), "The second launch did not find the flow.")
        let record = served(shown)
        XCTAssertEqual(record.first, "encounter place", "The encounter was not asked for first: \(record)")
        for photo in 1...3 {
            XCTAssertTrue(record.contains("complete \(photo)"), "Photo \(photo) was not sent at the next launch: \(record)")
        }
        // "Not sure": a post with no claim, after the photos, and no pick.
        let lastComplete = record.lastIndex { $0.hasPrefix("complete ") } ?? -1
        let posted = record.firstIndex { $0.hasPrefix("post no-claim photos ") }
        XCTAssertNotNil(posted, "Not sure made no post with no claim: \(record)")
        XCTAssertTrue((posted ?? -1) > lastComplete, "The post went before the photos: \(record)")
        XCTAssertFalse(record.contains { $0.hasPrefix("pick") }, "Not sure sent a pick: \(record)")
        second.terminate()

        // A flow kept that is not whole is dropped: the tab opens empty.
        // The one kept here reads as a flow, on the new-cat form, with a
        // coat the server does not take.
        let third = XCUIApplication()
        third.launchArguments = ["-uiTesting", "-look", "light", "-keepQueue", "-flowBroken"]
        third.launch()
        openScan(third)
        XCTAssertTrue(find(third, "scan.take").waitForExistence(timeout: patience), "A broken flow did not leave the tab empty. \(onScreen(third))")
        XCTAssertFalse(find(third, "scan.which").exists, "A broken flow was used. \(onScreen(third))")
        XCTAssertFalse(find(third, "new.name").exists, "A broken new-cat form was used. \(onScreen(third))")

        // A cat that isn't here, nothing said about it, and "Just add":
        // the proposal goes, and no post.
        find(third, "scan.take").tap()
        expect(third, "scan.count", "1 photo")
        find(third, "scan.send").tap()
        expect(third, "scan.sent", "Sent: 1 photo")
        find(third, "scan.which").tap()
        let notHere = find(third, "which.new")
        XCTAssertTrue(notHere.waitForExistence(timeout: patience), "Which cat? has no row for a cat that isn't here. \(onScreen(third))")
        notHere.tap()
        let justAdd = third.buttons["new.add"].firstMatch
        XCTAssertTrue(justAdd.waitForExistence(timeout: patience), "The new-cat form has no Just add. \(onScreen(third))")
        justAdd.tap()
        expect(third, "scan.added", "Added")
        expect(third, "scan.post-state", "Thanks! An admin will look at your new cat.")
        let told = appInfo(third)
        XCTAssertTrue(told.contains("scan: kept flow dropped, not whole"), "The trail does not say the flow was dropped.")
        XCTAssertTrue(told.contains("scan: new cat added, no post"), "The trail does not say the new cat was added.")
        let asked = served(told)
        let proposed = asked.firstIndex { $0.hasPrefix("proposal ") }
        XCTAssertEqual(asked.filter { $0.hasPrefix("proposal ") }, ["proposal 1 no-name coat none region none traits none"], "Not one proposal with nothing said: \(asked)")
        XCTAssertTrue((proposed ?? -1) > (asked.lastIndex { $0.hasPrefix("complete ") } ?? Int.max), "The proposal went before the photo: \(asked)")
        XCTAssertFalse(asked.contains { $0.hasPrefix("post") }, "Just add made a post: \(asked)")
        XCTAssertFalse(asked.contains { $0.hasPrefix("pick") }, "Just add sent a pick: \(asked)")
        third.terminate()
    }

    /// A menu's choice: the picker, then the item, found by its words.
    private func choose(_ app: XCUIApplication, _ id: String, _ item: String) {
        // The picker is a button; asked for as "any element", the first to
        // answer may be the row around it.
        let picker = app.buttons[id].firstMatch
        XCTAssertTrue(picker.waitForExistence(timeout: patience), "There is no \(id). \(onScreen(app))")
        picker.tap()
        let option = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", item)).firstMatch
        XCTAssertTrue(option.waitForExistence(timeout: patience), "The menu of \(id) has no \(item). \(onScreen(app))")
        option.tap()
    }

    private func openScan(_ app: XCUIApplication) {
        let tab = app.tabBars.buttons["Scan a cat"]
        XCTAssertTrue(tab.waitForExistence(timeout: patience), "The tabs did not open. \(onScreen(app))")
        tab.tap()
        XCTAssertTrue(app.navigationBars["Scan a cat"].waitForExistence(timeout: patience), "Scan a cat did not open.")
    }

    private func find(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    /// Waits for an element to say exactly `label`, with the walk's one
    /// patience.
    private func expect(_ app: XCUIApplication, _ id: String, _ label: String) {
        let element = find(app, id)
        let said = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", label), object: element)
        XCTAssertEqual(XCTWaiter().wait(for: [said], timeout: patience), .completed, "\(id) does not say \"\(label)\". \(onScreen(app))")
    }

    /// Profile, then App info: its whole text.
    private func appInfo(_ app: XCUIApplication) -> String {
        app.tabBars.buttons["Profile"].tap()
        let row = find(app, "row.app-info")
        XCTAssertTrue(row.waitForExistence(timeout: patience), "Profile has no App info row.")
        row.tap()
        let text = find(app, "app-info.text")
        XCTAssertTrue(text.waitForExistence(timeout: patience), "App info did not open.")
        return text.label + "\n" + (text.value as? String ?? "")
    }

    /// What the made-up server was asked, from App info, in order.
    private func served(_ shown: String) -> [String] {
        guard let part = shown.components(separatedBy: "stand-in server:\n").dropFirst().first else { return [] }
        // The label and the value may both hold the text: the first copy.
        return Array(part.components(separatedBy: "\n").prefix { !$0.isEmpty && !$0.hasPrefix("BGU Cats, app info") })
    }

    /// Scrolls the feed until the element can be tapped: down first, then
    /// back up if it went past.
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<6 where !(element.exists && element.isHittable) {
            app.swipeUp(velocity: .slow)
        }
        for _ in 0..<6 where !(element.exists && element.isHittable) {
            app.swipeDown(velocity: .slow)
        }
        XCTAssertTrue(element.exists && element.isHittable, "\(element) cannot be reached. \(onScreen(app))")
    }

    /// What is on screen, in one line, for a failure's message: nobody
    /// here can open the simulator, so the job's log is all there is.
    private func onScreen(_ app: XCUIApplication) -> String {
        let texts = app.staticTexts.allElementsBoundByIndex.prefix(20).map { $0.label }
        let buttons = app.buttons.allElementsBoundByIndex.prefix(20).map { "\($0.identifier)=\($0.label)" }
        return "On screen, texts: \(texts); buttons: \(buttons)"
    }

    /// The element is gone within a few seconds.
    private func gone(_ element: XCUIElement) -> Bool {
        let away = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: element)
        return XCTWaiter().wait(for: [away], timeout: patience) == .completed
    }

    private func keep(_ app: XCUIApplication, _ name: String) {
        let shot = app.screenshot()
        let picture = XCTAttachment(screenshot: shot)
        picture.name = name
        picture.lifetime = .keepAlways
        add(picture)
        // A picture named dark is dark, and one named light is light. Under
        // a system dialog iOS dims the screen behind it by about a fifth,
        // so a light one's bar is lowered by as much; still far above dark.
        let bright = ScreensUITests.brightness(shot.image)
        let light = name.hasPrefix("terms-") ? 0.52 : 0.65
        if name.hasSuffix("-dark") {
            XCTAssertLessThan(bright, 0.35, "\(name) is not dark: the screen's brightness is \(bright).")
        } else {
            XCTAssertGreaterThan(bright, light, "\(name) is not light: the screen's brightness is \(bright).")
        }
    }

    /// How bright a picture is as a whole, from 0 (black) to 1 (white):
    /// the picture drawn into a single pixel.
    private static func brightness(_ image: UIImage) -> Double {
        guard let source = image.cgImage else { return -1 }
        var pixel = [UInt8](repeating: 0, count: 4)
        pixel.withUnsafeMutableBytes { bytes in
            let context = CGContext(
                data: bytes.baseAddress,
                width: 1,
                height: 1,
                bitsPerComponent: 8,
                bytesPerRow: 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            )
            context?.interpolationQuality = .high
            context?.draw(source, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        }
        return (Double(pixel[0]) + Double(pixel[1]) + Double(pixel[2])) / (3 * 255)
    }
}
