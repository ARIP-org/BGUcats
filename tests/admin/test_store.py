"""Labelling data layer. Spec §4.1, §6.3, §10.

What matters most: assignment is idempotent and ordered photos-first so a
failure can be re-run, nothing that is a duplicate or rejected leaks into a
cat, and derived counts always match GSI3.
"""

import pytest
from ulid import ULID

from admin import store


def cat(table, **overrides):
    fields = {"coatColor": "orange", "coatPattern": "tabby"}
    fields.update(overrides)
    return store.create_cat(table, fields)


# --- queue -------------------------------------------------------------------


class TestQueue:
    def test_groups_unlabelled_photos_into_sessions_oldest_first(self, table, seed):
        first, _ = seed.session(photos=2)
        second, _ = seed.session(photos=3)
        q = store.queue(table)
        assert [e["session"]["sessionId"] for e in q["sessions"]] == [first, second]
        assert [len(e["unlabeled"]) for e in q["sessions"]] == [2, 3]

    def test_only_unlabelled_photos_put_a_session_in_the_queue(self, table, seed):
        seed.session(photos=2, status="duplicate")
        seed.session(photos=2, status="rejected")
        seed.session(photos=2, status="labeled")
        assert store.queue(table)["sessions"] == []

    def test_pending_photos_are_invisible(self, table, seed):
        sid, _ = seed.session(photos=0)
        seed.photo(sid, status="pending")
        assert store.queue(table)["sessions"] == []
        assert store.session_photos(table, sid) == []

    def test_limit_and_cursor_page_through_everything(self, table, seed):
        sessions = [seed.session(photos=2)[0] for _ in range(5)]
        seen, cursor = [], None
        for _ in range(10):
            page = store.queue(table, limit=2, cursor=cursor)
            seen += [e["session"]["sessionId"] for e in page["sessions"]]
            cursor = page["cursor"]
            if not cursor:
                break
        assert list(dict.fromkeys(seen)) == sessions

    def test_interleaved_sessions_are_never_lost(self, table, seed):
        # Two submitters shooting at the same time: their photos alternate in
        # the status index. Paging one session at a time must still reach both.
        a, _ = seed.session(photos=0)
        b, _ = seed.session(photos=0)
        for _ in range(4):
            seed.photo(a)
            seed.photo(b)
        seen, cursor = [], None
        for _ in range(20):
            page = store.queue(table, limit=1, cursor=cursor)
            seen += [e["session"]["sessionId"] for e in page["sessions"]]
            cursor = page["cursor"]
            if not cursor:
                break
        assert set(seen) == {a, b}

    def test_queue_size_counts_photos(self, table, seed):
        seed.session(photos=3)
        seed.session(photos=2, status="labeled")
        assert store.queue_size(table) == 3


# --- cats --------------------------------------------------------------------


class TestCats:
    def test_create_requires_coat_fields(self, table):
        with pytest.raises(store.StoreError, match="coatColor is required"):
            store.create_cat(table, {"coatPattern": "solid"})

    @pytest.mark.parametrize(
        ("field", "value"),
        [("coatColor", "purple"), ("coatPattern", "spots"), ("status", "asleep")],
    )
    def test_enums_follow_the_spec(self, table, field, value):
        fields = {"coatColor": "black", "coatPattern": "solid", field: value}
        with pytest.raises(store.StoreError, match=field):
            store.create_cat(table, fields)

    def test_unknown_fields_are_refused(self, table):
        with pytest.raises(store.StoreError, match="unknown cat fields"):
            store.create_cat(
                table, {"coatColor": "black", "coatPattern": "solid", "x": 1}
            )

    def test_create_with_a_client_ulid_is_idempotent(self, table):
        cat_id = str(ULID())
        a = store.create_cat(
            table, {"coatColor": "black", "coatPattern": "solid"}, cat_id
        )
        b = store.create_cat(
            table, {"coatColor": "white", "coatPattern": "solid"}, cat_id
        )
        assert a["catId"] == b["catId"] == cat_id
        assert b["coatColor"] == "black"  # the retry did not overwrite
        assert len(store.list_cats(table)) == 1

    def test_unset_fields_are_absent_not_null(self, table):
        item = cat(table)
        assert "displayName" not in item
        assert item["status"] == "active"

    def test_listing_returns_cats_only(self, table, seed):
        seed.session(photos=3)
        cat(table, displayName="Ryzhik")
        cats = store.list_cats(table)
        assert [c["displayName"] for c in cats] == ["Ryzhik"]

    def test_update_sets_and_clears(self, table):
        c = cat(table, displayName="Ryzhik")
        updated = store.update_cat(
            table, c["catId"], {"displayName": "", "distinguishing": "notched left ear"}
        )
        assert "displayName" not in updated
        assert updated["distinguishing"] == "notched left ear"

    def test_required_fields_cannot_be_cleared(self, table):
        c = cat(table)
        with pytest.raises(store.StoreError, match="cannot be cleared"):
            store.update_cat(table, c["catId"], {"coatColor": None})

    @pytest.mark.parametrize("bad", ["X#Y", "PHOTO#1", "", "short", None])
    def test_ids_that_are_not_ulids_are_refused(self, table, bad):
        with pytest.raises(store.StoreError, match="must be a ULID"):
            store.get_cat(table, bad)


# --- assignment ----------------------------------------------------------------


class TestAssign:
    def test_labels_every_photo_and_then_the_session(self, table, seed):
        sid, photos = seed.session(photos=3)
        c = cat(table)
        result = store.assign_session(table, sid, c["catId"])
        assert result["labeled"] == 3
        for pid in photos:
            item = seed.get(f"PHOTO#{pid}")
            assert item["status"] == "labeled"
            assert item["catId"] == c["catId"]
            assert item["GSI2PK"] == "STATUS#labeled"
            assert item["GSI3PK"] == f"CAT#{c['catId']}"
            assert item["GSI3SK"] == item["createdAt"]
        assert seed.get(f"SESSION#{sid}")["catId"] == c["catId"]

    def test_assigned_session_leaves_the_queue(self, table, seed):
        sid, _ = seed.session(photos=3)
        store.assign_session(table, sid, cat(table)["catId"])
        assert store.queue(table)["sessions"] == []

    def test_duplicates_and_rejected_photos_are_not_labelled(self, table, seed):
        sid, _ = seed.session(photos=2)
        dup = seed.photo(sid, status="duplicate")
        rej = seed.photo(sid, status="rejected")
        result = store.assign_session(table, sid, cat(table)["catId"])
        assert result["labeled"] == 2
        assert result["skipped"] == {"duplicate": 1, "rejected": 1}
        assert seed.get(f"PHOTO#{dup}")["status"] == "duplicate"
        assert "GSI3PK" not in seed.get(f"PHOTO#{rej}")

    def test_rerunning_is_a_no_op(self, table, seed):
        sid, _ = seed.session(photos=3)
        c = cat(table)
        store.assign_session(table, sid, c["catId"])
        store.assign_session(table, sid, c["catId"])
        assert store.get_cat(table, c["catId"])["photoCount"] == 3
        assert len(store.cat_photos(table, c["catId"])) == 3

    def test_reassigning_moves_photos_and_recounts_both_cats(self, table, seed):
        sid, _ = seed.session(photos=3)
        wrong, right = cat(table), cat(table, coatColor="grey")
        store.assign_session(table, sid, wrong["catId"])
        store.assign_session(table, sid, right["catId"])
        assert store.get_cat(table, wrong["catId"])["photoCount"] == 0
        assert store.get_cat(table, right["catId"])["photoCount"] == 3
        assert store.cat_photos(table, wrong["catId"]) == []

    def test_counts_and_primary_photo_follow_gsi3(self, table, seed):
        c = cat(table)
        s1, p1 = seed.session(photos=2)
        s2, _ = seed.session(photos=3)
        store.assign_session(table, s1, c["catId"])
        store.assign_session(table, s2, c["catId"])
        item = store.get_cat(table, c["catId"])
        assert (item["photoCount"], item["sessionCount"]) == (5, 2)
        assert item["primaryPhotoId"] == p1[0]

    def test_a_chosen_primary_photo_is_kept(self, table, seed):
        c = cat(table)
        sid, photos = seed.session(photos=3)
        store.assign_session(table, sid, c["catId"])
        store.update_cat(table, c["catId"], {"primaryPhotoId": photos[2]})
        s2, _ = seed.session(photos=1)
        store.assign_session(table, s2, c["catId"])
        assert store.get_cat(table, c["catId"])["primaryPhotoId"] == photos[2]

    def test_missing_session_or_cat_is_not_found(self, table, seed):
        sid, _ = seed.session()
        with pytest.raises(store.NotFound):
            store.assign_session(table, sid, str(ULID()))
        with pytest.raises(store.NotFound):
            store.assign_session(table, str(ULID()), cat(table)["catId"])

    def test_a_failure_halfway_leaves_the_session_unassigned(
        self, table, seed, monkeypatch
    ):
        sid, photos = seed.session(photos=3)
        c = cat(table)
        real = table.update_item
        calls = {"n": 0}

        def flaky(**kwargs):
            if kwargs["Key"]["PK"].startswith("PHOTO#"):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("network blip")
            return real(**kwargs)

        monkeypatch.setattr(table, "update_item", flaky)
        with pytest.raises(RuntimeError):
            store.assign_session(table, sid, c["catId"])
        # Parent last: the session is not marked as merged...
        assert seed.get(f"SESSION#{sid}")["catId"] is None
        # ...and it is still in the queue, so the admin will see it again.
        assert store.queue(table)["sessions"][0]["session"]["sessionId"] == sid

        monkeypatch.setattr(table, "update_item", real)
        store.assign_session(table, sid, c["catId"])
        assert seed.get(f"SESSION#{sid}")["catId"] == c["catId"]
        assert all(seed.get(f"PHOTO#{p}")["status"] == "labeled" for p in photos)


# --- reject / restore ----------------------------------------------------------


class TestReject:
    def test_reject_removes_from_queue_and_from_the_cat(self, table, seed):
        sid, photos = seed.session(photos=3)
        c = cat(table)
        store.assign_session(table, sid, c["catId"])
        store.reject_photos(table, [photos[0]], "two cats in frame")
        item = seed.get(f"PHOTO#{photos[0]}")
        assert item["status"] == "rejected"
        assert item["rejectReason"] == "two cats in frame"
        assert item["rejectedFrom"] == "labeled"
        assert "GSI3PK" not in item
        assert store.get_cat(table, c["catId"])["photoCount"] == 2

    def test_rejecting_the_main_photo_picks_another(self, table, seed):
        sid, photos = seed.session(photos=2)
        c = cat(table)
        store.assign_session(table, sid, c["catId"])
        assert store.get_cat(table, c["catId"])["primaryPhotoId"] == photos[0]
        store.reject_photos(table, [photos[0]], "blurry")
        assert store.get_cat(table, c["catId"])["primaryPhotoId"] == photos[1]

    def test_a_cat_with_no_photos_has_no_main_photo(self, table, seed):
        sid, photos = seed.session(photos=1)
        c = cat(table)
        store.assign_session(table, sid, c["catId"])
        store.reject_photos(table, photos, "not a cat")
        assert "primaryPhotoId" not in store.get_cat(table, c["catId"])

    def test_pending_photos_cannot_be_rejected(self, table, seed):
        sid, _ = seed.session(photos=0)
        pid = seed.photo(sid, status="pending")
        with pytest.raises(store.Conflict, match="finished uploading"):
            store.reject_photos(table, [pid], "x")

    def test_reject_session_rejects_only_assignable_photos(self, table, seed):
        sid, _ = seed.session(photos=2)
        dup = seed.photo(sid, status="duplicate")
        assert store.reject_session(table, sid, "not a cat") == {"rejected": 2}
        assert seed.get(f"PHOTO#{dup}")["status"] == "duplicate"
        assert store.queue(table)["sessions"] == []

    def test_restore_returns_a_photo_to_the_queue(self, table, seed):
        _, photos = seed.session(photos=2)
        store.reject_photos(table, photos, "oops")
        assert store.restore_photos(table, photos) == {"restored": 2}
        item = seed.get(f"PHOTO#{photos[0]}")
        assert item["status"] == "unlabeled"
        assert "rejectReason" not in item
        assert store.queue_size(table) == 2

    def test_a_restored_duplicate_stays_a_duplicate(self, table, seed):
        # Otherwise the same bytes could be labelled a second time and counted
        # twice in the dataset.
        sid, _ = seed.session(photos=1)
        dup = seed.photo(sid, status="duplicate")
        store.reject_photos(table, [dup], "oops")
        store.restore_photos(table, [dup])
        item = seed.get(f"PHOTO#{dup}")
        assert item["status"] == "duplicate"
        assert item["GSI2PK"] == "STATUS#duplicate"
        c = cat(table)
        assert store.assign_session(table, sid, c["catId"])["labeled"] == 1

    def test_restore_only_touches_rejected_photos(self, table, seed):
        _, photos = seed.session(photos=1)
        assert store.restore_photos(table, photos) == {"restored": 0}


# --- merge ---------------------------------------------------------------------


class TestMerge:
    def test_moves_everything_and_leaves_a_tombstone(self, table, seed):
        a, b = cat(table, displayName="A"), cat(table, displayName="B")
        s1, _ = seed.session(photos=2)
        s2, _ = seed.session(photos=3)
        store.assign_session(table, s1, a["catId"])
        store.assign_session(table, s2, b["catId"])

        result = store.merge_cats(table, b["catId"], a["catId"])
        assert result["moved_sessions"] == 1
        assert store.get_cat(table, a["catId"])["photoCount"] == 5
        assert store.get_cat(table, a["catId"])["sessionCount"] == 2
        assert seed.get(f"SESSION#{s2}")["catId"] == a["catId"]
        source = store.get_cat(table, b["catId"])
        assert source["mergedInto"] == a["catId"]
        assert source["photoCount"] == 0
        assert [c["catId"] for c in store.list_cats(table)] == [a["catId"]]

    def test_rerunning_a_merge_is_a_no_op(self, table, seed):
        a, b = cat(table), cat(table)
        sid, _ = seed.session(photos=2)
        store.assign_session(table, sid, b["catId"])
        store.merge_cats(table, b["catId"], a["catId"])
        assert store.merge_cats(table, b["catId"], a["catId"])["moved_sessions"] == 0
        assert store.get_cat(table, a["catId"])["photoCount"] == 2

    def test_cannot_merge_into_itself(self, table):
        a = cat(table)
        with pytest.raises(store.StoreError, match="itself"):
            store.merge_cats(table, a["catId"], a["catId"])

    def test_cannot_merge_into_a_merged_cat(self, table):
        a, b, c = cat(table), cat(table), cat(table)
        store.merge_cats(table, b["catId"], a["catId"])
        with pytest.raises(store.Conflict):
            store.merge_cats(table, c["catId"], b["catId"])

    def test_a_merged_cat_cannot_receive_sessions_or_edits(self, table, seed):
        a, b = cat(table), cat(table)
        store.merge_cats(table, b["catId"], a["catId"])
        sid, _ = seed.session()
        with pytest.raises(store.Conflict):
            store.assign_session(table, sid, b["catId"])
        with pytest.raises(store.Conflict):
            store.update_cat(table, b["catId"], {"displayName": "x"})


# --- coverage -------------------------------------------------------------------


class TestCoverage:
    @pytest.mark.parametrize(
        ("photos", "sessions", "usable"),
        [(19, 5, False), (20, 2, False), (20, 3, True), (100, 10, True)],
    )
    def test_usable_needs_both_floors(self, photos, sessions, usable):
        assert store.coverage(photos, sessions)["usable"] is usable

    def test_levels(self):
        c = store.coverage(50, 3)
        assert c == {"photos": "comfortable", "sessions": "floor", "usable": True}
