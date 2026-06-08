#!/usr/bin/env python3
"""Build data_practo_booked.json — TRUE Practo bookings per clinic/week.

A booking counts as Practo if the patient's phone matches a phone in the Practo lead sheet
(same phone-match attribution build_clinic_data.py uses). This captures phone follow-up
conversions, not just Practo's own online slot-booking timestamp.

Keyed "City|Clinic", arrays newest-first aligned to the diagnostic's 12 Monday-weeks.
Run: python3 scripts/build_practo_booked.py   (needs AWS SSO)"""
import os, sys, io, csv, json, subprocess, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS=["2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27","2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16"]
idx = {w:i for i,w in enumerate(WEEKS)}
PRACTO_SHEET_ID  = "1pTPQgdSUaomRuj_49dARVJ4Vtiy34uE73X4gqqkwlaE"   # same sheet build_clinic_data uses
PRACTO_SHEET_TAB = "Practo"

def norm_phone(raw):
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 12 and digits.startswith("91"): return "+"+digits
    if len(digits) == 11 and digits.startswith("91"): return "+"+digits
    if len(digits) == 10: return "+91"+digits
    return None

def load_practo_phones():
    url = f"https://docs.google.com/spreadsheets/d/{PRACTO_SHEET_ID}/export?format=csv&sheet={PRACTO_SHEET_TAB}"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", errors="replace")
    phones, col = set(), None
    for i, row in enumerate(csv.reader(io.StringIO(raw))):
        if i == 0:
            for ci, h in enumerate(row):
                if "phone" in h.lower() and "patient" in h.lower(): col = ci; break
            if col is None: col = 9
            continue
        if not row or len(row) <= col: continue
        p = norm_phone(row[col])
        if p: phones.add(p)
    return phones

def main():
    phones = load_practo_phones()
    if not phones:
        sys.stderr.write("no Practo phones loaded — aborting\n"); sys.exit(1)
    print(f"Practo phones: {len(phones):,}")
    sql = open(os.path.join(ROOT,"scripts","fetch_practo_booked.sql")).read()
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                       input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in p.stderr:
        sys.stderr.write("fetch_practo_booked.sql failed: "+(p.stderr or "")[:300]+"\n"); sys.exit(1)
    D, matched, total = {}, 0, 0
    for line in p.stdout.strip("\n").splitlines():
        c = line.split("\t")
        if len(c) < 4: continue
        city, clinic, wk, phone = c[0], c[1], c[2], c[3]
        if wk not in idx: continue
        total += 1
        if norm_phone(phone) in phones:
            matched += 1
            D.setdefault(f"{city}|{clinic}", [0]*12)[idx[wk]] += 1
    out = {"_meta":{"source":"allo_consultations.appointments (Screening Call) × Practo-sheet phone match",
                    "weeks":WEEKS, "note":"TRUE Practo bookings incl. phone follow-up; a booking is Practo if the patient phone is in the Practo lead sheet."}}
    out.update(D)
    json.dump(out, open(os.path.join(ROOT,"data_practo_booked.json"),"w"), separators=(",",":"))
    print(f"data_practo_booked.json · {len(D)} clinics · {matched:,}/{total:,} bookings matched Practo")
    b = D.get("Bangalore|Bellandur")
    if b: print("Bellandur true Practo booked (newest-first):", b)

if __name__ == "__main__":
    main()
