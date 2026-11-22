#!/usr/bin/env python3
"""Write one manifest entry for a built region database."""
import argparse
import json
import os
import sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    meta = dict(sqlite3.connect(args.db).execute("SELECT key, value FROM meta").fetchall())
    south, west, north, east = (float(x) for x in meta["bounds"].split(","))
    entry = {
        "id": meta["region"],
        "url": args.url,
        "south": south, "west": west, "north": north, "east": east,
        "bytes": os.path.getsize(args.db),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(entry, f)


if __name__ == "__main__":
    main()
