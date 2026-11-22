#!/usr/bin/env python3
"""Print a GitHub Actions matrix ({"include": [...]}) of leaf Geofabrik regions with a PBF file.

Leaf = a region that no other region lists as its parent (country or sub-region, not continent).
Usage: list_regions.py --offset 0 --count 256   (GitHub allows at most 256 matrix jobs per run)
"""
import argparse
import json
import urllib.request

INDEX = "https://download.geofabrik.de/index-v1.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--count", type=int, default=256)
    args = ap.parse_args()

    with urllib.request.urlopen(INDEX, timeout=60) as r:
        index = json.load(r)
    feats = index["features"]
    parents = {f["properties"].get("parent") for f in feats}
    leaves = []
    for f in feats:
        p = f["properties"]
        pbf = (p.get("urls") or {}).get("pbf")
        if not pbf or p["id"] in parents:
            continue
        leaves.append({"id": p["id"], "url": pbf})
    leaves.sort(key=lambda x: x["id"])
    chunk = leaves[args.offset:args.offset + args.count]
    print(json.dumps({"include": chunk}))


if __name__ == "__main__":
    main()
