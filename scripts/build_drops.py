#!/usr/bin/env python3
"""Build data_drops.json — nested City → Clinic → Doctor demand-health dataset for the
"Where did demand drop?" Diagnostic View. Weekly arrays, OLDEST-first, from existing data:
  leads   : data_leads.json (sum of sources, clinic-engaged)
  book/done: data.json weekly_city/clinic/doctor (gross / calls_done)
  adays/weekday/weekend doctor-days: data_diagnostic.json (avail / weekend)
  avail hrs: data_roster.json (shr.avail, aligned — roster lags a week)
Run: python3 scripts/build_drops.py"""
import os, sys, json, re, datetime, subprocess

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
    widx = {w: i for i, w in enumerate(WK)}

    # ── per-DOCTOR active days (realized) from the roster, keyed city|locality|doctor → {adays[],we[]} ──
    DOC_AVAIL = {}
    try:
        sql = open(os.path.join(ROOT,"scripts","fetch_drops_doc_avail.sql")).read()
        p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                           input=sql, capture_output=True, text=True)
        if p.returncode==0 and "ERROR" not in p.stderr:
            for line in p.stdout.strip().splitlines():
                c = line.split("\t")
                if len(c) < 6: continue
                city, loc, doc, wk, ad, we = c[0], c[1], c[2], c[3], c[4], c[5]
                if wk not in widx: continue
                o = DOC_AVAIL.setdefault(f"{city}|{loc}|{doc}", {"a":[0]*NW,"we":[0]*NW})
                try: o["a"][widx[wk]] += int(float(ad)); o["we"][widx[wk]] += int(float(we))
                except (ValueError, IndexError): pass
            print(f"  per-doctor availability: {len(DOC_AVAIL)} doctors")
        else:
            sys.stderr.write("WARN per-doctor avail query failed; doctors will have no availability\n")
    except Exception as e:
        sys.stderr.write(f"WARN per-doctor avail skipped: {e}\n")

    # ── episode-based FIRST-TIME / total / done SC bookings, per city|locality|doctor (oldest-first) ──
    # first = patient's all-time first episode ("1st Time Bookings" the city heads track), all = every
    # episode (total), donen = first episodes that completed. Validated to match the city-head sheet.
    BK = {}
    try:
        sql = open(os.path.join(ROOT,"scripts","fetch_drops_bookings.sql")).read()
        p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")],
                           input=sql, capture_output=True, text=True)
        if p.returncode==0 and "ERROR" not in p.stderr:
            for line in p.stdout.strip().splitlines():
                c = line.split("\t")
                if len(c) < 7: continue
                city_, loc_, doc_, wk_, fb_, ab_, dn_ = c[:7]
                if wk_ not in widx: continue
                o = BK.setdefault(f"{city_}|{loc_}|{doc_}", {"first":[0]*NW,"all":[0]*NW,"donen":[0]*NW})
                i = widx[wk_]
                try: o["first"][i]+=int(float(fb_)); o["all"][i]+=int(float(ab_)); o["donen"][i]+=int(float(dn_))
                except (ValueError,IndexError): pass
            print(f"  episode bookings: {len(BK)} city|clinic|doctor rows")
        else:
            sys.stderr.write("WARN drops-bookings query failed; falling back to data.json gross\n")
    except Exception as e:
        sys.stderr.write(f"WARN drops-bookings skipped: {e}\n")

    def bk_for(city, loc=None, doc=None):
        """Sum episode bookings (first/all/donen) over matching keys: whole city, one clinic, or one doctor."""
        f=[0]*NW; a=[0]*NW; dn=[0]*NW
        for k,o in BK.items():
            kc = k.split("|",2)
            if len(kc) < 3: continue
            if doc is not None:
                if not (kc[0]==city and kc[1]==loc and kc[2]==doc): continue
            elif loc is not None:
                if not (kc[0]==city and kc[1]==loc): continue
            else:
                if kc[0]!=city: continue
            for i in range(NW): f[i]+=o["first"][i]; a[i]+=o["all"][i]; dn[i]+=o["donen"][i]
        return f,a,dn

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
            cbook, cbookall, cdone = bk_for(city, clinic)              # first-time / all / done(new)
            if not any(cbookall):                                       # fallback: episode pull unavailable
                cbook = dj("clinic", uk, "gross"); cbookall = cbook; cdone = dj("clinic", uk, "calls_done")
            ravail= roster_avail(pk)
            # doctors — driven by the episode-bookings provider names (same name source as DOC_AVAIL)
            docs=[]
            docnames = sorted({k.split("|",2)[2] for k in BK
                               if k.startswith(f"{city}|{clinic}|") and not k.endswith("|(unassigned)")})
            for dname in docnames:
                dbook, dbookall, ddone = bk_for(city, clinic, dname)
                if not any(dbookall): continue
                dobj={"id":slug(dname),"name":dname,"spec":"SH","book":dbook,"bookall":dbookall,"done":ddone}
                da=DOC_AVAIL.get(f"{city}|{clinic}|{dname}")
                if da and any(da["a"]):
                    dobj["adays"]=da["a"]; dobj["adays_we"]=da["we"]
                    dobj["adays_wd"]=[max(0,da["a"][i]-da["we"][i]) for i in range(NW)]
                docs.append(dobj)
            cl={"id":slug(clinic),"name":clinic,"leads":leads,"book":cbook,"bookall":cbookall,"done":cdone,
                "adays":aday,"adays_wd":awd,"adays_we":awe,"doctors":docs}
            if ravail: cl["avail"]=ravail
            clinics_out.append(cl)
            for i in range(NW):
                c_leads[i]+=leads[i]; c_aday[i]+=aday[i]; c_awd[i]+=awd[i]; c_awe[i]+=awe[i]
                if ravail and ravail[i]: c_avail[i]+=ravail[i]; c_avail_any=True
        citybook, citybookall, citydone = bk_for(city)
        if not any(citybookall):
            citybook = dj("city",uk_city,"gross"); citybookall = citybook; citydone = dj("city",uk_city,"calls_done")
        cobj={"id":slug(city),"name":city,"tier":1 if city in T1 else 2,
              "leads":c_leads,"book":citybook,"bookall":citybookall,"done":citydone,
              "adays":c_aday,"adays_wd":c_awd,"adays_we":c_awe,"clinics":clinics_out}
        if c_avail_any: cobj["avail"]=c_avail
        out_cities.append(cobj)

    out={"_meta":{"weeks":labels,"weeks_iso":WK,
         "book_def":"book = first-time SC bookings (patient's first-ever episode, reschedules collapsed, online excluded) — the city-head '1st Time Bookings'. bookall = all episodes (new + returning). done = first-time episodes completed.",
         "source":"fetch_drops_bookings.sql episodes (book/bookall/done) · data_diagnostic (doctor-days) · data_leads (leads) · data_roster (avail hrs)"},
         "cities":out_cities}
    json.dump(out, open(os.path.join(ROOT,"data_drops.json"),"w"), separators=(",",":"))
    nclin=sum(len(c["clinics"]) for c in out_cities); ndoc=sum(len(cl["doctors"]) for c in out_cities for cl in c["clinics"])
    print(f"data_drops.json · {len(out_cities)} cities · {nclin} clinics · {ndoc} doctors · {NW} weeks ({labels[0]}→{labels[-1]})")


if __name__=="__main__":
    main()
