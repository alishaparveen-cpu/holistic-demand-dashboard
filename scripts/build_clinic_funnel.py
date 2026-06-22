#!/usr/bin/env python3
"""Build data_clinic_funnel.json — the CLINIC-LEVEL funnel (stages 0-9) for clinic-funnel.html.
Joins the clinic-attributable data we already pull (GMB Insights, bookings/done, availability,
reviews, leads, category) with the CITY-level Google Ads paid layer (data_ga_city_paid.json).

Clinic-level (real, badge CLINIC ✓):   supply · GMB discovery/engagement · GMB organic calls ·
  bookings · category mix · show-up · done · velocity.
City-level (badge CITY):               Google Ads Loc%/IS%/spend/clicks/CPP — shared across the
  city's clinics; the HTML also offers a per-clinic allocation by booking share.
All arrays are 12 weeks, newest-first (aligned to the dashboard weeks).
Run:  python3 scripts/build_clinic_funnel.py    (no Redshift — reads existing JSONs)
"""
import os, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = lambda f: json.load(open(os.path.join(ROOT, f)))
WEEKS = ["2026-06-08","2026-06-01","2026-05-25","2026-05-18","2026-05-11","2026-05-04","2026-04-27",
         "2026-04-20","2026-04-13","2026-04-06","2026-03-30","2026-03-23"]
NW = len(WEEKS)
Z = lambda: [0]*NW
def arr(o, k, n=NW):
    a = (o or {}).get(k) or []
    a = list(a[:n]); a += [0]*(n-len(a)); return a

def rating_fill(a, n=NW):
    # GMB rating is reported with a lag (newest weeks null). It's a current-state value — carry the
    # most recent known rating forward so every week shows the clinic's last-known stars, not "—".
    a = list((a or [])[:n]); a += [None]*(n-len(a))
    out = a[:]; last = None
    for i in range(n-1, -1, -1):            # oldest → newest
        if a[i] is not None: last = a[i]
        elif last is not None: out[i] = last
    return out

def main():
    GMB = L("data_gmb_insights.json"); DIAG = L("data_diagnostic.json"); REV = L("data_reviews.json")
    ROST = L("data_roster.json"); BT = L("data_booktype.json"); LEADS = L("data_leads.json")
    PAID = L("data_ga_city_paid.json"); BIG = L("data.json")
    try: REVN = L("data_clinic_revenue.json")
    except Exception: REVN = {}
    try: LEADF = L("data_clinic_lead_funnel.json")          # AI-audit clinic leads (call_analyses)
    except Exception: LEADF = {"_meta": {"weeks": []}}
    lwk = (LEADF.get("_meta", {}) or {}).get("weeks", [])
    lpos = {w: i for i, w in enumerate(lwk)}
    def ai_series(key, field):                              # realign AI-lead weeks → the funnel's WEEKS
        o = LEADF.get(key)
        if not o: return [0]*NW
        src = o.get(field) or []
        return [ (src[lpos[w]] if w in lpos and lpos[w] < len(src) else 0) for w in WEEKS ]
    def ai_lead_cats(key):                                  # inbound leads split into STI / SH / MH / Other
        o = LEADF.get(key); bc = (o or {}).get("by_cat") or {}
        def rs(cks):
            return [ sum((bc.get(ck) or [])[lpos[w]] if (w in lpos and lpos[w] < len(bc.get(ck) or [])) else 0 for ck in cks) for w in WEEKS ]
        return {"STI": rs(["STI"]), "SH": rs(["SEXUAL_HEALTH_GENERAL"]), "MH": rs(["MENTAL_HEALTH"]), "Other": rs(["OTHER", "NOT_MENTIONED"])}
    WC = BIG.get("all", {}).get("weekly_clinic", {})
    rweeks = (ROST.get("_meta", {}) or {}).get("weeks", [])
    rpos = {w: i for i, w in enumerate(rweeks)}    # roster weeks lag diagnostic weeks by one — align by date
    # weekly_clinic is keyed by "City_Clinic"; map a pipe key → its weekly per-field arrays
    def wc_series(pipe):
        city, clinic = pipe.split("|", 1)
        cand = city + "_" + clinic
        out = {}
        for f in ["gross","calls_done","no_show","rescheduled","slot_booked","total","STI","ED+","PE+","ED+PE+","NSSD","oth"]:
            out[f] = [ (WC.get(w, {}).get(cand, {}) or {}).get(f, 0) or 0 for w in WEEKS ]
        return out

    clinics = sorted(k for k in DIAG if k != "_meta")
    out_clinics = {}
    city_book = {}   # city → weekly total bookings (for allocation)
    for key in clinics:
        city = key.split("|")[0]
        d = DIAG.get(key, {}); g = GMB.get(key, {}); rv = REV.get(key, {}); ro = ROST.get(key, {})
        bt = BT.get(key, {}); ld = LEADS.get(key, {}); wc = wc_series(key)
        shr = (ro or {}).get("shr", {})
        active_days = arr(d, "avail"); weekend_days = arr(d, "weekend")
        # roster weeks LAG the diagnostic weeks by one — align hours by actual date, carry the last
        # known week forward into the trailing gap, and never show hours on a 0-active-day week.
        rsrc = (shr or {}).get("avail") or []
        avail_hours = [ (rsrc[rpos[w]] if (w in rpos and rpos[w] < len(rsrc)) else None) for w in WEEKS ]
        _last = None
        for i in range(NW-1, -1, -1):
            if avail_hours[i] is not None: _last = avail_hours[i]
            elif _last is not None: avail_hours[i] = _last
        avail_hours = [ (round(h, 1) if (h is not None and (active_days[i] or 0) > 0) else (0 if (active_days[i] or 0) == 0 else h))
                        for i, h in enumerate(avail_hours) ]
        impressions = arr(g, "searches"); gmb_days = arr(g, "days"); interactions = arr(g, "interactions")
        directions = arr(g, "directions"); gmb_calls = arr(g, "calls"); website = arr(g, "website")
        bookings = wc["gross"]; done = wc["calls_done"]; no_show = wc["no_show"]; resched = wc["rescheduled"]
        catmix = {c: wc[c] for c in ["STI","ED+","PE+","ED+PE+","NSSD","oth"]}
        leads_by = {ch: arr(ld, ch) for ch in ["gmb","google_ad","organic","fb","justdial","others","practo_crm","outbound_wa"]}
        leads_total = [sum(leads_by[ch][i] for ch in leads_by) for i in range(NW)]
        for i in range(NW):
            city_book.setdefault(city, Z())
            city_book[city][i] += bookings[i] or 0
        out_clinics[key] = {
            "city": city,
            "supply": {"active_days": active_days, "avail_hours": avail_hours, "weekend_days": weekend_days},
            "discovery": {"impressions": impressions, "gmb_days": gmb_days,
                          "review_vel": arr(rv, "n"), "rating": rating_fill((rv or {}).get("rating"))},
            "engagement": {"interactions": interactions, "directions": directions, "website": website, "gmb_calls": gmb_calls},
            "lead": {"leads_total": leads_total, "by_chan": leads_by, "gmb_organic_calls": gmb_calls, "gmb_leads": arr(d, "gmbLeads"),
                     "ai_lead_calls": ai_series(key, "lead_calls"), "ai_relevant": ai_series(key, "relevant"), "ai_strong": ai_series(key, "strong"),
                     "ai_lead_by_cat": ai_lead_cats(key)},
            "booking": {"bookings": bookings, "new": arr(bt, "new"), "repeat": arr(bt, "repeat"), "catmix": catmix},
            "showup": {"no_show": no_show, "reschedules": resched},
            "done": {"done": done},
            "revenue": {"rev": arr(REVN.get(key, {}), "rev"), "paid_consults": arr(REVN.get(key, {}), "paid_consults"),
                        "by_cat": {c: arr((REVN.get(key, {}).get("rev_by_cat") or {}), c) for c in ["STI","ED+","PE+","ED+PE+","NSSD","oth"]}},
        }
    # velocity + allocation weight (needs city_book) + attach city paid
    for key, o in out_clinics.items():
        city = o["city"]; bk = o["booking"]["bookings"]; ad = o["supply"]["active_days"]; ah = o["supply"]["avail_hours"]
        o["velocity"] = {
            "bk_per_day": [round(bk[i]/ad[i], 2) if ad[i] else None for i in range(NW)],
            "bk_per_hour": [round(bk[i]/ah[i], 2) if ah[i] else None for i in range(NW)],
            "done_per_day": [round(o["done"]["done"][i]/ad[i], 2) if ad[i] else None for i in range(NW)],
        }
        cb = city_book.get(city, Z())
        o["alloc_w"] = [round(bk[i]/cb[i], 4) if cb[i] else 0 for i in range(NW)]   # clinic share of city bookings

    out = {"_meta": {"weeks": WEEKS, "source": "clinic funnel — GMB Insights + bookings/done + availability + reviews + category (clinic-level) · Google Ads (city-level paid)",
                     "note": "Google Ads paid metrics (Loc%/IS%/spend/clicks/CPP) are CITY-level; the report shares them across a city's clinics, or allocates by each clinic's booking share (alloc_w)."},
           "cities": {}, "clinics": out_clinics}
    for city, cb in city_book.items():
        paid = PAID.get(city)
        out["cities"][city] = {"book_total": cb, "clinics": sorted(k for k in out_clinics if k.split("|")[0] == city),
                               "paid": paid, "paid_matched": paid is not None}
    json.dump(out, open(os.path.join(ROOT, "data_clinic_funnel.json"), "w"), separators=(",", ":"))
    nc = len(out_clinics); ncity = len(out["cities"]); matched = sum(1 for c in out["cities"].values() if c["paid_matched"])
    print(f"data_clinic_funnel.json · {nc} clinics · {ncity} cities ({matched} with Google Ads paid)")
    nopaid = sorted(c for c, v in out["cities"].items() if not v["paid_matched"])
    if nopaid: print("  cities with NO Google Ads paid match:", nopaid)
    # sanity: one clinic
    k = "Bangalore|Indiranagar" if "Bangalore|Indiranagar" in out_clinics else clinics[0]
    o = out_clinics[k]
    print(f"  {k}: W0 impr={o['discovery']['impressions'][0]} interactions={o['engagement']['interactions'][0]} "
          f"bookings={o['booking']['bookings'][0]} done={o['done']['done'][0]} active_days={o['supply']['active_days'][0]} bk/day={o['velocity']['bk_per_day'][0]} alloc_w={o['alloc_w'][0]}")


if __name__ == "__main__":
    main()
