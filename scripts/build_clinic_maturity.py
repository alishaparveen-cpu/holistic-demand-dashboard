#!/usr/bin/env python3
"""Build data_clinic_maturity.json — clinic age bucket per locality, for the Full-funnel 'Clinic age' filter.

Age = weeks since the clinic's FIRST booking in data_sc_bookings (55-wk history). Buckets:
  lt3 (<3 mo) · m3_6 (3-6 mo) · m6_12 (6-12 mo) · gt12 (>1 yr, i.e. booking in the oldest week = >=12mo).
Client-side derivation (no Redshift) — approximates launch date by first booking. Regenerate after re-pulling data_sc_bookings.
Run: python3 scripts/build_clinic_maturity.py   (uses today's date; pass YYYY-MM-DD as arg to pin)
"""
import os, sys, json, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.date.today()


def main():
    d = json.load(open(os.path.join(ROOT, "data_sc_bookings.json")))
    wks, clinics = d["_meta"]["weeks"], d["clinics"]
    out = {}
    for key, o in clinics.items():
        bk = o.get("booked", [])
        first = next((w for i, w in enumerate(wks) if i < len(bk) and bk[i] > 0), None)
        if not first:
            continue
        mo = (TODAY - datetime.date.fromisoformat(first)).days / 30.4
        b = "lt3" if mo < 3 else "m3_6" if mo < 6 else "m6_12" if mo < 12 else "gt12"
        loc = key.split("|", 1)[1] if "|" in key else key
        out[loc] = {"b": b, "mo": round(mo, 1), "fw": first}
    json.dump(out, open(os.path.join(ROOT, "data_clinic_maturity.json"), "w"), separators=(",", ":"))
    from collections import Counter
    c = Counter(v["b"] for v in out.values())
    print(f"data_clinic_maturity.json · {len(out)} clinics · buckets {dict(c)}")


if __name__ == "__main__":
    main()
