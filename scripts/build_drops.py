#!/usr/bin/env python3
"""Build data_drops.json — nested City → Clinic → Doctor demand-health dataset for the
"Where did demand drop?" Diagnostic View. Weekly arrays, OLDEST-first, from existing data:
  leads   : data_leads.json (sum of sources, clinic-engaged)
  book/done: data.json weekly_city/clinic/doctor (gross / calls_done)
  adays/weekday/weekend doctor-days: data_diagnostic.json (avail / weekend)
  avail hrs: data_roster.json (shr.avail, aligned — roster lags a week)
Run: python3 scripts/build_drops.py"""
import os, json, re, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T1 = {"Bangalore","Mumbai","Navi Mumbai","Pune","Hyderabad","Chennai","Delhi","Delhi NCR","Gurgaon","Gurugram","Kolkata"}
SRC = ["gmb","google_ad","organic","fb","justdial","others"]


def slug(s): return re.sub(r"[^a-z0-9]+","-",s.lower()).strip("-")


def main():
    big = json.load(open(os.path.join(ROOT,"data.json")))["all"]
    D   = json.load(open(os.path.join(ROOT,"data_diagnostic.json")))
    L   = json.load(open(os.path.join(ROOT,"data_leads.json")))
    R   = json.load(open(os.path.join(ROOT,"data_roster.json")))
    WK_NEW = (L.get("_meta") or D.get("_meta"))["weeks"]          # newest-first, 12
    WK = list(reversed(WK_NEW))                                   # oldest-first
    NW = len(WK)
    def lbl(iso):
        d = datetime.date.fromisoformat(iso); return f"{d.day} {d.strftime('%b')}"
    labels = [lbl(w) for w in WK]
    rweeks = (R.get("_meta") or {}).get("weeks", [])
    rmap = {w: rweeks.index(w) for w in WK if w in rweeks}        # demand-week → roster col

    def rev(a):  # newest-first 12 → oldest-first 12, missing→0
        a = a or []; out=[0]*NW
        for i in range(NW):
            j = NW-1-i
            out[i] = (a[j] if j < len(a) else 0) or 0
        return out
    def dj(level, name, field):  # data.json by ISO week (oldest-first)
        m = big.get("weekly_"+level, {})
        return [ ((m.get(w,{}) or {}).get(name,{}) or {}).get(field,0) or 0 for w in WK ]
    def roster_avail(pipe):
        r = R.get(pipe)
        if not r or "shr" not in r: return None
        out=[None]*NW
        for i,w in enumerate(WK):
            ci = rmap.get(w)
            if ci is not None and ci < len(r["shr"]["avail"]): out[i] = r["shr"]["avail"][ci]
        return out if any(v for v in out) else None

    # canonical clinic keys (pipe) from diagnostic ∪ leads
    clinkeys = sorted({k for src in (D,L) for k in src if k!="_meta"})
    cities = {}
    for pk in clinkeys:
        city, clinic = (pk.split("|",1)+[""])[:2]
        if not city or not clinic: continue
        if "online" in city.lower() or "online" in clinic.lower(): continue   # offline clinic demand only
        cities.setdefault(city, []).append((pk, clinic))

    out_cities=[]
    for city in sorted(cities):
        uk_city = city
        c_leads=[0]*NW; c_aday=[0]*NW; c_awd=[0]*NW; c_awe=[0]*NW; c_avail=[0]*NW; c_avail_any=False
        clinics_out=[]
        for pk, clinic in sorted(cities[city], key=lambda x:x[1]):
            uk = pk.replace("|","_")                              # data.json clinic key
            diag = D.get(pk, {}); lead = L.get(pk, {})
            leads = [sum((rev(lead.get(s))[i]) for s in SRC) for i in range(NW)]
            aday  = rev(diag.get("avail")); awe = rev(diag.get("weekend"))
            awd   = [max(0,aday[i]-awe[i]) for i in range(NW)]
            book  = dj("clinic", uk, "gross"); done = dj("clinic", uk, "calls_done")
            ravail= roster_avail(pk)
            # doctors
            docs=[]
            dprefix = uk+"|"
            docnames=set()
            for w in WK:
                for dk in (big.get("weekly_doctor",{}).get(w,{}) or {}):
                    if dk.startswith(dprefix): docnames.add(dk)
            for dk in sorted(docnames):
                dname = dk.split("|",1)[1]
                if dname=="(unassigned)": continue
                dbook=dj("doctor",dk,"gross"); ddone=dj("doctor",dk,"calls_done")
                if not any(dbook): continue
                docs.append({"id":slug(dname),"name":dname,"spec":"SH","book":dbook,"done":ddone})
            cl={"id":slug(clinic),"name":clinic,"leads":leads,"book":book,"done":done,
                "adays":aday,"adays_wd":awd,"adays_we":awe,"doctors":docs}
            if ravail: cl["avail"]=ravail
            clinics_out.append(cl)
            for i in range(NW):
                c_leads[i]+=leads[i]; c_aday[i]+=aday[i]; c_awd[i]+=awd[i]; c_awe[i]+=awe[i]
                if ravail and ravail[i]: c_avail[i]+=ravail[i]; c_avail_any=True
        cobj={"id":slug(city),"name":city,"tier":1 if city in T1 else 2,
              "leads":c_leads,"book":dj("city",uk_city,"gross"),"done":dj("city",uk_city,"calls_done"),
              "adays":c_aday,"adays_wd":c_awd,"adays_we":c_awe,"clinics":clinics_out}
        if c_avail_any: cobj["avail"]=c_avail
        out_cities.append(cobj)

    out={"_meta":{"weeks":labels,"weeks_iso":WK,"source":"data.json (book/done) · data_diagnostic (doctor-days) · data_leads (leads) · data_roster (avail hrs)"},
         "cities":out_cities}
    json.dump(out, open(os.path.join(ROOT,"data_drops.json"),"w"), separators=(",",":"))
    nclin=sum(len(c["clinics"]) for c in out_cities); ndoc=sum(len(cl["doctors"]) for c in out_cities for cl in c["clinics"])
    print(f"data_drops.json · {len(out_cities)} cities · {nclin} clinics · {ndoc} doctors · {NW} weeks ({labels[0]}→{labels[-1]})")


if __name__=="__main__":
    main()
