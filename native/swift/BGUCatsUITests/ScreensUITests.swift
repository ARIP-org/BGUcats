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

    // A walk is a test of its own for each look, and it is cut by launch
    // of the app: a launch starts from nothing, so a part needs nothing
    // that an earlier one did. The walk was one test a look until it grew
    // past its time limit with every step passing (#150, 2026-11-27: eight
    // minutes on a slow Mac, the light one 462 seconds). A test that nears
    // half its limit on the Mac is split the same way.

    func testAccountInLight() {
        account(look: "light")
    }

    func testAccountInDark() {
        account(look: "dark")
    }

    func testEveryScreenInLight() {
        walk(look: "light")
    }

    func testEveryScreenInDark() {
        walk(look: "dark")
    }

    /// The account's own launches: nobody signed in, a sign-in that ends,
    /// and the terms, asked before a like, again when they changed, and
    /// before a name suggested on a cat's page. Each is a launch of its
    /// own, closed before the next.
    private func account(look: String) {
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

        // The terms not accepted yet, on a cat's page: a name suggested asks
        // for them first. "Cancel" sends nothing; accepting sends the name
        // as it was typed, and the poll the server answers shows it as the
        // member's, "Being checked".
        let naming = XCUIApplication()
        naming.launchArguments = ["-uiTesting", "-look", look, "-termsRequired"]
        naming.launch()
        let namingTab = naming.tabBars.buttons["Cats"]
        XCTAssertTrue(namingTab.waitForExistence(timeout: patience), "The tabs did not open. \(onScreen(naming))")
        namingTab.tap()
        let namingCat = find(naming, "gallery.c1")
        XCTAssertTrue(namingCat.waitForExistence(timeout: patience), "The gallery did not show its cats. \(onScreen(naming))")
        namingCat.tap()
        let nameField = find(naming, "poll.field")
        XCTAssertTrue(nameField.waitForExistence(timeout: patience), "Mitzi's page has no field to suggest a name. \(onScreen(naming))")
        reveal(nameField, in: naming)
        nameField.tap()
        nameField.typeText("Hummus")
        let suggestName = naming.buttons["poll.suggest"].firstMatch
        suggestName.tap()
        let askFirst = naming.alerts["Before you post"]
        XCTAssertTrue(askFirst.waitForExistence(timeout: patience), "A name suggested before the terms did not ask for them. \(onScreen(naming))")
        askFirst.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(gone(askFirst), "The terms' dialog stayed after Cancel.")
        XCTAssertFalse(find(naming, "poll.option.hummus").exists, "A suggestion declined at the terms reached the poll. \(onScreen(naming))")
        suggestName.tap()
        XCTAssertTrue(askFirst.waitForExistence(timeout: patience), "The next suggestion did not ask for the terms again. \(onScreen(naming))")
        askFirst.buttons["Accept and go on"].firstMatch.tap()
        let hummus = find(naming, "poll.option.hummus")
        XCTAssertTrue(hummus.waitForExistence(timeout: patience), "The name suggested is not in the poll. \(onScreen(naming))")
        XCTAssertEqual(hummus.label, "Hummus, 1 vote, Being checked", "The name suggested is not the member's, being checked.")
        XCTAssertEqual(hummus.value as? String, "chosen", "The name suggested does not carry the member's vote.")
        XCTAssertTrue(find(naming, "poll.suggested").exists, "The poll does not say the name is in. \(onScreen(naming))")
        keep(naming, "cat-poll-suggested-\(look)")
        let namingInfo = appInfo(naming)
        XCTAssertEqual(served(namingInfo).filter { $0.hasPrefix("suggest") }, ["suggest Hummus, new"], "Not one suggestion, as typed: \(served(namingInfo))")
        let namingTrail = namingInfo.components(separatedBy: "stand-in server:").first ?? namingInfo
        for line in ["terms: asked", "terms: declined", "terms: accepted", "poll: suggested, being checked"] {
            XCTAssertTrue(namingTrail.contains(line), "App info did not keep \"\(line)\".")
        }
        XCTAssertFalse(namingTrail.contains("Hummus") || namingTrail.contains("hummus"), "The trail holds the name suggested.")
        // The rest of the profile, in the same launch: its feed still has
        // the member's post being checked, and the terms were accepted
        // above. It ends with the account deleted.
        profile(naming, look: look)
        naming.terminate()
    }

    /// Signed in, with the terms accepted: Home and a post's menus, Profile
    /// and App info, then Cats. One launch, in this order.
    private func walk(look: String) {
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

        // Scan a cat has its own walk below, and Cats comes last in this
        // one, after App info: a search leaves the keyboard over the tabs.
        app.tabBars.buttons["Profile"].tap()
        XCTAssertTrue(app.navigationBars["Profile"].waitForExistence(timeout: patience), "The tab Profile did not open.")
        keep(app, "profile-\(look)")

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

        cats(app, look: look)
        app.terminate()
    }

    /// Cats: the gallery with the cat of the day and the made-up campus's
    /// three cats; Mitzi's page, her post liked there, her name poll voted
    /// on, moved and taken back, and back to the
    /// gallery as it was; the page of the cat with no name, where nothing
    /// is put in place of what the server did not send; and the search,
    /// with one cat left and with none. The like on Home earlier in the
    /// walk reached the made-up server, so her post starts liked.
    private func cats(_ app: XCUIApplication, look: String) {
        app.tabBars.buttons["Cats"].tap()
        XCTAssertTrue(app.navigationBars["Cats"].waitForExistence(timeout: patience), "The tab Cats did not open. \(onScreen(app))")
        let mitzi = find(app, "gallery.c1")
        XCTAssertTrue(mitzi.waitForExistence(timeout: patience), "The gallery did not show its cats. \(onScreen(app))")
        XCTAssertFalse(app.staticTexts["Not built yet"].exists, "Cats still says it is not built.")
        XCTAssertTrue(find(app, "cats.today").exists, "The gallery has no cat of the day. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["Cat of the day"].exists, "The cat of the day is not called so. \(onScreen(app))")
        XCTAssertTrue(find(app, "gallery.c2").exists, "The gallery has no Shachor. \(onScreen(app))")
        XCTAssertTrue(find(app, "gallery.c3").exists, "The gallery has no cat with no name. \(onScreen(app))")
        XCTAssertTrue(find(app, "cats.sort").exists, "The gallery has no way to sort. \(onScreen(app))")
        XCTAssertTrue(app.searchFields.firstMatch.exists, "The gallery has no search field. \(onScreen(app))")
        keep(app, "cats-\(look)")

        // Mitzi's page: photos, numbers, "You met", and her post below.
        reveal(mitzi, in: app)
        mitzi.tap()
        let name = find(app, "cat.name")
        XCTAssertTrue(name.waitForExistence(timeout: patience), "A cat's page did not open. \(onScreen(app))")
        XCTAssertEqual(name.label, "Mitzi")
        for part in ["cat.photos", "cat.named", "cat.area", "cat.coat", "cat.bio", "cat.number.posts", "cat.number.likes", "cat.number.last-seen", "cat.number.gpa", "cat.met"] {
            XCTAssertTrue(find(app, part).waitForExistence(timeout: patience), "Mitzi's page has no \(part). \(onScreen(app))")
        }
        XCTAssertTrue(app.staticTexts["You met this cat 2 times."].exists, "\"You met\" does not say how often. \(onScreen(app))")
        keep(app, "cat-\(look)")

        // Her post, on the feed's own card: taking the like back and
        // liking again both count, here as on Home.
        // The posts are drawn as they scroll into sight.
        let heart = find(app, "like.p1")
        reveal(heart, in: app)
        XCTAssertTrue(heart.waitForExistence(timeout: patience), "Mitzi's page has no post. \(onScreen(app))")
        XCTAssertTrue(find(app, "menu.p1").exists, "The post on a cat's page has no menu. \(onScreen(app))")
        XCTAssertEqual(heart.value as? String, "liked", "The cat's page does not show the like the member gave on Home.")
        heart.tap()
        let unliked = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 3"), object: heart)
        XCTAssertEqual(XCTWaiter().wait(for: [unliked], timeout: patience), .completed, "Taking the like back on a cat's page did not count. \(onScreen(app))")
        heart.tap()
        let relike = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Like, 4"), object: heart)
        XCTAssertEqual(XCTWaiter().wait(for: [relike], timeout: patience), .completed, "A like on a cat's page did not count. \(onScreen(app))")
        XCTAssertEqual(heart.value as? String, "liked")
        keep(app, "cat-post-\(look)")

        // The name poll: her name leading, a second name, and the member's
        // own suggestion still being checked, with no vote of theirs on it.
        // Revealed from its top, so the whole poll is in the picture.
        reveal(find(app, "poll.total"), in: app)
        let leader = find(app, "poll.option.mitzi")
        let runnerUp = find(app, "poll.option.pilpel")
        let pending = find(app, "poll.option.ptitim")
        XCTAssertTrue(leader.waitForExistence(timeout: patience), "Mitzi's page has no name poll. \(onScreen(app))")
        XCTAssertEqual(leader.label, "Mitzi, 5 votes, LEADING", "The leader is not marked.")
        XCTAssertEqual(runnerUp.label, "Pilpel, 2 votes")
        XCTAssertEqual(pending.label, "Ptitim, 0 votes, Being checked", "The member's own name is not marked as being checked.")
        XCTAssertEqual(find(app, "poll.total").label, "7 votes")
        for option in [leader, runnerUp, pending] {
            XCTAssertEqual(option.value as? String, "not chosen", "\(option.identifier) is chosen before any vote.")
        }
        keep(app, "cat-poll-\(look)")

        // A vote: the member's choice, and the counts as the server answered.
        runnerUp.tap()
        expect(app, "poll.option.pilpel", "Pilpel, 3 votes")
        XCTAssertEqual(runnerUp.value as? String, "chosen", "The vote is not shown as the member's choice.")
        expect(app, "poll.total", "8 votes")
        keep(app, "cat-poll-voted-\(look)")
        // Moved to another option, then taken back by a tap on the choice.
        leader.tap()
        expect(app, "poll.option.mitzi", "Mitzi, 6 votes, LEADING")
        XCTAssertEqual(runnerUp.label, "Pilpel, 2 votes", "The vote moved and stayed counted where it was.")
        XCTAssertEqual(leader.value as? String, "chosen")
        leader.tap()
        expect(app, "poll.option.mitzi", "Mitzi, 5 votes, LEADING")
        XCTAssertEqual(leader.value as? String, "not chosen", "The vote taken back is still shown.")

        // What the made-up server was asked: each once, in order. App info
        // was left open on Profile earlier in the walk: back to its list.
        app.tabBars.buttons["Profile"].tap()
        let profileBack = app.navigationBars["App info"].buttons.element(boundBy: 0)
        XCTAssertTrue(profileBack.waitForExistence(timeout: patience), "Profile is not where the walk left it. \(onScreen(app))")
        profileBack.tap()
        let polled = appInfo(app)
        let votesSent = served(polled).filter { $0.hasPrefix("vote") || $0.hasPrefix("unvote") }
        XCTAssertEqual(votesSent, ["vote pilpel", "vote mitzi from pilpel", "unvote mitzi"], "Not a vote, a vote moved and a vote taken back, each once.")
        let pollTrail = polled.components(separatedBy: "stand-in server:").first ?? polled
        for line in ["poll: voted", "poll: vote taken back"] {
            XCTAssertTrue(pollTrail.contains(line), "App info did not keep \"\(line)\".")
        }
        for word in ["Pilpel", "pilpel", "Ptitim", "ptitim"] {
            XCTAssertFalse(pollTrail.contains(word), "The trail holds \"\(word)\".")
        }
        app.tabBars.buttons["Cats"].tap()
        XCTAssertTrue(name.waitForExistence(timeout: patience), "Cats is not on Mitzi's page as it was left. \(onScreen(app))")

        // Back: the gallery, as it was left.
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.navigationBars["Cats"].waitForExistence(timeout: patience), "Back did not come to the gallery. \(onScreen(app))")
        XCTAssertTrue(mitzi.waitForExistence(timeout: patience), "Back on the gallery, its cats are gone. \(onScreen(app))")
        XCTAssertTrue(find(app, "cats.today").exists && find(app, "gallery.c2").exists, "Back on the gallery, it is not as it was. \(onScreen(app))")

        // The cat with no name and no meeting: the web app's words for the
        // name, and nothing where the server sent nothing.
        let unnamed = find(app, "gallery.c3")
        reveal(unnamed, in: app)
        unnamed.tap()
        XCTAssertTrue(name.waitForExistence(timeout: patience), "The unnamed cat's page did not open. \(onScreen(app))")
        XCTAssertEqual(name.label, "A cat with no name yet")
        XCTAssertTrue(find(app, "cat.no-posts").waitForExistence(timeout: patience), "The unnamed cat's page does not say it has no posts. \(onScreen(app))")
        for part in ["cat.met", "cat.area", "cat.coat", "cat.bio", "cat.number.last-seen", "cat.number.gpa"] {
            XCTAssertFalse(find(app, part).exists, "The unnamed cat's page shows \(part), which the server did not send. \(onScreen(app))")
        }
        keep(app, "cat-unnamed-\(look)")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(mitzi.waitForExistence(timeout: patience), "Back did not come to the gallery. \(onScreen(app))")

        // The search, on the phone: one cat left, then none.
        let field = app.searchFields.firstMatch
        field.tap()
        field.typeText("Mitz")
        XCTAssertTrue(gone(find(app, "gallery.c2")), "A search for Mitzi left Shachor. \(onScreen(app))")
        XCTAssertTrue(mitzi.exists, "A search for Mitzi left her out. \(onScreen(app))")
        XCTAssertFalse(find(app, "gallery.c3").exists, "A search for Mitzi left the cat with no name. \(onScreen(app))")
        keep(app, "cats-search-\(look)")
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 4) + "Garfield")
        XCTAssertTrue(gone(mitzi), "A search for Garfield left Mitzi. \(onScreen(app))")
        let none = find(app, "cats.none")
        XCTAssertTrue(none.waitForExistence(timeout: patience), "A search that finds nothing does not say so. \(onScreen(app))")
        XCTAssertTrue(app.staticTexts["No cat called “Garfield”."].exists, "A search that finds nothing does not say so in the web app's words. \(onScreen(app))")
        keep(app, "cats-search-none-\(look)")
    }

    /// Profile: a new name, which waits to be checked; a username refused
    /// under its field, which keeps what was typed; the profile photo,
    /// chosen (a drawn picture with made-up EXIF), refused the second
    /// time, and removed; My posts, with the
    /// member's post being checked and an older public one; and Delete
    /// account: Cancel sends nothing, then the account goes, the sign-in
    /// screen says so, and the made-up server was asked once, with the
    /// body the API takes. App info was left open on Profile.
    private func profile(_ app: XCUIApplication, look: String) {
        let back = app.navigationBars["App info"].buttons.element(boundBy: 0)
        XCTAssertTrue(back.waitForExistence(timeout: patience), "Profile is not on App info as the walk left it. \(onScreen(app))")
        back.tap()
        XCTAssertTrue(app.navigationBars["Profile"].waitForExistence(timeout: patience), "Back did not come to Profile. \(onScreen(app))")
        for row in ["profile.me", "profile.name", "profile.username", "row.my-posts", "row.app-info", "profile.sign-out"] {
            XCTAssertTrue(find(app, row).waitForExistence(timeout: patience), "Profile has no \(row). \(onScreen(app))")
        }

        // A new name, typed in its row: the server takes it, the member
        // sees it at once, and the row says others see it once checked.
        let nameField = app.textFields["profile.name"].firstMatch
        retype(nameField, "Tess Member")
        let pending = find(app, "profile.name-pending")
        XCTAssertTrue(pending.waitForExistence(timeout: patience), "A new name does not say it is being checked. \(onScreen(app))")
        XCTAssertEqual(pending.label, "Others see your new name once it has been checked.")
        XCTAssertTrue(find(app, "profile.me").label.contains("Tess Member"), "The new name is not the member's at once. \(onScreen(app))")
        keep(app, "profile-name-pending-\(look)")

        // A username someone has: refused under the field, in the web
        // app's words; the field keeps what was typed, the account its name.
        let usernameField = app.textFields["profile.username"].firstMatch
        retype(usernameField, "first.tester")
        let refused = find(app, "profile.username-note")
        XCTAssertTrue(refused.waitForExistence(timeout: patience), "A username taken is not said under the field. \(onScreen(app))")
        XCTAssertEqual(refused.label, "That username is taken. Try another.")
        XCTAssertEqual(usernameField.value as? String, "first.tester", "The field did not keep what was typed.")
        XCTAssertTrue(find(app, "profile.me").label.contains("@test.member"), "A refused username changed the account. \(onScreen(app))")
        keep(app, "profile-username-taken-\(look)")

        // The profile photo. None yet: the menu on it has "Choose a photo"
        // and nothing to remove. The stand-in hands over a drawn picture
        // that carries made-up EXIF and GPS; the terms were accepted above.
        let photo = app.buttons["profile.photo"].firstMatch
        reveal(photo, in: app)
        XCTAssertEqual(photo.value as? String, "no photo", "The member has a photo to begin with. \(onScreen(app))")
        photo.tap()
        let choosePhoto = item(app, "Choose a photo")
        XCTAssertTrue(choosePhoto.waitForExistence(timeout: patience), "The photo's menu has no \"Choose a photo\". \(onScreen(app))")
        XCTAssertFalse(item(app, "Remove photo").exists, "With no photo, the menu offers to remove one. \(onScreen(app))")
        choosePhoto.tap()
        // Taken: the new photo in place, with the web app's words that it
        // is being checked.
        let photoPending = find(app, "profile.photo-pending")
        XCTAssertTrue(photoPending.waitForExistence(timeout: patience), "A new photo does not say it is being checked. \(onScreen(app))")
        XCTAssertEqual(photoPending.label, "Others see your new photo once it has been checked.")
        XCTAssertEqual(photo.value as? String, "photo, being checked", "The new photo is not in place. \(onScreen(app))")
        keep(app, "profile-photo-pending-\(look)")

        // With a photo the menu also has "Remove photo". A second picture:
        // the stand-in refuses it as the server refuses one it cannot use,
        // said in the web app's words, and the photo from before stays.
        photo.tap()
        XCTAssertTrue(item(app, "Remove photo").waitForExistence(timeout: patience), "With a photo, the menu has no \"Remove photo\". \(onScreen(app))")
        XCTAssertTrue(item(app, "Choose a photo").exists, "The menu has no \"Choose a photo\". \(onScreen(app))")
        keep(app, "profile-photo-menu-\(look)")
        item(app, "Choose a photo").tap()
        let photoNote = find(app, "profile.photo-note")
        XCTAssertTrue(photoNote.waitForExistence(timeout: patience), "A refused photo is not said. \(onScreen(app))")
        XCTAssertEqual(photoNote.label, "That picture could not be used. Try another one.", "The refusal is not in the web app's words.")
        XCTAssertEqual(photo.value as? String, "photo, being checked", "A refused photo took the old one's place. \(onScreen(app))")
        XCTAssertFalse(find(app, "profile.photo-retry").exists, "A photo refused for good offers to send it again. \(onScreen(app))")
        keep(app, "profile-photo-refused-\(look)")

        // "Remove photo": the system's confirmation, then the profile with
        // no photo.
        photo.tap()
        let removeItem = item(app, "Remove photo")
        XCTAssertTrue(removeItem.waitForExistence(timeout: patience), "The menu has no \"Remove photo\". \(onScreen(app))")
        removeItem.tap()
        let removing = app.alerts["Remove your profile photo?"]
        XCTAssertTrue(removing.waitForExistence(timeout: patience), "Remove photo did not ask first. \(onScreen(app))")
        removing.buttons["Remove photo"].firstMatch.tap()
        XCTAssertTrue(gone(removing), "The confirmation stayed after Remove photo.")
        let noPhoto = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "no photo"), object: photo)
        XCTAssertEqual(XCTWaiter().wait(for: [noPhoto], timeout: patience), .completed, "After removing, the profile still has a photo. \(onScreen(app))")
        XCTAssertFalse(find(app, "profile.photo-pending").exists, "A removed photo still says it is being checked. \(onScreen(app))")
        keep(app, "profile-photo-removed-\(look)")

        // My posts: two, the one being checked says so, the public one
        // says nothing.
        find(app, "row.my-posts").tap()
        let checking = find(app, "post.state.p2")
        XCTAssertTrue(checking.waitForExistence(timeout: patience), "My posts does not mark the post being checked. \(onScreen(app))")
        XCTAssertEqual(checking.label, "Being checked")
        keep(app, "my-posts-\(look)")
        let older = find(app, "menu.p4")
        reveal(older, in: app)
        XCTAssertFalse(find(app, "post.state.p4").exists, "A public post is marked. \(onScreen(app))")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.navigationBars["Profile"].waitForExistence(timeout: patience), "Back did not come to Profile. \(onScreen(app))")

        // Delete account, last: the system's confirmation with the plan's
        // sentence. Cancel sends nothing.
        let deleteRow = app.buttons["profile.delete-account"].firstMatch
        reveal(deleteRow, in: app)
        deleteRow.tap()
        let asked = app.alerts["Delete your account?"]
        XCTAssertTrue(asked.waitForExistence(timeout: patience), "Delete account did not ask first. \(onScreen(app))")
        let sentence = "Your posts, badges, points and friends will be removed for good. The cat photos you took stay with the cats' records, with nothing left that points to you."
        // XCUITest refuses an identifier over 128 characters: the sentence
        // is asked for by its label instead.
        XCTAssertTrue(asked.staticTexts.matching(NSPredicate(format: "label == %@", sentence)).firstMatch.exists, "The confirmation does not say what goes and what stays. \(onScreen(app))")
        keep(app, "delete-account-\(look)")
        asked.buttons["Cancel"].firstMatch.tap()
        XCTAssertTrue(gone(asked), "The confirmation stayed after Cancel.")
        let cancelled = appInfo(app)
        XCTAssertFalse(served(cancelled).contains { $0.hasPrefix("delete me") }, "Cancel sent the deletion: \(served(cancelled))")
        app.navigationBars["App info"].buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.navigationBars["Profile"].waitForExistence(timeout: patience), "Back did not come to Profile. \(onScreen(app))")

        // Confirmed: the account is being deleted, and the sign-in screen
        // says so in one line.
        reveal(deleteRow, in: app)
        deleteRow.tap()
        XCTAssertTrue(asked.waitForExistence(timeout: patience), "Delete account did not ask the second time. \(onScreen(app))")
        asked.buttons["Delete account"].firstMatch.tap()
        let signIn = find(app, "sign-in.google")
        XCTAssertTrue(signIn.waitForExistence(timeout: patience), "After deleting, the sign-in screen did not come up. \(onScreen(app))")
        XCTAssertEqual(find(app, "sign-in.note").label, "Your account is being deleted.", "The sign-in screen does not say the account is being deleted.")
        keep(app, "signed-out-deleted-\(look)")

        // What the made-up server was asked, from App info on the sign-in
        // screen: the deletion once, with {"confirm": "delete"}.
        app.buttons["App info"].firstMatch.tap()
        let text = find(app, "app-info.text")
        XCTAssertTrue(text.waitForExistence(timeout: patience), "App info did not open from the sign-in screen.")
        let shown = text.label + "\n" + (text.value as? String ?? "")
        let asks = served(shown)
        XCTAssertEqual(asks.filter { $0.hasPrefix("delete me") }, ["delete me confirm delete"], "Not one deletion, as the API takes it: \(asks)")
        XCTAssertEqual(asks.filter { $0.hasPrefix("rename") || $0.hasPrefix("username") }, ["rename", "username name_taken"], "Not one name and one username: \(asks)")
        // The photo: the three calls in order, once each for each picture,
        // the second refused; then one removal.
        let avatarCalls = asks.filter { $0.hasPrefix("avatar") }
        XCTAssertEqual(
            avatarCalls.map { $0.hasPrefix("avatar upload") ? String($0.prefix(15)) : $0 },
            ["avatar start 1", "avatar upload 1", "avatar complete 1", "avatar start 2", "avatar upload 2", "avatar complete 2 bad_photo", "avatar remove"],
            "Not the photo's calls in order, once each: \(avatarCalls)"
        )
        // What storage was sent, read from the bytes: a JPEG of at most
        // 200,000 bytes, square, at most 512 px a side, with no EXIF, XMP
        // or IPTC segment, from a picture 1200 by 900 that carried them.
        for sent in avatarCalls where sent.hasPrefix("avatar upload") {
            let words = sent.components(separatedBy: " ")
            XCTAssertEqual(words.count, 9, "The upload's record cannot be read: \(sent)")
            guard words.count == 9 else { continue }
            XCTAssertEqual(words[3], "jpeg", "The photo sent is not a JPEG: \(sent)")
            XCTAssertLessThanOrEqual(Int(words[4]) ?? .max, 200_000, "The photo sent is over 200,000 bytes: \(sent)")
            let sides = words[6].components(separatedBy: "x").compactMap { Int($0) }
            XCTAssertEqual(sides.count, 2, "The photo sent has no size: \(sent)")
            XCTAssertEqual(sides.first, sides.last, "The photo sent is not square: \(sent)")
            XCTAssertLessThanOrEqual(sides.first ?? .max, 512, "The photo sent is over 512 px a side: \(sent)")
            XCTAssertEqual(words[8], "none", "The photo sent still carries EXIF, XMP or IPTC: \(sent)")
        }
        let trail = shown.components(separatedBy: "stand-in server:").first ?? shown
        for line in [
            "profile: name saved",
            "profile: username refused (name_taken)",
            "my posts: 2 posts",
            "account: delete asked",
            "account: delete cancelled",
            "account: deleting",
            "upload: everything waiting dropped",
            "avatar: chosen",
            "avatar: made ready, ",
            "avatar: refused (bad_photo)",
            "avatar: removed",
        ] {
            XCTAssertTrue(trail.contains(line), "App info did not keep \"\(line)\".")
        }
        for word in ["Tess", "first.tester"] {
            XCTAssertFalse(trail.contains(word), "The trail holds \"\(word)\".")
        }
    }

    /// An item of an open menu, found by its words.
    private func item(_ app: XCUIApplication, _ words: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@", words)).firstMatch
    }

    /// Puts the cursor at the end of a field's text (the end is on the
    /// right: the profile's fields are aligned there), deletes what is
    /// there and types `text` and "done".
    private func retype(_ field: XCUIElement, _ text: String) {
        XCTAssertTrue(field.waitForExistence(timeout: patience), "\(field) is not there.")
        field.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        let had = (field.value as? String)?.count ?? 0
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: had + 2) + text + "\n")
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
        // An open menu dims it the same way.
        let dimmed = name.hasPrefix("terms-") || name.hasPrefix("delete-account-") || name.hasPrefix("profile-photo-menu-")
        // My posts is the stand-in's photos almost edge to edge, under an
        // inline title: a light one measured 0.64. Still far above dark.
        let photos = name.hasPrefix("my-posts-")
        let light = dimmed ? 0.52 : photos ? 0.58 : 0.65
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
