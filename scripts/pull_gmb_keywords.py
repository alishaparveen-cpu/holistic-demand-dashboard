#!/usr/bin/env python3
"""Per-clinic GMB SEARCH KEYWORDS by month, categorised SH/STI/MH/Other — the
category-resolved TOP-OF-FUNNEL signal for "did the psychiatrist-category change shift
GMB demand from SH to MH". GBP Performance API searchkeywords/impressions/monthly is
monthly-only, so we pull each month separately. insightsValue is either {value:N}
(exact) or {threshold:N} (long tail, ">N" — we floor at N). Writes data_gmb_keywords.json.
Auth: GBP_CLIENT_ID/SECRET/REFRESH_TOKEN (source ~/.allo_gbp.env). Run: python3 scripts/pull_gmb_keywords.py
"""
import os, sys, json, re, urllib.parse, urllib.request

# clinic -> GBP location id (from the clinic->GMB-id table). MH-funnel clinics that
# carry the psychiatrist-category change + a few non-MH controls for diff-in-diff.
CLINICS = {
  # MH (category changed)
  "Coimbatore|Bharathi Nagar": ("9724695569029443936",  "MH"),
  "Navi Mumbai|Kharghar":      ("13412576936814792533", "MH"),
  "Pune|Hadapsar":             ("18428812500995344552", "MH"),
  "Pune|Kharadi":              ("12369744412506563079", "MH"),
  "Bangalore|Indiranagar":     ("12238800764553363051", "MH"),
  "Jaipur|Vaishali Nagar":     ("2584614150468436300",  "MH"),
  "Hubli|Vidya Nagar":         ("13976033231598062289", "MH"),
  # CONTROL (no MH category change) — to diff-in-diff against
  "Bangalore|Jayanagar":       ("554001656424784766",   "CTRL"),
  "Hyderabad|Ameerpet":        ("18004701114486959273", "CTRL"),
  "Mumbai|Ghatkopar":          ("14972625616199796151", "CTRL"),
}
MONTHS = [(2026,2),(2026,3),(2026,4),(2026,5),(2026,6)]   # Feb..Jun 2026 (change was ~late May/Jun)

MH_RE  = re.compile(r"psychiat|psycholog|mental|anxiet|depress|stress|therap|counsel|ocd|bipolar|adhd|panic|\bmood\b|मानसिक|डिप्रे|अवसाद|चिंता|तनाव|घबरा", re.I)
STI_RE = re.compile(r"\bstd\b|\bsti\b|\bhiv\b|herpes|syphil|gonorr|chlam|discharge|\buti\b|\burine\b|burning|genital wart", re.I)
SH_RE  = re.compile(r"\bsex|sexolog|erectile|\bed\b|premature|\bpe\b|libido|testoster|penis|\bling\b|नपुंस|शीघ्र|वीर्य|\bलिंग|कामे|संभोग|गुप्त रोग|सेक्स|यौन|सेक्सोलॉ|मर्दाना|स्तंभन|शीघ्रपतन", re.I)
def cat(kw):
    k=kw.lower()
    if MH_RE.search(k): return "MH"
    if STI_RE.search(k): return "STI"
    if SH_RE.search(k): return "SH"
    return "Other"

def token():
    body=urllib.parse.urlencode({"client_id":os.environ["GBP_CLIENT_ID"],"client_secret":os.environ["GBP_CLIENT_SECRET"],
        "refresh_token":os.environ["GBP_REFRESH_TOKEN"],"grant_type":"refresh_token"}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token",body))["access_token"]

def kw_month(at, loc, y, m):
    url=("https://businessprofileperformance.googleapis.com/v1/locations/%s/searchkeywords/impressions/monthly"
         "?monthlyRange.startMonth.year=%d&monthlyRange.startMonth.month=%d"
         "&monthlyRange.endMonth.year=%d&monthlyRange.endMonth.month=%d"%(loc,y,m,y,m))
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+at})
    d=json.load(urllib.request.urlopen(req,timeout=60))
    out=[]
    for r in d.get("searchKeywordsCounts",[]):
        v=r.get("insightsValue",{}); val=int(v.get("value") or v.get("threshold") or 0)
        out.append((r.get("searchKeyword",""), val))
    return out

def main():
    at=token(); ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res={"_meta":{"months":["%d-%02d"%(y,m) for y,m in MONTHS],"source":"GBP Performance API searchkeywords/impressions/monthly · categorised SH/STI/MH/Other","note":"insightsValue value or threshold(floor). top100 keywords/month."}}
    for key,(loc,grp) in CLINICS.items():
        bycat={c:[0]*len(MONTHS) for c in ("SH","STI","MH","Other")}; top={}
        for mi,(y,m) in enumerate(MONTHS):
            try: rows=kw_month(at,loc,y,m)
            except Exception as e: print("  [warn] %s %d-%02d: %s"%(key,y,m,str(e)[:80])); continue
            for kw,val in rows: bycat[cat(kw)][mi]+=val
            top["%d-%02d"%(y,m)]=[(kw,cat(kw),val) for kw,val in rows[:12]]
        res[key]={"group":grp,"by_cat":bycat,"top":top}
        tot=[sum(bycat[c][i] for c in bycat) for i in range(len(MONTHS))]
        shsh=[round(bycat["SH"][i]/tot[i]*100) if tot[i] else 0 for i in range(len(MONTHS))]
        mhsh=[round(bycat["MH"][i]/tot[i]*100) if tot[i] else 0 for i in range(len(MONTHS))]
        print("%-26s [%s] SH-share %% by month: %s | MH-share %%: %s"%(key,grp,shsh,mhsh))
    json.dump(res,open(os.path.join(ROOT,"data_gmb_keywords.json"),"w"),separators=(",",":"))
    print("wrote data_gmb_keywords.json")

if __name__=="__main__": main()
