#!/usr/bin/env python3
"""Refresh the MBTA Frequent Bus Network list from the V3 API.

The MBTA maintains the "Frequent Bus" designation itself (the set changes with
service pickens/redesigns), and exposes it as the `description` field on each
route in the V3 API — the same data as the static GTFS feed, but the frequent
label only lives on the API. So we pull it rather than recompute headways from
stop_times: whatever MBTA currently lists as frequent is the source of truth.

Output: data/frequent_bus.json (schema tonight.frequentbus/1). Each run diffs
against the previous file so the app-health dashboard can flag when a route
joins/leaves the network or its endpoints change. It also cross-checks the
routes actually drawn on the metro map (transit-layer.json) so a drawn route
that loses frequent status — or a newly-frequent route with no line drawn yet —
is surfaced too.

Run from the repo root:  python3 scraper/refresh_frequent_bus.py
Weekly via .github/workflows/frequent-bus.yml.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "frequent_bus.json"
TRANSIT_LAYER = ROOT / "transit-layer.json"

V3_ROUTES = "https://api-v3.mbta.com/routes"
FREQUENT_DESC = "Frequent Bus"
# Silver Line routes carry description "Frequent Bus" too, but the app already
# renders them as rapid-transit "Silver". Tag them so the front end / dashboard
# can treat them differently from numbered buses.
SILVER_PREFIX = "SL"
SCHEMA = "tonight.frequentbus/1"


def fetch_frequent_routes():
    params = {
        "filter[type]": "3",  # 3 = bus (includes Silver Line)
        "fields[route]": "short_name,long_name,description,direction_destinations,color",
    }
    headers = {}
    key = os.environ.get("MBTA_API_KEY")
    if key:
        headers["x-api-key"] = key
    resp = requests.get(V3_ROUTES, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    routes = []
    for r in data:
        a = r.get("attributes", {})
        if a.get("description") != FREQUENT_DESC:
            continue
        short = a.get("short_name") or r["id"]
        routes.append({
            "id": r["id"],
            "short_name": short,
            "long_name": a.get("long_name", ""),
            # set-compared for change detection, but stored ordered for display
            "endpoints": a.get("direction_destinations") or [],
            "color": a.get("color", ""),
            "silver_line": short.upper().startswith(SILVER_PREFIX),
        })
    routes.sort(key=lambda x: (x["silver_line"], _num_key(x["short_name"])))
    return routes


def _num_key(short):
    """Sort '1' < '9' < '15' < '104' numerically, SL* alphabetically."""
    return (0, int(short)) if short.isdigit() else (1, short)


def load_previous():
    if not OUT.exists():
        return None
    try:
        return json.loads(OUT.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def diff_routes(prev_routes, cur_routes):
    """Compare previous vs current frequent lists by route id."""
    prev = {r["id"]: r for r in (prev_routes or [])}
    cur = {r["id"]: r for r in cur_routes}

    added = [cur[i]["short_name"] for i in cur if i not in prev]
    dropped = [prev[i]["short_name"] for i in prev if i not in cur]

    endpoint_changed = []
    for i in cur:
        if i not in prev:
            continue
        pe, ce = set(prev[i].get("endpoints", [])), set(cur[i].get("endpoints", []))
        pln, cln = prev[i].get("long_name", ""), cur[i].get("long_name", "")
        if pe != ce or pln != cln:
            endpoint_changed.append({
                "short_name": cur[i]["short_name"],
                "was": prev[i].get("long_name", ""),
                "now": cur[i].get("long_name", ""),
            })
    return {
        "added": sorted(added, key=_num_key),
        "dropped": sorted(dropped, key=_num_key),
        "endpoint_changed": sorted(endpoint_changed, key=lambda x: _num_key(x["short_name"])),
    }


def drawn_bus_routes():
    """Route short_names drawn on the metro map (line entries with mode 'Bus'
    or 'Silver'). Convention: the line entry's `name` holds the route short_name
    (e.g. "1", "66", "SL1"). Returns None if the map can't be read."""
    if not TRANSIT_LAYER.exists():
        return None
    try:
        layer = json.loads(TRANSIT_LAYER.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    drawn = set()
    for ln in layer.get("lines", []):
        if ln.get("line") in ("Bus", "Silver"):
            name = (ln.get("name") or "").strip()
            if name:
                drawn.add(name)
    return drawn


def map_coverage(cur_routes, drawn):
    """Only meaningful once the user has started drawing bus routes; until then
    every route is 'missing' which is just noise, so we suppress it."""
    cov = {"tracking": False, "drawn": [], "missing_from_map": [], "drawn_not_frequent": []}
    if not drawn:
        return cov
    cov["tracking"] = True
    frequent_names = {r["short_name"] for r in cur_routes}
    cov["drawn"] = sorted(drawn, key=_num_key)
    cov["missing_from_map"] = sorted(frequent_names - drawn, key=_num_key)
    cov["drawn_not_frequent"] = sorted(drawn - frequent_names, key=_num_key)
    return cov


def main():
    now = datetime.now(timezone.utc).isoformat()
    try:
        routes = fetch_frequent_routes()
    except requests.RequestException as e:
        print(f"ERROR: could not reach MBTA V3 API: {e}", file=sys.stderr)
        return 1
    if not routes:
        print("ERROR: API returned zero Frequent Bus routes — refusing to "
              "overwrite (likely an upstream schema change).", file=sys.stderr)
        return 1

    prev = load_previous()
    if prev is None:
        # Cold start: establish a baseline, don't report the whole network as
        # "added" (that would light up the dashboard on first ever run).
        changes = {"added": [], "dropped": [], "endpoint_changed": []}
        print("(cold start — recording baseline, no changes reported)")
    else:
        changes = diff_routes(prev.get("routes"), routes)
    has_change = bool(changes["added"] or changes["dropped"] or changes["endpoint_changed"])

    # Keep the timestamp of the last real change so the dashboard can show
    # "changed 3d ago" until the next weekly run, rather than clearing instantly.
    last_change_at = now if has_change else (prev.get("last_change_at") if prev else None)

    coverage = map_coverage(routes, drawn_bus_routes())

    out = {
        "schema": SCHEMA,
        "generated_at": now,
        "source": "MBTA V3 API /routes filter[type]=3, description='Frequent Bus'",
        "count": len(routes),
        "routes": routes,
        "changes": changes,
        "last_change_at": last_change_at,
        "map": coverage,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")

    print(f"Wrote {OUT.relative_to(ROOT)} — {len(routes)} frequent routes.")
    if has_change:
        print("  CHANGES since last run:")
        if changes["added"]:
            print(f"    + added:   {', '.join(changes['added'])}")
        if changes["dropped"]:
            print(f"    - dropped: {', '.join(changes['dropped'])}")
        for c in changes["endpoint_changed"]:
            print(f"    ~ {c['short_name']}: '{c['was']}' -> '{c['now']}'")
    else:
        print("  No change since last run.")
    if coverage["tracking"]:
        if coverage["missing_from_map"]:
            print(f"  Not yet drawn on map: {', '.join(coverage['missing_from_map'])}")
        if coverage["drawn_not_frequent"]:
            print(f"  Drawn but NO LONGER frequent: {', '.join(coverage['drawn_not_frequent'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
