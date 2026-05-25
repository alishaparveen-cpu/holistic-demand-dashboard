"""
GMB profile audit: join the GMB listings (parsed from Business Manager UI) against
the STI-share data per clinic. Test whether business-title patterns correlate with
STI share, and surface profile-level issues (Pending edits, Suspended, missing
descriptors).

Source files:
  sti_share.csv      — clinic, city, avg_sti_pct, sti_calls, total_calls
  raw_listings.txt   — store_code \t title \t address \t status   (66 rows)
"""

from __future__ import annotations

import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def load_sti() -> list[dict]:
    rows = []
    with open(HERE / "sti_share.csv") as f:
        for r in csv.DictReader(f):
            r["avg_sti_pct"] = float(r["avg_sti_pct"]) if r["avg_sti_pct"] else None
            r["sti_calls"] = int(r["sti_calls"])
            r["total_calls"] = int(r["total_calls"])
            rows.append(r)
    return rows


def load_listings() -> list[dict]:
    rows = []
    with open(HERE / "raw_listings.txt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            store_code, title, address, status = parts[:4]
            rows.append({
                "store_code": store_code,
                "title": title,
                "address": address,
                "status": status,
            })
    return rows


def classify_title(title: str) -> dict:
    """Bucket the title format into discrete categories."""
    t = title.lower()
    return {
        "has_sti_or_std": ("sti" in t) or ("std" in t),
        "has_sti_explicit": "sti" in t,
        "has_std": "std" in t,
        "has_hiv": "hiv" in t,
        "has_sexologist": "sexologist" in t,
        "has_sex_clinic": "sex clinic" in t,
        "has_sexual_health": "sexual health" in t,
        "has_mental_health": "mental" in t,
        "has_sex_doctor": "sex doctor" in t or "sex doctors" in t,
        "has_specialist": "specialist" in t,
        "has_testing": "testing" in t,
        "minimal": (t.count(" ") < 4 or t.count("|") == 0 and t.count("-") == 0),
        "uses_pipe_format": "|" in t,
        "title_len": len(title),
    }


def match_sti_to_listing(sti_rows: list[dict], listings: list[dict]) -> list[dict]:
    """
    Match each STI-share row to a GMB listing by clinic-name substring.
    Match priority: clinic name in title, then clinic name in address.
    Returns one row per STI clinic with the matched listing fields (or None).
    """
    out = []
    used = set()
    for s in sti_rows:
        clinic_lc = s["clinic"].lower()
        # Strategy: substring match against title first, then address.
        best = None
        for L in listings:
            if L["store_code"] in used:
                continue
            if clinic_lc in L["title"].lower():
                best = L
                break
        if best is None:
            for L in listings:
                if L["store_code"] in used:
                    continue
                if clinic_lc in L["address"].lower():
                    best = L
                    break
        if best:
            used.add(best["store_code"])
            tc = classify_title(best["title"])
            out.append({**s, **tc, "title": best["title"], "status": best["status"], "store_code": best["store_code"]})
        else:
            out.append({**s, "title": None, "status": None, "store_code": None})
    return out


def buckets(rows: list[dict]) -> dict[str, list[dict]]:
    """Bucket by STI share tier; exclude no-volume rows from analysis."""
    active = [r for r in rows if r["avg_sti_pct"] is not None and r["total_calls"] >= 10]
    top = [r for r in active if r["avg_sti_pct"] >= 28]
    mid = [r for r in active if 12 <= r["avg_sti_pct"] < 28]
    low = [r for r in active if r["avg_sti_pct"] < 12]
    return {"top": top, "mid": mid, "low": low}


def pct_with(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    return 100 * sum(1 for r in rows if r.get(key)) / len(rows)


def report(rows: list[dict]):
    b = buckets(rows)
    print("=" * 70)
    print(f"BUCKET COUNTS")
    print(f"  Top (≥28% STI):     n={len(b['top']):2d}  avg STI%={statistics.mean(r['avg_sti_pct'] for r in b['top']):.1f}%")
    print(f"  Mid (12–28%):       n={len(b['mid']):2d}  avg STI%={statistics.mean(r['avg_sti_pct'] for r in b['mid']):.1f}%")
    print(f"  Low (<12%):         n={len(b['low']):2d}  avg STI%={statistics.mean(r['avg_sti_pct'] for r in b['low']) if b['low'] else 0:.1f}%")
    print()

    flags = [
        ("Title mentions STI or STD",        "has_sti_or_std"),
        ("Title mentions 'STI' explicitly",  "has_sti_explicit"),
        ("Title mentions 'STD'",             "has_std"),
        ("Title mentions 'Testing'",         "has_testing"),
        ("Title mentions 'Specialist'",      "has_specialist"),
        ("Title mentions 'Sexologist'",      "has_sexologist"),
        ("Title mentions 'Sex Clinic'",      "has_sex_clinic"),
        ("Title uses pipe-separated format", "uses_pipe_format"),
    ]
    print(f"{'Flag':<42} {'Top':>10} {'Mid':>10} {'Low':>10}")
    print("-" * 72)
    for label, key in flags:
        print(f"{label:<42} {pct_with(b['top'], key):>9.0f}% {pct_with(b['mid'], key):>9.0f}% {pct_with(b['low'], key):>9.0f}%")
    print()

    # Title-length comparison
    def avg_len(r):
        lens = [x["title_len"] for x in r if x.get("title_len")]
        return statistics.mean(lens) if lens else 0
    print(f"{'Avg title length (chars)':<42} {avg_len(b['top']):>9.0f}  {avg_len(b['mid']):>9.0f}  {avg_len(b['low']):>9.0f}")
    print()

    # Status issues
    print("STATUS ISSUES (Suspended / Pending edits / Unmatched):")
    for tier_name, tier_rows in b.items():
        bad = [r for r in tier_rows if r.get("status") in ("Suspended", "Pending edits")]
        unmatched = [r for r in tier_rows if r.get("title") is None]
        if bad or unmatched:
            print(f"  {tier_name.upper()}:")
            for r in bad:
                print(f"    {r['clinic']:<25} {r['city']:<15} {r['avg_sti_pct']:>5.0f}%  STATUS={r['status']}")
            for r in unmatched:
                print(f"    {r['clinic']:<25} {r['city']:<15} {r['avg_sti_pct']:>5.0f}%  UNMATCHED in GMB list")
    print()


def per_clinic_lowtier(rows: list[dict]):
    """Dump each low-tier clinic with its title for visual scan."""
    low = [r for r in rows if r["avg_sti_pct"] is not None and r["avg_sti_pct"] < 12 and r["total_calls"] >= 10]
    print("=" * 70)
    print(f"LOW-TIER CLINICS (STI < 12%, ≥10 calls)  n={len(low)}")
    print("=" * 70)
    low.sort(key=lambda r: r["avg_sti_pct"])
    for r in low:
        print(f"\n  {r['clinic']} ({r['city']})  STI={r['avg_sti_pct']:.0f}% ({r['sti_calls']}/{r['total_calls']})")
        print(f"    STATUS: {r.get('status', 'unmatched')}")
        if r.get("title"):
            print(f"    TITLE:  {r['title']}")
        else:
            print("    TITLE:  (no GMB listing matched)")


def per_clinic_toptier(rows: list[dict]):
    """Top performers — show what titles look like."""
    top = [r for r in rows if r["avg_sti_pct"] is not None and r["avg_sti_pct"] >= 28]
    print("=" * 70)
    print(f"TOP-TIER CLINICS (STI ≥ 28%)  n={len(top)}")
    print("=" * 70)
    top.sort(key=lambda r: -r["avg_sti_pct"])
    for r in top:
        print(f"\n  {r['clinic']} ({r['city']})  STI={r['avg_sti_pct']:.0f}% ({r['sti_calls']}/{r['total_calls']})")
        print(f"    STATUS: {r.get('status', 'unmatched')}")
        print(f"    TITLE:  {r.get('title', '(unmatched)')}")


def main():
    sti = load_sti()
    listings = load_listings()
    print(f"Loaded {len(sti)} STI rows, {len(listings)} GMB listings")
    print()
    joined = match_sti_to_listing(sti, listings)
    matched = sum(1 for r in joined if r.get("title"))
    print(f"Matched: {matched}/{len(joined)}")
    print()
    report(joined)
    per_clinic_toptier(joined)
    per_clinic_lowtier(joined)


if __name__ == "__main__":
    main()
