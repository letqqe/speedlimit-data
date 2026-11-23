#!/usr/bin/env python3
"""Print a GitHub Actions matrix ({"include": [...]}) of leaf Geofabrik regions with a PBF file.

Leaf = a region no other region lists as its parent. Regions whose PBF is larger than
MAX_BYTES (40 GB, bigger than the runner's scratch disk) are skipped (they cannot be processed on a free runner or stored under GitHub's
2 GB per-file limit); each skip is printed to stderr.
Usage: list_regions.py --offset 0 --count 256
"""
import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

INDEX = "https://download.geofabrik.de/index-v1.json"
MAX_BYTES = 40 * 1024**3


def size_of(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0  # unknown size: keep it, the build step will report any real failure


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--count", type=int, default=256)
    ap.add_argument("--done", help="file with release asset names; regions already published are skipped")
    args = ap.parse_args()

    done_names = set()
    if args.done:
        with open(args.done, encoding="utf-8") as f:
            done_names = {line.strip() for line in f if line.strip()}

    with urllib.request.urlopen(INDEX, timeout=60) as r:
        feats = json.load(r)["features"]
    parents = {f["properties"].get("parent") for f in feats}
    leaves = []
    for f in feats:
        p = f["properties"]
        pbf = (p.get("urls") or {}).get("pbf")
        if pbf and p["id"] not in parents:
            # IDs are used as file names and as app keys, so "us/alabama" becomes "us-alabama".
            leaves.append({"id": p["id"].replace("/", "-"), "url": pbf})
    leaves.sort(key=lambda x: x["id"])

    with ThreadPoolExecutor(max_workers=16) as ex:
        sizes = list(ex.map(lambda x: size_of(x["url"]), leaves))
    kept = []
    for leaf, size in zip(leaves, sizes):
        if size > MAX_BYTES:
            print(f"skip {leaf['id']}: {size / 1024**3:.1f} GB", file=sys.stderr)
        else:
            kept.append(leaf)

    def published(region_id):
        # a region is done when its entry is on the release, unsplit or as grid cells
        if f"entry-{region_id}.json" in done_names:
            return True
        pat = re.compile(rf"entry-{re.escape(region_id)}-r\d+c\d+\.json")
        return any(pat.fullmatch(n) for n in done_names)

    todo = [r for r in kept if not published(r["id"])]
    print(f"{len(kept)} buildable, {len(kept) - len(todo)} already published, {len(todo)} to build", file=sys.stderr)
    chunk = todo[args.offset:args.offset + args.count]
    print(f"this run: {len(chunk)}", file=sys.stderr)
    print(json.dumps({"include": chunk}))


if __name__ == "__main__":
    main()
