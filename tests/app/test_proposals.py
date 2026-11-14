"""New-cat proposals (B6): "a cat that isn't here" from the member app, the
desk's approve, merge and reject, and the post that waits for the decision.
Nothing about a proposed cat is public until an admin decides (D7)."""

from tests.app.test_encounters import (
    BAMBA,
    POST,
    SESSION,
    SIMBA,
    campus,  # noqa: F401  (the fixture)
    cat_counts,
    desk_call,
    enc,
    encounter,
    met,
)
from tests.app.test_me import call

from .test_me import ADMIN, HELPER, aws  # noqa: F401  (the fixture)

PROPOSAL = "01JD0000000000000000000PR1"
OTHER_PROPOSAL = "01JD0000000000000000000PR2"


def propose(proposal_id=PROPOSAL, session=SESSION, email=HELPER, **fields):
    body = {
        "proposalId": proposal_id,
        "sessionId": session,
        "nameIdea": "Hummus",
        "coat": "ginger",
        "regionId": "library",
        "traits": ["kitten", "friendly", "kitten"],
        **fields,
    }
    return call("POST", "/api/v1/proposals", body, email=email)


def post_new_cat(proposal_id=PROPOSAL):
    return call(
        "POST",
        "/api/v1/posts",
        {
            "postId": POST,
            "sessionId": SESSION,
            "photoIds": ["01JD0000000000000000000PH1"],
            "claim": {"proposalId": proposal_id},
            "text": "Never seen this one before.",
        },
        email=HELPER,
    )


def my_card(email=HELPER):
    return call("GET", f"/api/v1/posts/{POST}", email=email)


def desk_proposals():
    return desk_call("GET", "/api/proposals")[1]["proposals"]


def public_cat_ids():
    return {c["catId"] for c in call("GET", "/api/v1/cats", email=ADMIN)[1]["cats"]}


# ------------------------------------------------------------- proposing


def test_a_proposal_is_the_proposer_s_and_nobody_else_s(campus):  # noqa: F811
    encounter(campus)
    status, body = propose()
    assert status == 200
    proposal = body["proposal"]
    assert proposal["status"] == "open"
    assert proposal["traits"] == ["friendly", "kitten"]  # one order, no repeats
    assert enc(campus)["proposalId"] == PROPOSAL
    assert enc(campus)["claimedCatId"] is None
    mine = call("GET", "/api/v1/me/proposals", email=HELPER)[1]["proposals"]
    assert [p["proposalId"] for p in mine] == [PROPOSAL]
    assert call("GET", "/api/v1/me/proposals", email=ADMIN)[1]["proposals"] == []
    assert PROPOSAL not in public_cat_ids()


def test_sending_it_again_is_the_same_proposal(campus):  # noqa: F811
    encounter(campus)
    first = propose()[1]
    assert propose()[1] == first


def test_one_proposal_per_encounter(campus):  # noqa: F811
    encounter(campus)
    propose()
    status, body = propose(OTHER_PROPOSAL)
    assert (status, body["code"]) == (409, "already_proposed")


def test_only_from_the_lists(campus):  # noqa: F811
    encounter(campus)
    for bad in ({"coat": "purple"}, {"traits": ["grumpy"]}, {"regionId": "moon"}):
        assert propose(**bad)[0] == 400, bad
    assert propose(regionId="elsewhere", coat=None, traits=[])[0] == 200


def test_not_for_someone_else_s_encounter(campus):  # noqa: F811
    encounter(campus)
    assert propose(email=ADMIN)[0] == 403


def test_capture_may_answer_a_new_cat(campus):  # noqa: F811
    encounter(campus)
    body = {
        "modelVersion": "mega-t224-int8-0123456789ab",
        "choice": "new",
        "shown": [SIMBA, BAMBA],
        "ranked": [{"catId": SIMBA, "score": 0.5}],
        "photoCount": 1,
    }
    assert desk_call("POST", f"/api/encounters/{SESSION}/pick", body, HELPER)[0] == 200


# ------------------------------------------------------------- the held post


def test_a_post_for_a_new_cat_waits_for_the_admin(campus):  # noqa: F811
    encounter(campus)
    propose()
    assert post_new_cat()[0] == 200
    campus["stream"].settle()
    status, body = my_card()
    assert status == 200
    card = body["post"]
    assert card["state"] == "pending"
    assert card["cat"] is None
    assert card["proposal"] == {
        "proposalId": PROPOSAL,
        "status": "open",
        "nameIdea": "Hummus",
    }
    assert my_card(ADMIN)[0] == 404
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"] == []


def test_a_post_cannot_name_someone_else_s_proposal(campus):  # noqa: F811
    encounter(campus)
    propose()
    status, _ = call(
        "POST",
        "/api/v1/posts",
        {
            "postId": POST,
            "sessionId": SESSION,
            "photoIds": ["01JD0000000000000000000PH1"],
            "claim": {"proposalId": OTHER_PROPOSAL},
        },
        email=HELPER,
    )
    assert status == 400


# ------------------------------------------------------------- the desk


def test_the_desk_lists_what_waits(campus):  # noqa: F811
    encounter(campus)
    propose()
    (item,) = desk_proposals()
    assert item["proposalId"] == PROPOSAL
    assert item["nameIdea"] == "Hummus"
    assert item["proposer"]["username"] == "helper"
    assert len(item["photos"]) == 1 and item["photos"][0]["thumbUrl"]
    # A user is refused the desk's queue.
    assert desk_call("GET", "/api/proposals", email=HELPER)[0] == 403


def test_approving_makes_the_cat_labels_the_encounter_and_publishes_the_post(
    campus,  # noqa: F811
):
    encounter(campus)
    propose()
    post_new_cat()
    campus["stream"].settle()

    status, body = desk_call(
        "POST", f"/api/proposals/{PROPOSAL}/approve", {"name": "Hummus"}
    )
    assert status == 200 and body["catId"] == PROPOSAL
    campus["stream"].settle()

    cat = campus["data"].get_item(Key={"PK": f"CAT#{PROPOSAL}", "SK": "META"})["Item"]
    assert (cat["name"], cat["coat"], cat["usualRegionId"]) == (
        "Hummus",
        "ginger",
        "library",
    )
    session = campus["data"].get_item(Key={"PK": f"SESSION#{SESSION}", "SK": "META"})
    assert session["Item"]["catId"] == PROPOSAL
    assert PROPOSAL in public_cat_ids()

    card = my_card(ADMIN)[1]["post"]
    assert card["cat"] == {"catId": PROPOSAL, "name": "Hummus"}
    assert [
        c["postId"] for c in call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"]
    ] == [POST]
    assert cat_counts(campus, PROPOSAL) == (1, 0)
    assert set(met(campus)) == {PROPOSAL}
    assert desk_proposals() == []

    # Approving again makes no second cat.
    assert (
        desk_call("POST", f"/api/proposals/{PROPOSAL}/approve")[1]["catId"] == PROPOSAL
    )


def test_approving_without_a_name_needs_one(campus):  # noqa: F811
    encounter(campus)
    propose(nameIdea=None)
    status, body = desk_call("POST", f"/api/proposals/{PROPOSAL}/approve")
    assert status == 400 and "name" in body["error"]


def test_merging_puts_the_post_on_the_known_cat(campus):  # noqa: F811
    encounter(campus)
    propose()
    post_new_cat()
    campus["stream"].settle()
    desk_call("POST", f"/api/proposals/{PROPOSAL}/merge", {"catId": SIMBA})
    campus["stream"].settle()
    card = my_card(ADMIN)[1]["post"]
    assert card["cat"]["catId"] == SIMBA
    assert cat_counts(campus, SIMBA) == (1, 0)
    assert PROPOSAL not in public_cat_ids()
    assert set(met(campus)) == {SIMBA}


def test_rejecting_keeps_the_post_unpublished_and_the_encounter_in_the_queue(
    campus,  # noqa: F811
):
    encounter(campus)
    propose()
    post_new_cat()
    campus["stream"].settle()
    desk_call("POST", f"/api/proposals/{PROPOSAL}/reject")
    campus["stream"].settle()
    card = my_card()[1]["post"]
    assert card["state"] == "hidden"
    assert card["proposal"]["status"] == "rejected"
    assert my_card(ADMIN)[0] == 404
    assert call("GET", "/api/v1/feed", email=ADMIN)[1]["cards"] == []
    session = campus["data"].get_item(Key={"PK": f"SESSION#{SESSION}", "SK": "META"})
    assert session["Item"].get("catId") is None
    # A second, different decision is refused.
    assert (
        desk_call("POST", f"/api/proposals/{PROPOSAL}/merge", {"catId": SIMBA})[0]
        == 409
    )
    # And the person may propose again for the same encounter.
    assert propose(OTHER_PROPOSAL)[0] == 200


def test_a_post_for_a_rejected_proposal_is_refused(campus):  # noqa: F811
    encounter(campus)
    propose()
    desk_call("POST", f"/api/proposals/{PROPOSAL}/reject")
    status, body = post_new_cat()
    assert (status, body["code"]) == (400, "not_accepted")


# --------------------------------------------------------------- push (B9)


def test_an_approved_cat_is_told_to_whoever_added_it_and_a_rejected_one_is_not(
    campus,  # noqa: F811
    monkeypatch,
):
    from events import handler as events

    sent = []
    monkeypatch.setattr(events, "PUSH", True)
    monkeypatch.setattr(
        events, "_deliver", lambda device, payload, key: sent.append(payload) or "sent"
    )
    call(
        "PUT",
        "/api/v1/me/devices/phone-0001",
        {"apnsToken": "ab" * 32, "environment": "production"},
        email=HELPER,
    )
    encounter(campus)
    assert propose()[0] == 200
    campus["stream"].settle()
    assert sent == []

    assert desk_call("POST", f"/api/proposals/{PROPOSAL}/approve", {"name": "Hummus"})[0] == 200
    campus["stream"].settle()
    (push,) = sent
    assert push["aps"]["alert"]["body"] == "The new cat you added was approved"
    assert push["opens"] == {"kind": "cat", "id": PROPOSAL}
    assert "Hummus" not in str(push)

    # Another one, rejected: said in the app, never on a lock screen.
    other_session = "01JD0000000000000000000SE2"
    encounter(campus, session=other_session, photo="01JD0000000000000000000PH2")
    assert propose(OTHER_PROPOSAL, session=other_session)[0] == 200
    campus["stream"].settle()
    assert desk_call("POST", f"/api/proposals/{OTHER_PROPOSAL}/reject")[0] == 200
    campus["stream"].settle()
    assert len(sent) == 1
