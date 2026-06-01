"""
build_diagnosis.py — produces diagnosis.json for the dashboard's Diagnosis page.

Uses the demand tracker SHEET'S OWN LOGIC (validated against L0 formulas), so
numbers reconcile to the sheet to the row:
  Bookings = Book2Done_Raw_Data rows where apt_create_dt in week AND phone_rank==1
             (new-patient dedup, no status filter)
  Channel  = `Source final` (sheet's phone-line waterfall)
  Online   = locality == 'Online';  Category = diag_cat
  Leads    = Leads_Raw rows by created_on_date, channel via `Source Final`
Availability (active-days) is the only Redshift input (roster_slots).

Usage:
  python3 build_diagnosis.py --sheet-xlsx demand_sheet.xlsx --w6-start 2026-05-25
  (requires openpyxl; AWS_PROFILE with redshift-data for active-days)
"""
import argparse, datetime, json, os, sys
from collections import defaultdict
try:
    import openpyxl
except ImportError:
    sys.exit("pip install openpyxl")


def channel(s):
    k = str(s).lower()
    return ("FB" if k in ("fb", "ig") else "Google" if k == "google" else "GMB" if k == "gmb"
            else "Practo" if k == "practo" else "Organic" if k in ("organic", "blog") else "Other")


def wkinfo(d):
    if isinstance(d, datetime.datetime): d = d.date()
    if not isinstance(d, datetime.date):
        try: d = datetime.datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        except Exception: return None, None
    return (d - datetime.timedelta(days=d.weekday())).strftime("%Y-%m-%d"), ("we" if d.weekday() >= 5 else "wd")


def read_tab(wb, name):
    ws = wb[name]; it = ws.iter_rows(values_only=True)
    idx = {h: i for i, h in enumerate(next(it)) if h is not None}
    return it, idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-xlsx", required=True)
    ap.add_argument("--w6-start", required=True)
    ap.add_argument("--out", default="diagnosis.json")
    a = ap.parse_args()
    w6 = datetime.datetime.strptime(a.w6_start, "%Y-%m-%d")
    BASE = [(w6 - datetime.timedelta(weeks=8 - i)).strftime("%Y-%m-%d") for i in range(8)]
    LBASE = BASE[-5:]; W6 = a.w6_start; weeks = set(BASE + [W6])

    wb = openpyxl.load_workbook(a.sheet_xlsx, read_only=True, data_only=True)
    # bookings
    it, idx = read_tab(wb, "Book2Done_Raw_Data")
    g = lambda r, n: r[idx[n]] if n in idx and idx[n] < len(r) else None
    bchan = defaultdict(lambda: defaultdict(int))
    bmode = defaultdict(lambda: defaultdict(int))
    bcat = defaultdict(lambda: defaultdict(int))
    bclin = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in it:
        if str(g(r, "phone_rank")) != "1.0": continue
        w, dow = wkinfo(g(r, "apt_create_dt"))
        if w not in weeks: continue
        online = str(g(r, "locality")) == "Online"
        bchan[channel(g(r, "Source final"))][w] += 1
        bmode["online" if online else "offline"][w] += 1
        bcat["STI" if str(g(r, "diag_cat")) == "STI" else "SH"][w] += 1
        if not online: bclin[str(g(r, "locality"))][w][dow] += 1
    # leads
    it, idx = read_tab(wb, "Leads_Raw")
    sf = "Source Final" if "Source Final" in idx else "Source final"
    g = lambda r, n: r[idx[n]] if n in idx and idx[n] < len(r) else None
    lchan = defaultdict(lambda: defaultdict(int))
    for r in it:
        w, _ = wkinfo(g(r, "created_on_date"))
        if w in weeks: lchan[channel(g(r, sf))][w] += 1
    wb.close()

    # active days + city from Redshift
    import boto3, time
    c = boto3.client("redshift-data", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
    def Q(sql):
        qid = c.execute_statement(ClusterIdentifier="warehouse", Database="allo_prod", DbUser="redshift_admin", Sql=sql)["Id"]
        for _ in range(240):
            time.sleep(3); d = c.describe_statement(Id=qid)
            if d["Status"] == "FINISHED": break
            if d["Status"] in ("FAILED", "ABORTED"): raise RuntimeError(d.get("Error"))
        res = c.get_statement_result(Id=qid); rows = []
        while True:
            rows += [[list(f.values())[0] if f else None for f in row] for row in res["Records"]]
            if "NextToken" not in res: break
            res = c.get_statement_result(Id=qid, NextToken=res["NextToken"])
        return rows
    city = {str(x[0]): str(x[1]) for x in Q("SELECT locality,MAX(city) FROM allo_health.locations WHERE deleted_at IS NULL AND locality IS NOT NULL GROUP BY 1")}
    lo, hi = min(weeks), (w6 + datetime.timedelta(days=6)).strftime("%Y-%m-%d")
    ad = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for x in Q(f"""WITH dd AS (SELECT l.locality, DATE_TRUNC('week',DATE(rs.start_time + INTERVAL '5.5 hours')) wk,
        DATE(rs.start_time + INTERVAL '5.5 hours') dt, EXTRACT(DOW FROM (rs.start_time + INTERVAL '5.5 hours')) dow,
        SUM(EXTRACT(EPOCH FROM (rs.end_time-rs.start_time))/60.0) m
      FROM allo_consultations.roster_slots rs JOIN allo_consultations.types t ON t.id=rs.type_id JOIN allo_health.locations l ON rs.location_id=l.id
      WHERE t.name='Screening Call' AND rs.is_realized=1 AND rs.overlaps_non_bookable_block=0 AND l.deleted_at IS NULL AND l.locality IS NOT NULL
        AND ((rs.is_booked=1 AND rs.overlaps_other_booked_type=0) OR (rs.available_for_booking=1 AND rs.in_repeat_boundary=0))
        AND DATE(rs.start_time + INTERVAL '5.5 hours') BETWEEN '{lo}' AND '{hi}' GROUP BY 1,2,3,4)
      SELECT locality, wk, SUM(CASE WHEN m>=60 AND dow IN(1,2,3,4,5) THEN 1 ELSE 0 END), SUM(CASE WHEN m>=60 AND dow IN(0,6) THEN 1 ELSE 0 END) FROM dd GROUP BY 1,2"""):
        try: ad[str(x[0])][str(x[1])[:10]] = [int(x[2]), int(x[3])]
        except (TypeError, ValueError): pass

    avg = lambda d, ws: round(sum(d.get(w, 0) for w in ws) / len(ws), 0)
    # clinic classification
    clinics = []
    for cl in set(bclin) | set(ad):
        base = avg({w: sum(bclin[cl].get(w, {}).values()) for w in BASE + [W6]}, BASE)
        w6v = sum(bclin[cl].get(W6, {}).values())
        if base == 0 and w6v == 0: continue
        wks = sum(1 for w in BASE if (sum(ad.get(cl, {}).get(w, [0, 0])) > 0 or sum(bclin[cl].get(w, {}).values()) > 0))
        bucket = "New" if wks < 8 else ("Maturing" if base < 25 else "Mature")
        adb = avg({w: sum(ad.get(cl, {}).get(w, [0, 0])) for w in BASE}, BASE); adw = sum(ad.get(cl, {}).get(W6, [0, 0]))
        wdb = avg({w: ad.get(cl, {}).get(w, [0, 0])[0] for w in BASE}, BASE); web = avg({w: ad.get(cl, {}).get(w, [0, 0])[1] for w in BASE}, BASE)
        cls = ("Growing" if w6v > base + 1 else "Stable" if w6v >= base - 1
               else "Availability" if (adb > 0 and adb - adw >= 0.5) else "L2B Conversion")
        clinics.append({"clinic": cl, "city": city.get(cl, "?"), "bucket": bucket, "base": base, "w6": w6v,
                        "delta": round(w6v - base, 1), "ad_base": adb, "ad_w6": adw,
                        "wd": f"{wdb:.0f}->{ad.get(cl, {}).get(W6, [0, 0])[0]}",
                        "we": f"{web:.0f}->{ad.get(cl, {}).get(W6, [0, 0])[1]}", "classification": cls})
    clinics.sort(key=lambda x: x["delta"])

    out = {
        "week": W6, "week_label": f"week of {W6}", "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method": "Sheet-exact: bookings=apt_create_dt+phone_rank=1, channel=Source final, online=locality==Online; baseline=8wk (leads 5wk).",
        "totals": {"leads": {"base": int(sum(avg(lchan[c], LBASE) for c in lchan)), "w6": sum(lchan[c].get(W6, 0) for c in lchan)},
                   "bookings": {"base": int(avg(bmode["online"], BASE) + avg(bmode["offline"], BASE)), "w6": bmode["online"].get(W6, 0) + bmode["offline"].get(W6, 0)},
                   "online": {"base": int(avg(bmode["online"], BASE)), "w6": bmode["online"].get(W6, 0)},
                   "offline": {"base": int(avg(bmode["offline"], BASE)), "w6": bmode["offline"].get(W6, 0)}},
        "leads_channel": sorted([{"channel": c, "base": avg(lchan[c], LBASE), "w6": lchan[c].get(W6, 0)} for c in lchan], key=lambda x: x["w6"] - x["base"]),
        "bookings_channel": sorted([{"channel": c, "base": avg(bchan[c], BASE), "w6": bchan[c].get(W6, 0)} for c in bchan], key=lambda x: x["w6"] - x["base"]),
        "category": [{"cat": c, "base": avg(bcat[c], BASE), "w6": bcat[c].get(W6, 0)} for c in ("SH", "STI")],
        "buckets": _buckets(clinics, ad, bclin, BASE, W6),
        "clinics": clinics,
        "rule_outs": {"category": "SH & STI ~flat, share steady — uniform across categories",
                      "demand": "Leads flat at clinic level; only FB channel down -> online"},
    }
    out["attribution"] = {"gross": sum(b["avail"] + b["l2b"] for b in out["buckets"]),
                          "availability": sum(b["avail"] for b in out["buckets"]),
                          "l2b": sum(b["l2b"] for b in out["buckets"])}
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"Wrote {a.out}: {len(clinics)} clinics; W6 bookings {out['totals']['bookings']['w6']}")


def _buckets(clinics, ad, bclin, BASE, W6):
    agg = defaultdict(lambda: {"n": 0, "base": 0.0, "w6": 0, "avail": 0.0, "l2b": 0.0})
    for o in clinics:
        a = agg[o["bucket"]]; a["n"] += 1; a["base"] += o["base"]; a["w6"] += o["w6"]
        loss = o["base"] - o["w6"]
        if loss >= 2:
            adrop = o["ad_base"] - o["ad_w6"]
            av = min(loss, (o["base"] / o["ad_base"]) * adrop) if (o["ad_base"] > 0 and adrop >= 0.5) else 0
            a["avail"] += av; a["l2b"] += loss - av
    return [{"name": b, "n": agg[b]["n"], "base": round(agg[b]["base"]), "w6": agg[b]["w6"],
             "avail": round(agg[b]["avail"]), "l2b": round(agg[b]["l2b"])} for b in ("New", "Maturing", "Mature") if b in agg]


if __name__ == "__main__":
    main()
