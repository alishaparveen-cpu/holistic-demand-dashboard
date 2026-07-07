#!/usr/bin/env python3
"""Overview builder — the attribution story in three views (call leads):
  ① correct   : leads whose system utm_source was already right (untouched), by channel
  ② corrections: per exotel number we overrode — which line, system said X, we attributed Y
  ③ final     : final channels after corrections
Emits data_overview.json: weeks, correct{wk:{ch:[c,b]}}, final{wk:{ch:[c,b]}},
  corrections:[{number,note,sys,our,wk:{<wk>:[c,b]}}]
Run: AWS_PROFILE=redshift-data python3 scripts/build_overview.py
"""
import os, sys, json, csv, subprocess
from collections import defaultdict, Counter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
OVR = os.path.join(ROOT, "number_source_overrides.csv")
OUT = os.path.join(ROOT, "data_overview.json")
FLOOR = "2026-05-01"

SQL = """
WITH caller AS (SELECT pid, call_wk, ph10, exonum FROM (
    SELECT ec.user_id pid, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date call_wk,
      RIGHT(p.phone_no,10) ph10, ec.exotel_number exonum,
      ROW_NUMBER() OVER (PARTITION BY ec.user_id, DATE_TRUNC('week',DATEADD(minute,330,ec.created_at)) ORDER BY ec.created_at) rn
    FROM allo_prod.allo_vendors.exotel_calls ec JOIN allo_prod.allo_persons.patient p ON p.id=ec.user_id
    WHERE ec.direction IN ('inbound','incoming') AND ec.routed_to='lead_to_call' AND ec.exotel_number!='08071176846'
      AND ec.user_id IS NOT NULL AND DATE_TRUNC('week',DATEADD(minute,330,ec.created_at))::date>='{floor}') WHERE rn=1),
 crm AS (SELECT ph10, us FROM (SELECT RIGHT(phone_no,10) ph10, LOWER(CAST(utm_source AS VARCHAR)) us,
          ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY updated_at DESC NULLS LAST) rn
        FROM allo_prod.allo_persons.lead WHERE phone_no IS NOT NULL) WHERE rn=1),
 bka AS (SELECT patient_id pid, DATE_TRUNC('week',DATEADD(minute,330,MIN(created_at)))::date bwk FROM allo_prod.allo_consultations.appointments WHERE deleted_at IS NULL GROUP BY 1),
 fl AS (SELECT RIGHT(phone_no1,10) ph10, DATE_TRUNC('week',MIN(created_on_date))::date flw FROM production.public.main_source_wise_leads GROUP BY 1)
SELECT TO_CHAR(c.call_wk,'YYYY-MM-DD') week, c.exonum,
  CASE WHEN crm.us IS NULL OR crm.us IN ('','null') THEN '(none)' ELSE crm.us END crm_source,
  CASE WHEN fl.flw IS NULL THEN 'no_lead' WHEN fl.flw<c.call_wk THEN 'earlier' ELSE 'this_wk' END vintage,
  COUNT(DISTINCT c.pid) callers,
  SUM(CASE WHEN b.bwk=c.call_wk THEN 1 ELSE 0 END) booked
FROM caller c LEFT JOIN crm ON crm.ph10=c.ph10 LEFT JOIN bka b ON b.pid=c.pid LEFT JOIN fl ON fl.ph10=c.ph10
GROUP BY 1,2,3,4;
""".replace("{floor}", FLOOR)


def run(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True,
                       env={**os.environ, "AWS_PROFILE": "redshift-data"})
    out = (p.stdout or "").strip()
    if p.returncode != 0 or out.startswith("FAIL") or "Traceback" in (p.stderr or ""):
        sys.exit("query failed:\n" + (p.stderr or out)[-800:])
    return [ln.split("\t") for ln in out.split("\n") if ln.strip() and not ln.startswith("FAIL")]


def norm(s):
    s = (s or "").lower()
    return {"gmb": "GMB", "google": "Google Ads", "fb": "Meta", "practo": "Practo",
            "justdial": "JustDial", "organic": "Organic"}.get(s, "(none)" if s in ("(none)", "", "null") else "Other")


if __name__ == "__main__":
    ov = {}
    for r in csv.DictReader(open(OVR)):
        ov[r["exotel_number"].strip()] = (r["channel"].strip(), r.get("notes", "").strip())
    correct = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    final = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    system = defaultdict(lambda: defaultdict(lambda: [0, 0]))       # RAW system utm, all callers (matches colleague)
    system_tw = defaultdict(lambda: defaultdict(lambda: [0, 0]))    # RAW system utm, THIS-week-lead callers only (→ 1,626)
    final_tw = defaultdict(lambda: defaultdict(lambda: [0, 0]))     # CORRECTED channel, THIS-week-lead callers only (→ 1,626)
    corr = defaultdict(lambda: {"note": "", "our": "", "sys": Counter(), "wk": defaultdict(lambda: [0, 0])})
    for r in run(SQL):
        if len(r) < 6:
            continue
        wk, num, crm, vintage, c, b = r[0], r[1].strip(), r[2], r[3], int(float(r[4])), int(float(r[5]))
        sysch = norm(crm)
        rawch = sysch if sysch != "(none)" else "Direct / Call (blank)"
        system[wk][rawch][0] += c; system[wk][rawch][1] += b
        if vintage == "this_wk":                                    # lead created this week (incl. lead-after)
            system_tw[wk][rawch][0] += c; system_tw[wk][rawch][1] += b
        if num in ov:
            fch = ov[num][0]
            cc = corr[num]; cc["our"] = fch; cc["note"] = ov[num][1]; cc["sys"][crm] += c
            cc["wk"][wk][0] += c; cc["wk"][wk][1] += b
        elif sysch != "(none)":
            fch = sysch
            correct[wk][sysch][0] += c; correct[wk][sysch][1] += b
        else:
            fch = "Undetermined"
        final[wk][fch][0] += c; final[wk][fch][1] += b
        if vintage == "this_wk":
            final_tw[wk][fch][0] += c; final_tw[wk][fch][1] += b
    corrections = []
    for num, cc in corr.items():
        sysv = cc["sys"].most_common(1)[0][0] if cc["sys"] else "(none)"
        corrections.append({"number": num, "note": cc["note"], "sys": sysv, "our": cc["our"], "wk": cc["wk"]})
    weeks = sorted(final.keys())
    json.dump({"weeks": weeks, "system": system, "system_tw": system_tw, "correct": correct,
               "final": final, "final_tw": final_tw, "corrections": corrections},
              open(OUT, "w"), separators=(",", ":"))
    print("weeks", len(weeks), "| corrected numbers", len(corrections))
    print("wrote", OUT)
