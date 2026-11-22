#!/usr/bin/env python3
"""Merge entry-*.json files into one manifest.json (a JSON array sorted by id)."""
import glob
import json
import sys


def main():
    src_dir, out = sys.argv[1], sys.argv[2]
    entries = [json.load(open(p, encoding="utf-8")) for p in glob.glob(f"{src_dir}/entry-*.json")]
    entries.sort(key=lambda e: e["id"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(entries, f)
    print(f"{len(entries)} regions -> {out}")


if __name__ == "__main__":
    main()
