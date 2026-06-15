#!/usr/bin/env python3
"""Build data_practo_conv.json — TRUE Practo lead→book *cohort* conversion per clinic/week (+doctor).

Why this exists: the old Practo "Lead → Book %" divided phone-matched true bookings (counted by
BOOKING week, all-time phone universe, incl. reschedules & out-of-window leads) by that week's NEW
profile leads — a stock ÷ flow mismatch that produced impossible >100% conversions (Bangalore 121%,
Hyderabad 130%). This builder instead computes a proper cohort funnel from ONE consistent universe:

  • Leads  = distinct Practo lead phones in the rich Practo connections sheet (1pTPQgd), by LEAD week.
  • Booked = those same phones that booked a Screening Call in Redshift (any time in the window).
  • conv   = booked / leads  → always ≤ 100% (each lead either booked or not).

Result is stable & believable (~67%/wk network). Recent weeks read slightly low because their leads
are still maturing (haven't had time to book yet) — the UI notes this.

Keyed "City|Clinic" = {leads:[12], booked:[12]} newest-first; doctors in data_practo_conv_by_doctor.json.
Run: AWS_PROFILE=redshift-data python3 scripts/build_practo_conv.py   (needs AWS SSO + public sheet)"""
import os, sys, io, csv, json, datetime, subprocess, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27",
         "2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
idx = {w: i for i, w in enumerate(WEEKS)}
# Rich Practo connections export (same sheet build_practo_booked uses for the phone universe).
# Cols: 1 Date(lead, DD-MM-YYYY) · 4 Practice Locality(clinic) · 5 Practice City · 6 Doctor Name · 9 Patient_Phone_Number
PRACTO_SHEET_ID  = "1pTPQgdSUaomRuj_49dARVJ4Vtiy34uE73X4gqqkwlaE"
PRACTO_SHEET_TAB = "Practo"
WIN_START, WIN_END = "2026-03-16", "2026-06-09"   # booked-phone window (covers the 12 lead-weeks + a little maturation)

BOOKED_PHONES_SQL = f"""SELECT DISTINCT p.phone_no
FROM allo_consultations.appointments a
JOIN allo_consultations.consultations c ON a.consultation_id=c.id
JOIN allo_persons.patient p ON c.patient_id=p.id
WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL
  AND c.consultation_type_id=(SELECT id FROM allo_consultations.types WHERE name='Screening Call')
  AND DATE(a.start_time + INTERVAL '5.5 hours') BETWEEN '{WIN_START}' AND '{WIN_END}'
  AND p.phone_no IS NOT NULL AND p.phone_no<>'';"""


def norm_phone(raw):
    d = "".join(c for c in str(raw) if c.isdigit())
    if len(d) == 12 and d.startswith("91"): return "+" + d
    if len(d) == 11 and d.startswith("91"): return "+" + d
    if len(d) == 10: return "+91" + d
    return None


def monday(s):
    s = (s or "").strip().split()[0] if s else ""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            dt = datetime.datetime.strptime(s, fmt).date()
            return (dt - datetime.timedelta(days=dt.weekday())).isoformat()
        except ValueError:
            pass
    return None


def load_booked_phones():
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                       input=BOOKED_PHONES_SQL, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in p.stderr:
        sys.stderr.write("booked-phones query failed: " + (p.stderr or "")[:300] + "\n"); sys.exit(1)
    phones = set()
    for line in p.stdout.strip("\n").splitlines():
        ph = norm_phone(line.strip())
        if ph: phones.add(ph)
    return phones


def load_practo_rows():
    url = f"https://docs.google.com/spreadsheets/d/{PRACTO_SHEET_ID}/export?format=csv&sheet={PRACTO_SHEET_TAB}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return list(csv.reader(io.StringIO(r.read().decode("utf-8", errors="replace"))))


def main():
    booked = load_booked_phones()
    print(f"Redshift booked phones (Screening Call, {WIN_START}→{WIN_END}): {len(booked):,}")
    rows = load_practo_rows()
    print(f"Practo connections sheet rows: {len(rows)-1:,}")

    D, BYDOC = {}, {}
    seen = set()  # (week, phone) — count each lead phone once per week (distinct leads)
    netL = [0] * 12; netB = [0] * 12
    for r in rows[1:]:
        if len(r) < 10: continue
        wk = monday(r[1])
        if wk not in idx: continue
        ph = norm_phone(r[9])
        if not ph: continue
        clinic, city, doc = (r[4] or "").strip(), (r[5] or "").strip(), (r[6] or "").strip() or "(unassigned)"
        if not clinic: continue
        i = idx[wk]
        key = (wk, ph)
        if key in seen:  # same phone, same week → one lead
            continue
        seen.add(key)
        did_book = ph in booked
        o = D.setdefault(f"{city}|{clinic}", {"leads": [0]*12, "booked": [0]*12})
        o["leads"][i] += 1
        if did_book: o["booked"][i] += 1
        dd = BYDOC.setdefault(f"{city}|{clinic}", {}).setdefault(doc, {"leads": [0]*12, "booked": [0]*12})
        dd["leads"][i] += 1
        if did_book: dd["booked"][i] += 1
        netL[i] += 1; netB[i] += (1 if did_book else 0)

    meta = {"source": "Practo connections sheet (1pTPQgd) lead phones × Redshift Screening-Call bookings",
            "weeks": WEEKS,
            "note": "COHORT lead→book: of distinct Practo lead phones in a week, the % that booked a Screening Call (any time in window). Always ≤100%. Recent weeks read low — leads still maturing."}
    out = {"_meta": meta}; out.update(D)
    json.dump(out, open(os.path.join(ROOT, "data_practo_conv.json"), "w"), separators=(",", ":"))
    docOut = {"_meta": meta}; docOut.update(BYDOC)
    json.dump(docOut, open(os.path.join(ROOT, "data_practo_conv_by_doctor.json"), "w"), separators=(",", ":"))

    conv = [round(netB[i]/netL[i]*100) if netL[i] else 0 for i in range(12)]
    print(f"data_practo_conv.json · {len(D)} clinics · {len(BYDOC)} clinic-doctor groups")
    print("network cohort leads/wk :", netL)
    print("network cohort booked/wk:", netB)
    print("network cohort conv %   :", conv, f" (avg {round(sum(netB)/max(1,sum(netL))*100)}%)")


if __name__ == "__main__":
    main()
