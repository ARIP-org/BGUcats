"""An encounter as the app counts it: `USER#{userId}` / `ENC#{sessionId}` in
bgucats-social (docs/data-model.md, "ENC"; docs/app-plan/03-data-model.md).

The bridge between the two tables. The desk's API writes it when a person
picks a cat and whenever an admin's label changes; the member API writes it
when the encounter is posted. The events Lambda reads it to count what a
person met and to keep a post's cat on the label.

Every write here is an update that sets fields from the truth as it is
now, so sending one twice, or late, does no harm.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from common import regions

ISRAEL = ZoneInfo("Asia/Jerusalem")


def day_of(iso):
    """The Israel date of an ISO time: the day a person met a cat on."""
    moment = datetime.fromisoformat(iso)
    return moment.astimezone(ISRAEL).date().isoformat()


def user_id_for(social_table, email):
    """The app's user id for a sign-in, or None if they never opened the app."""
    if not email:
        return None
    item = social_table.get_item(
        Key={"PK": f"IDENTITY#{email}", "SK": "META"}, ConsistentRead=True
    ).get("Item")
    return item["userId"] if item else None


def key(user_id, session_id):
    return {"PK": f"USER#{user_id}", "SK": f"ENC#{session_id}"}


def place_fields(session):
    """What an encounter takes from its session: when, and in which area.

    The area comes from the location already rounded to about 100 m, never
    from the phone's word, and is the region's id only.
    """
    region = None
    if session.get("coarseLat") is not None and session.get("coarseLon") is not None:
        region = regions.region_at(
            float(session["coarseLat"]), float(session["coarseLon"])
        )
    started = session.get("startedAt") or session.get("lastPhotoAt")
    return {
        "sessionId": session["sessionId"],
        "day": day_of(started) if started else None,
        "regionId": region,
    }


def shown_cat(enc):
    """The cat an encounter counts for: the label, else the claim; none if
    rejected. A person's claim counts at once and the label takes it back
    when it disagrees (D8)."""
    if not enc or enc.get("rejected"):
        return None
    return enc.get("labelCatId") or enc.get("claimedCatId")


def update(social_table, user_id, session_id, fields, *, only_if_there=False, keep=()):
    """SET `fields` on the encounter. `keep` names fields written only if
    absent. With `only_if_there`, an encounter that was never recorded is
    left alone and False is returned."""
    names, values, parts = {}, {}, []
    for i, (field, value) in enumerate(sorted(fields.items())):
        names[f"#f{i}"] = field
        values[f":v{i}"] = value
        if field in keep:
            parts.append(f"#f{i} = if_not_exists(#f{i}, :v{i})")
        else:
            parts.append(f"#f{i} = :v{i}")
    request = {
        "Key": key(user_id, session_id),
        "UpdateExpression": "SET " + ", ".join(parts),
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }
    if only_if_there:
        request["ConditionExpression"] = "attribute_exists(PK)"
    try:
        social_table.update_item(**request)
    except social_table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True
