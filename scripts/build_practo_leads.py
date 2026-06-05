#!/usr/bin/env python3
"""Build data_practo_leads.json — Practo profile leads (and online slot-booked) per clinic/week,
from the RD_Practo_Leads Google Sheet. This replaces the dashboard's fragile LIVE in-browser
sheet fetch (which silently drops the Practo-leads line whenever the Sheets CSV endpoint hiccups),
making Practo leads as robust as every other static data file.

Mirrors the client-side parsePracto(): Date col0 (DD-MM-YYYY) → Monday week; Slot Booked TS col4
(valid year >= 2000, not 1899) ⇒ online slot-booked. Keyed "City|Clinic" = {leads:[12], booked:[12]}.
Run: python3 scripts/build_practo_leads.py   (no auth — public sheet)"""
import os, sys, csv, io, json, re, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEET_ID = "1bZWGVKu6b4EFPDt3aKHn21gYjdhN1aT1-LT60BFe8g0"
SHEET_TAB = "RD_Practo_Leads"
WEEKS = ["2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20",
         "2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16","2026-03-09"]
idx = {w:i for i,w in enumerate(WEEKS)}

def main():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(SHEET_TAB)}"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        rows = list(csv.reader(io.StringIO(r.read().decode("utf-8", errors="replace"))))
    D = {}
    for c in rows[1:]:
        if len(c) < 9: continue
        p = (c[0] or "").strip().split("-")            # DD-MM-YYYY
        if len(p) != 3: continue
        try: dt = datetime.date(int(p[2]), int(p[1]), int(p[0]))
        except (ValueError, TypeError): continue
        mon = (dt - datetime.timedelta(days=dt.weekday())).isoformat()   # Monday
        if mon not in idx: continue
        clinic, city = (c[7] or "").strip(), (c[8] or "").strip()
        if not clinic: continue
        o = D.setdefault(f"{city}|{clinic}", {"leads":[0]*12, "booked":[0]*12})
        i = idx[mon]; o["leads"][i] += 1
        bts = (c[4] or "").strip(); m = re.search(r"(\d{4})", bts)
        if bts and "1899" not in bts and m and int(m.group(1)) >= 2000: o["booked"][i] += 1
    out = {"_meta":{"source":"RD_Practo_Leads sheet (static build — replaces fragile live fetch)",
                    "weeks":WEEKS, "fields":"leads=Practo profile leads/wk; booked=Practo online slot-booked (Slot Booked TS)"}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_practo_leads.json"),"w"), separators=(",",":"))
    print(f"data_practo_leads.json · {len(D)} clinics")
    v = D.get("Chennai|Velachery")
    if v: print("Chennai|Velachery leads (newest-first):", v["leads"])

if __name__ == "__main__":
    main()
