#!/usr/bin/env python3
"""Build a California ZIP (ZCTA) -> state legislative district lookup from the Census Bureau's relationship files.

Usage: build_zip_lookup.py <sldl file> <sldu file> <out.json>
Each input is the pipe-delimited ZCTA-to-district overlap file. For each ZIP the output lists the Assembly (A) and
Senate (S) districts it overlaps with the share of the ZIP's land area in each: {"90210": {"A": [[24, 0.71], ...], "S": [...]}}.
Area share is not population share, and ZIP areas are approximations of mail routes, so the site presents these as
likelihoods and points people to the official address lookup for a definite answer.
"""
import csv, json, sys
from collections import defaultdict

CA = "06"


def read(path, chamber_col_prefix):
    out = defaultdict(dict)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = csv.DictReader(fh, delimiter="|")
        cols = rows.fieldnames or []
        zcol = next(c for c in cols if c.startswith("GEOID_ZCTA5"))
        dcol = next(c for c in cols if c.startswith(f"GEOID_{chamber_col_prefix}"))
        acol = next(c for c in cols if c.startswith("AREALAND_PART"))
        for r in rows:
            geoid, z = (r.get(dcol) or "").strip(), (r.get(zcol) or "").strip()
            if not z or not geoid.startswith(CA):
                continue
            district = geoid[len(CA):]
            if not district.isdigit():  # "ZZZ" = not assigned to any district (water, etc.)
                continue
            out[z][int(district)] = out[z].get(int(district), 0) + int(r.get(acol) or 0)
    return out


def main():
    lower, upper, dest = sys.argv[1:4]
    result = {}
    for chamber, path, prefix in (("A", lower, "SLDL"), ("S", upper, "SLDU")):
        for z, parts in read(path, prefix).items():
            total = sum(parts.values()) or 1
            ranked = sorted(((d, a / total) for d, a in parts.items()), key=lambda x: -x[1])
            kept = [[d, round(s, 3)] for d, s in ranked if s >= 0.02]
            if kept:
                result.setdefault(z, {})[chamber] = kept
    with open(dest, "w") as fh:
        json.dump(result, fh, separators=(",", ":"), sort_keys=True)
    multi = sum(1 for v in result.values() if len(v.get("A", [])) > 1 or len(v.get("S", [])) > 1)
    print(f"{len(result)} California ZIPs; {multi} span more than one district")


if __name__ == "__main__":
    main()
