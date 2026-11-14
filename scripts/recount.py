"""Count the app's counters again from nothing and say where the stored
ones differ (docs/app-plan/08-milestones.md, B7: "a recount script").

Everything the events Lambda keeps is a sum of other items in the app's
table: a person's cats met, points, posts and badges from their encounters;
their feeding points from their feedings; a cat's popularity from what each
person gives it; a cat's "last fed" from its feedings. This reads the whole
table once, works each sum out with the Lambda's own functions, and prints
one line for every stored number that is not what the items add up to.

**It only reads.** A difference is put right by the Lambda itself the next
time one of that person's items changes; if one ever needs correcting by
hand, that is a job for the owner to ask for by name.

    AWS_PROFILE=bgucats-staging-ro python scripts/recount.py
    AWS_PROFILE=bgucats-prod-ro python scripts/recount.py

Exit status 1 if anything differs. A person who acts while the table is
being read can show as a difference that the next run does not.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _number(value):
    return int(value or 0)


def read(table):
    """Every item of the table, a page at a time."""
    items, start = [], None
    while True:
        page = table.scan(**({"ExclusiveStartKey": start} if start else {}))
        items.extend(page["Items"])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def differences(items):
    """One line for each stored counter that its items do not add up to."""
    # Imported here: the module opens a boto3 resource when it loads, and
    # the caller has chosen the account by then.
    from events import handler as events

    people, cats = {}, {}
    for item in items:
        pk, sk = item["PK"], item["SK"]
        if pk.startswith("USER#"):
            mine = people.setdefault(
                pk, {"enc": [], "fed": [], "met": {}, "metm": {}, "badges": set(), "all": {}}
            )
            if sk.startswith("ENC#"):
                mine["enc"].append(item)
            elif sk.startswith("FED#"):
                mine["fed"].append(item)
            elif sk.startswith("METM#"):
                mine["metm"][(item["catId"], item["month"])] = _number(item["points"])
            elif sk.startswith("MET#"):
                mine["met"][item["catId"]] = item
            elif sk.startswith("BADGE#"):
                mine["badges"].add(sk.removeprefix("BADGE#"))
            elif sk == "STATS#ALL":
                mine["all"] = item
        elif pk.startswith("CAT#"):
            cat = cats.setdefault(pk.removeprefix("CAT#"), {"public": {}, "fed": []})
            if sk == "PUBLIC":
                cat["public"] = item
            elif sk.startswith("FED#"):
                cat["fed"].append(item)

    out = []
    given = {}  # (catId, month) -> what everyone gives it
    for pk, mine in sorted(people.items()):
        met, _months, total = events.summarise(mine["enc"])
        points, posts, badges = events.achievements(mine["enc"], met)
        fed_points, cats_fed, feedings = events.fed(mine["fed"])
        want = {
            "encounters": total["encounters"],
            "catsMet": total["catsMet"],
            "points": points,
            "posts": posts,
            "fedPoints": fed_points,
            "catsFed": cats_fed,
            "feedings": feedings,
        }
        for field, value in want.items():
            stored = _number(mine["all"].get(field))
            if stored != value:
                out.append(f"{pk} STATS#ALL {field}: stored {stored}, counted {value}")
        if set(mine["met"]) != set(met):
            out.append(f"{pk} MET#: stored {sorted(mine['met'])}, counted {sorted(met)}")
        for cat, entry in met.items():
            stored = mine["met"].get(cat)
            if stored and (_number(stored["days"]), _number(stored["encounters"])) != (
                entry["days"],
                entry["encounters"],
            ):
                out.append(f"{pk} MET#{cat}: days or encounters differ")
        earned = {b for b in badges if b in events.ENCOUNTER_BADGES}
        held = mine["badges"] & set(events.ENCOUNTER_BADGES)
        if held != earned:
            out.append(f"{pk} badges: holds {sorted(held)}, earned {sorted(earned)}")
        if ("snack-giver" in mine["badges"]) != bool(feedings):
            out.append(f"{pk} badge snack-giver: held {'snack-giver' in mine['badges']}, feedings {feedings}")
        gives = events.popularity(mine["enc"])
        if gives != mine["metm"]:
            out.append(f"{pk} METM#: stored {sorted(mine['metm'].items())}, counted {sorted(gives.items())}")
        for key, value in gives.items():
            given[key] = given.get(key, 0) + value

    months = {month for _cat, month in given}
    for cat_id, cat in sorted(cats.items()):
        stored_months = {k.removeprefix("pop") for k in cat["public"] if k.startswith("pop")}
        for month in sorted(months | stored_months):
            stored = _number(cat["public"].get(f"pop{month}"))
            counted = given.get((cat_id, month), 0)
            if stored != counted:
                out.append(f"CAT#{cat_id} pop{month}: stored {stored}, counted {counted}")
        standing = max((f["at"] for f in cat["fed"] if not f.get("removed")), default=None)
        if cat["public"].get("lastFedAt") != standing:
            out.append(f"CAT#{cat_id} lastFedAt: stored {cat['public'].get('lastFedAt')}, counted {standing}")
    for cat_id, month in sorted(given):
        if cat_id not in cats:
            out.append(f"CAT#{cat_id} pop{month}: no public item, counted {given[(cat_id, month)]}")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", default="bgucats-social")
    args = parser.parse_args()
    profile = os.environ.get("AWS_PROFILE", "")
    if not profile.endswith("-ro"):
        sys.exit(
            "This only reads, so run it with a read-only profile: "
            f"AWS_PROFILE=bgucats-staging-ro or bgucats-prod-ro (AWS_PROFILE is {profile or 'not set'})."
        )
    import boto3

    table = boto3.Session(profile_name=profile, region_name="us-east-1").resource("dynamodb").Table(args.table)
    found = differences(read(table))
    for line in found:
        print(line)
    print(f"{len(found)} difference(s) in {args.table}." if found else f"Every counter in {args.table} is what its items add up to.")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
