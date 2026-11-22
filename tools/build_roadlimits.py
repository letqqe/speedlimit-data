#!/usr/bin/env python3
"""Build a road-limit SQLite database from OpenStreetMap data.

Input: GeoJSON sequence of road LineStrings with `maxspeed` tags, made by
  osmium tags-filter region.osm.pbf w/highway maxspeed
  osmium export -f geojsonseq -o roads.geojsonseq ...
Output: SQLite file in the format described in
  app/.../data/roadlimits/RoadLimitFormat.kt (format version 1).

Data: © OpenStreetMap contributors, ODbL 1.0.
"""
import argparse
import json
import math
import re
import sqlite3
import struct
import sys
from collections import defaultdict

FORMAT_VERSION = 1
TILE_ZOOM = 14
TILE_COUNT = 1 << TILE_ZOOM
RECORD = struct.Struct("<Biiii")  # u8 kmh, then four i32 coordinates * 1e7

NUMBER = re.compile(r"^(\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph|knots?)?$")


def to_kmh(raw):
    """Same rules as OsmSpeedTag.kt."""
    if not raw:
        return None
    s = raw.strip().lower()
    if s == "walk":
        return 7
    m = NUMBER.match(s)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2)
    if unit == "mph":
        v *= 1.609344
    elif unit and unit.startswith("knot"):
        v *= 1.852
    k = round(v)
    return k if 5 <= k <= 200 else None


def tile_x(lng):
    return min(max(math.floor((lng + 180.0) / 360.0 * TILE_COUNT), 0), TILE_COUNT - 1)


def tile_y(lat):
    lat = min(max(lat, -85.05112878), 85.05112878)
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * TILE_COUNT
    return min(max(math.floor(y), 0), TILE_COUNT - 1)


def tile_key(x, y):
    return x * TILE_COUNT + y


def tiles_for_bbox(s, w, n, e):
    """All tile keys touched by a bounding box."""
    x0, x1 = tile_x(w), tile_x(e)
    y0, y1 = tile_y(n), tile_y(s)  # y grows southward
    return [tile_key(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def iter_segments(path):
    f = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            geom = feat.get("geometry") or {}
            if geom.get("type") != "LineString":
                continue
            props = feat.get("properties") or {}
            kmh = to_kmh(props.get("maxspeed"))
            if kmh is None:
                kmh = to_kmh(props.get("maxspeed:forward")) or to_kmh(props.get("maxspeed:backward"))
            if kmh is None:
                continue
            coords = geom["coordinates"]
            # Store each consecutive pair of points as one segment.
            for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:]):
                yield kmh, lat1, lng1, lat2, lng2
    finally:
        if f is not sys.stdin:
            f.close()


EDGE_DEG = 0.001  # ~100 m: roads this close to a cell edge also go into the neighbouring cell


def write_db(path, region, tiles, count, bounds, source):
    out = sqlite3.connect(path)
    out.execute("DROP TABLE IF EXISTS meta")
    out.execute("DROP TABLE IF EXISTS tiles")
    out.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    out.execute("CREATE TABLE tiles (key INTEGER PRIMARY KEY, data BLOB)")
    out.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("format_version", str(FORMAT_VERSION)),
        ("region", region),
        ("source", source),
        ("licence", "ODbL 1.0 (https://opendatacommons.org/licenses/odbl/1-0/)"),
        ("segments", str(count)),
        ("bounds", "%s,%s,%s,%s" % bounds),
    ])
    out.executemany("INSERT INTO tiles VALUES (?, ?)", [(k, bytes(v)) for k, v in tiles.items()])
    out.commit()
    out.execute("VACUUM")
    out.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geojsonseq", help="road GeoJSON sequence, or - for stdin")
    ap.add_argument("out", help="output .sqlite path (for a grid, the cell suffix is added)")
    ap.add_argument("--region", required=True)
    ap.add_argument("--source", default="OpenStreetMap contributors (ODbL)")
    ap.add_argument("--bounds", help="south,west,north,east of the whole region (needed for --grid)")
    ap.add_argument("--grid", help="rows,cols: split the region into cells, one database each")
    args = ap.parse_args()

    if args.grid:
        rows, cols = (int(x) for x in args.grid.split(","))
        s0, w0, n0, e0 = (float(x) for x in args.bounds.split(","))
        cells = []
        for r in range(rows):
            for c in range(cols):
                cs = s0 + (n0 - s0) * r / rows
                cn = s0 + (n0 - s0) * (r + 1) / rows
                cw = w0 + (e0 - w0) * c / cols
                ce = w0 + (e0 - w0) * (c + 1) / cols
                cells.append((f"{args.region}-r{r}c{c}", (cs, cw, cn, ce)))
    else:
        cells = [(args.region, None)]

    tiles = {cid: defaultdict(bytearray) for cid, _ in cells}
    counts = {cid: 0 for cid, _ in cells}
    seen_bounds = [90.0, 180.0, -90.0, -180.0]  # s, w, n, e of what was actually read
    for kmh, a_lat, a_lng, b_lat, b_lng in iter_segments(args.geojsonseq):
        rec = RECORD.pack(kmh, round(a_lat * 1e7), round(a_lng * 1e7), round(b_lat * 1e7), round(b_lng * 1e7))
        s, n = min(a_lat, b_lat), max(a_lat, b_lat)
        w, e = min(a_lng, b_lng), max(a_lng, b_lng)
        seen_bounds = [min(seen_bounds[0], s), min(seen_bounds[1], w), max(seen_bounds[2], n), max(seen_bounds[3], e)]
        for cid, box in cells:
            if box is not None:
                cs, cw, cn, ce = box
                if n < cs - EDGE_DEG or s > cn + EDGE_DEG or e < cw - EDGE_DEG or w > ce + EDGE_DEG:
                    continue
            counts[cid] += 1
            for key in tiles_for_bbox(s, w, n, e):
                tiles[cid][key] += rec

    written = []
    for cid, box in cells:
        path = args.out if not args.grid else args.out.replace(".sqlite", f"-{cid.split('-')[-1]}.sqlite")
        bounds = box if box is not None else tuple(seen_bounds)
        write_db(path, cid, tiles[cid], counts[cid], bounds, args.source)
        written.append(path)
        print(f"{cid}: {counts[cid]} segments in {len(tiles[cid])} tiles -> {path} bounds {bounds}", file=sys.stderr)
    print("\n".join(written))


if __name__ == "__main__":
    main()
