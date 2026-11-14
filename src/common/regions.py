"""The campus places: web/regions.json, the one list of them.

The phone reads the file from the site; a Lambda reads its own copy,
which `$(call copy-common,…)` puts beside this module. Under pytest, the
file is read from web/ directly.
"""

import json
import math
from functools import cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CANDIDATES = (_HERE / "regions.json", _HERE.parents[1] / "web" / "regions.json")


@cache
def _load():
    for path in _CANDIDATES:
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError("regions.json is not beside common/ nor in web/")


def regions():
    return _load()["regions"]


def ids():
    return frozenset(r["id"] for r in regions())


def feeding_spots():
    """The campus's set feeding spots (D10): an id, names, its region and
    where it is. Made-up ones until the owner's list (O12)."""
    return _load().get("feedingSpots", [])


def feeding_spot_ids():
    return frozenset(s["id"] for s in feeding_spots())


def _metres(lat1, lon1, lat2, lon2):
    # Short distances on one campus: an equirectangular approximation is
    # within a metre of the haversine and easy to read.
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6_371_000 * math.hypot(x, y)


def region_at(lat, lon):
    """The id of the nearest region whose circle holds the point, or None."""
    best = None
    for r in regions():
        d = _metres(lat, lon, r["lat"], r["lon"])
        if d <= r["radiusM"] and (best is None or d < best[0]):
            best = (d, r["id"])
    return best[1] if best else None
