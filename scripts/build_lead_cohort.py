#!/usr/bin/env python3
"""Build data_lead_cohort.json — TRUE lead cohort by LEAD-CREATION week & channel.

Answers the demand-owner question the old booking-week lead-age data couldn't:
  "Of the leads that came in THIS week, how many booked? — by channel, with the lag."

Per clinic, per channel, indexed by lead-creation week (newest-first, 12 weeks):
  leads  = leads created that week
  booked = of those, how many have booked a call (ever — call_booking_ts not null)
  same   = booked in the same week the lead came in
  nextw  = booked the following week (1-wk lag)
  later  = booked 2+ weeks later (backlog)

Conversion = booked / leads (≤100%, a real cohort). Recent weeks read low because those
leads haven't had time to book yet (maturation) — the UI flags this.

Keyed "City|Clinic". Run: AWS_PROFILE=redshift-data python3 scripts/build_lead_cohort.py"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27",
         "2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23","2026-03-16"]
idx = {w: i for i, w in enumerate(WEEKS)}
CHANS = ["gmb", "google_ad", "organic", "fb", "justdial", "others"]
FIELDS = ["leads", "booked", "same", "nextw", "later", "inb_leads", "inb_booked"]


def main():
    sql = open(os.path.join(ROOT, "scripts", "fetch_lead_cohort.sql")).read()
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                       input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in p.stderr:
        sys.stderr.write("fetch_lead_cohort.sql failed: " + (p.stderr or "")[:300] + "\n"); sys.exit(1)
    D = {}
    for line in p.stdout.strip().splitlines():
        c = line.split("\t")
        if len(c) < 9: continue
        city, clinic, wk, chan = c[0], c[1], c[2], c[3]
        if wk not in idx or chan not in CHANS: continue
        key = f"{city}|{clinic}"
        o = D.setdefault(key, {ch: {f: [0]*12 for f in FIELDS} for ch in CHANS})
        i = idx[wk]
        for j, f in enumerate(FIELDS):
            try: o[chan][f][i] += int(float(c[4+j]))
            except (ValueError, IndexError): pass
    # ── NETWORK true cohort (no clinic-location filter → keeps unbooked leads → real conversion) ──
    net_sql = open(os.path.join(ROOT, "scripts", "fetch_lead_cohort_net.sql")).read()
    pn = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                        input=net_sql, capture_output=True, text=True)
    NET = {ch: {f: [0]*12 for f in FIELDS} for ch in CHANS}
    if pn.returncode == 0 and "ERROR" not in pn.stderr:
        for line in pn.stdout.strip().splitlines():
            c = line.split("\t")
            if len(c) < 9: continue
            wk, chan = c[0], c[1]
            if wk not in idx or chan not in CHANS: continue
            i = idx[wk]
            for j, f in enumerate(FIELDS):
                try: NET[chan][f][i] += int(float(c[2+j]))
                except (ValueError, IndexError): pass
    else:
        sys.stderr.write("WARN network cohort query failed; network omitted\n")
    # Practo (external — not in main_source_wise_leads): fold in from data_practo_conv.json (cohort leads/booked)
    practo = {f: [0]*12 for f in FIELDS}
    try:
        PC = json.load(open(os.path.join(ROOT, "data_practo_conv.json")))
        for k, o in PC.items():
            if k == "_meta": continue
            for i in range(12):
                practo["leads"][i] += (o.get("leads") or [0]*12)[i]
                practo["booked"][i] += (o.get("booked") or [0]*12)[i]
    except Exception as e:
        sys.stderr.write(f"WARN practo fold-in skipped: {e}\n")
    NET["practo"] = practo

    # ── BOOKING ATTRIBUTION (network): bookings by booking-week × channel × lead-age (0/1/2/3+ wks) ──
    ba_sql = open(os.path.join(ROOT, "scripts", "fetch_book_attr.sql")).read()
    pb = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "redshift_query.py")],
                        input=ba_sql, capture_output=True, text=True)
    BA = {ch: {f"a{a}": [0]*12 for a in range(5)} for ch in CHANS}   # a0=same wk … a4=4+ weeks back
    if pb.returncode == 0 and "ERROR" not in pb.stderr:
        for line in pb.stdout.strip().splitlines():
            c = line.split("\t")
            if len(c) < 4: continue
            wk, chan, age = c[0], c[1], c[2]
            if wk not in idx or chan not in CHANS: continue
            try: BA[chan][f"a{int(age)}"][idx[wk]] += int(float(c[3]))
            except (ValueError, IndexError, KeyError): pass
    else:
        sys.stderr.write("WARN booking-attribution query failed; _bookattr omitted\n")

    out = {"_meta": {"source": "production.public.main_source_wise_leads — lead cohort by CREATION week & channel",
                     "weeks": WEEKS, "chans": CHANS,
                     "fields": "leads=created that wk · booked=of those, ever booked · same/nextw/later=booking lag · inb_*=PC-Inbound (phoned us) · conv=booked/leads (recent wks still maturing)",
                     "network_note": "_network = TRUE cohort (all digital leads, no clinic filter) by channel+inbound; per-clinic entries are clinic-engaged leads only (≈booked)."}}
    out["_network"] = NET
    out["_bookattr"] = BA
    out.update(D)
    json.dump(out, open(os.path.join(ROOT, "data_lead_cohort.json"), "w"), separators=(",", ":"))

    # network roll-up for a sanity print
    netL = [0]*12; netB = [0]*12
    for k, o in D.items():
        for ch in CHANS:
            for i in range(12):
                netL[i] += o[ch]["leads"][i]; netB[i] += o[ch]["booked"][i]
    conv = [round(netB[i]/netL[i]*100) if netL[i] else 0 for i in range(12)]
    print(f"data_lead_cohort.json · {len(D)} clinics")
    print("network leads/wk (by lead week):", netL)
    print("network booked/wk             :", netB)
    print("cohort conv % (matures→older) :", conv, " — newest weeks read low (still maturing)")


if __name__ == "__main__":
    main()
