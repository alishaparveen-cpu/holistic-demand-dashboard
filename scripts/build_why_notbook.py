#!/usr/bin/env python3
"""Build data_why_notbook.json — the founder's "why didn't it book?" patient-flow cube,
per MH clinic × week, with the AVAILABILITY CROSS-CHECK.

Combines (pure-local, no Redshift):
  • data_clinic_funnels.json — MH call leads (callcat), clinic lead→book funnel, and the
    agent-disposition reasons for leads that didn't book (Main Disposition / subDisposition).
  • data_quick_diag.json     — per-clinic SC slots: open (availability.sc_slots), booked_slots,
    and slot_status (No Show / CANCELLED = WASTED capacity).

For each clinic-week it classifies the 'Doctor Slot/availability issue' losses against the
actual slot picture so the founder can tell WHY a lead didn't book:
  🔴 capacity gap  — patients turned away for 'no slot' AND ~no spare slots existed → add roster
  🟠 ops fumble    — patients turned away for 'no slot' BUT spare slots existed → booking/ops
  ⚪ wasted slot   — slots were booked then No-Show/Cancelled → capacity burned on no-shows

Reasons are CLINIC-LEVEL (the CRM disposition isn't category-tagged) — noted in the UI. MH
leads ARE category-specific (from the AI call-audit). Whitefield / day-level / per-category
reasons need the Redshift re-pull (phase 2).

Run: python3 scripts/build_why_notbook.py
"""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF = json.load(open(os.path.join(ROOT, "data_clinic_funnels.json")))
QD = json.load(open(os.path.join(ROOT, "data_quick_diag.json")))

# clinic_funnels short key -> quick_diag slug
SLUG = {"bharathi":"bharathi_nagar_coimbatore","indiranagar":"indiranagar_bangalore",
        "vaishali":"vaishali_nagar_jaipur","hadapsar":"hadapsar_pune","kharghar":"kharghar_navi_mumbai",
        "hubli":"vidya_nagar_hubli","kharadi":"kharadi_pune"}

# agent-disposition reason → bucket (the founder's "why")
BUCKET = {
  "avail": ["Doctor Slot/availability issue"],
  "timing":["Currently Busy - Will book later","Casual Enquiry - Slot time"],
  "lowint":["Casual Enquiry - Clinic Location","Casual Enquiry - Conditions we treat","Casual Enquiry - Doctor",
            "Casual Enquiry - Treatment Process","Needs to discuss with family/Friends/relative","Others"],
  "noise": ["Blank Call","Spam Call","Call Dropped in Between","Outbound Not connected","Other Language Call Back",
            "Didn't give a reason and disconnected","Transferred the Call to POC group"],
  "wantbook":["Customer WANTS to Book Consultation"],   # said yes but not yet booked → hot follow-up
  "untag": ["(no tag)","(not yet dispositioned)","Not Booked","Booked"],   # Booked here = mis-tag on a non-book lead
}
R2B = {r:b for b,rs in BUCKET.items() for r in rs}
BUCKET_LABEL = {"avail":"Availability (no slot)","timing":"Timing / will-book-later","lowint":"Low-intent (casual)",
                "noise":"Noise (spam/blank/not-connected)","wantbook":"Wanted to book — not yet","untag":"Untagged (agent didn't disposition)"}

CFW = CF["weeks"]; CFWL = CF.get("week_labels", CFW)
QW = QD["weeks"]; qidx = {w:i for i,w in enumerate(QW)}

def qd_week(slug, week, path):
    """value of a quick_diag field-array at the given week-string (None if absent)."""
    c = QD["clinics"].get(slug)
    if not c: return None
    a = c.get("sc", {})
    for p in path: a = (a or {}).get(p) if isinstance(a, dict) else None
    if not isinstance(a, list): return None
    i = qidx.get(week)
    return (a[i] if i is not None and i < len(a) else None)

out = {"_meta": {"weeks": CFW, "week_labels": CFWL, "cats": CF.get("cats", ["SH","STI","MH","Other"]),
        "bucket_label": BUCKET_LABEL,
        "note": "Founder 'why didn't it book' — per MH clinic × week. MH leads = AI-call-audit MH intent (category-specific). "
                "Disposition reasons + slot cross-check are CLINIC-level (CRM disposition isn't category-tagged; slots aren't per-category). "
                "spare = open SC slots − booked; wasted = No-Show + Cancelled. Verdict flags whether 'no slot' losses were a real "
                "capacity gap, an ops fumble (spare existed), or wasted on no-shows."},
       "clinics": {}}

for key, node in CF["clinics"].items():
    slug = SLUG.get(key)
    if not slug: continue
    lead = node["leads"]; NW = len(CFW)
    Z = lambda: [0]*NW
    # MH call leads (category-specific), summed over channels
    mh = Z()
    for ch, arr in (lead.get("callcat", {}).get("MH", {}) or {}).items():
        for i in range(min(NW, len(arr))): mh[i] += arr[i] or 0
    # clinic lead→book funnel (all categories — noted)
    booked = [ (lead.get("booked_same",Z())[i] or 0)+(lead.get("booked_later",Z())[i] or 0) for i in range(NW) ]
    notbk  = lead.get("not_booked", Z())
    # disposition reasons → weekly buckets
    wkr = lead.get("nobook_reasons_weekly", {})
    buckets = {b: Z() for b in BUCKET}
    for reason, arr in wkr.items():
        b = R2B.get(reason, "untag")
        for i in range(min(NW, len(arr))): buckets[b][i] += arr[i] or 0
    # slot cross-check per week (from quick_diag, matched by week-string)
    openS, bookedS, wasted = Z(), Z(), Z()
    for i, wk in enumerate(CFW):
        o  = qd_week(slug, wk, ["availability","sc_slots"])
        bs = qd_week(slug, wk, ["done","booked_slots"])
        ss = QD["clinics"].get(slug,{}).get("sc",{}).get("done",{}).get("slot_status",{}) or {}
        ns = (ss.get("No Show") or [None]*len(QW)); cx = (ss.get("CANCELLED") or [None]*len(QW))
        qi = qidx.get(wk)
        openS[i]   = round(o) if o else 0
        bookedS[i] = round(bs) if bs else 0
        wasted[i]  = int(((ns[qi] if qi is not None and qi<len(ns) else 0) or 0) + ((cx[qi] if qi is not None and qi<len(cx) else 0) or 0)) if qi is not None else 0
    spare = [max(0, openS[i]-bookedS[i]) for i in range(NW)]
    # per-week verdict on the 'availability' losses
    verdict = []
    for i in range(NW):
        a = buckets["avail"][i]
        if a <= 0: verdict.append(None)
        elif spare[i] >= a: verdict.append("ops")          # spare slots covered the turned-away demand → booking/ops fumble
        elif spare[i] > 0:  verdict.append("mixed")
        else:               verdict.append("capacity")     # no spare → genuine capacity gap
    out["clinics"][key] = {"city":node.get("city"), "loc":node.get("loc"),
        "mh_leads":mh, "booked":booked, "not_booked":notbk,
        "buckets":{b:buckets[b] for b in BUCKET},
        "open_slots":openS, "booked_slots":bookedS, "spare_slots":spare, "wasted_slots":wasted,
        "verdict":verdict}

json.dump(out, open(os.path.join(ROOT, "data_why_notbook.json"), "w"), separators=(",",":"))
print(f"data_why_notbook.json · {len(out['clinics'])} MH clinics · {len(CFW)} weeks")
for k, c in out["clinics"].items():
    li = next((i for i,v in enumerate(c['mh_leads']) if v), 0)
    print(f"  {k:<12} latest MH leads={c['mh_leads'][li] if c['mh_leads'] else 0}  "
          f"avail-loss(wk)={c['buckets']['avail'][li]}  spare={c['spare_slots'][li]}  wasted={c['wasted_slots'][li]}  verdict={c['verdict'][li]}")
