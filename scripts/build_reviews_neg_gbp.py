#!/usr/bin/env python3
"""Build data_reviews_neg.json (recent NEGATIVE Google reviews per clinic, with text) live from the
Google Business Profile reviews API — replaces the warehouse external_reviews ETL that stopped on
2026-05-06. Auth: GBP_CLIENT_ID/SECRET/REFRESH_TOKEN in env (business.manage scope).
Negatives = rating <= 3, review_date >= CUTOFF (~last 8 weeks)."""
import os, sys, json, re, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNT = "104278284314268556784"            # PERSONAL account holding the clinic locations
CUTOFF = "2026-04-06"                          # ~last 8 weeks
STAR = {"ONE":1,"TWO":2,"THREE":3,"FOUR":4,"FIVE":5}

def token():
    body = urllib.parse.urlencode({"client_id":os.environ["GBP_CLIENT_ID"],
        "client_secret":os.environ["GBP_CLIENT_SECRET"],"refresh_token":os.environ["GBP_REFRESH_TOKEN"],
        "grant_type":"refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body) as r:
        return json.load(r)["access_token"]

def get(url, at):
    req = urllib.request.Request(url, headers={"Authorization":"Bearer "+at})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def list_locations(at):
    out, page = [], None
    while True:
        u = f"https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{ACCOUNT}/locations?readMask=name,title&pageSize=100"
        if page: u += "&pageToken="+page
        d = get(u, at); out += d.get("locations", []); page = d.get("nextPageToken")
        if not page: break
    return out

def clean(txt):
    if not txt: return ""
    m = re.match(r"\(Translated by Google\)\s*(.*?)\s*\(Original\)", txt, re.S)  # keep the English translation
    return (m.group(1) if m else txt).strip().replace("\n"," ")[:240]

def reviews(acc, loc, at):
    out, page = [], None
    for _ in range(3):                          # up to ~150 newest reviews — plenty for an 8-wk window
        u = f"https://mybusiness.googleapis.com/v4/accounts/{acc}/locations/{loc}/reviews?pageSize=50&orderBy=updateTime%20desc"
        if page: u += "&pageToken="+page
        d = get(u, at)
        if "error" in d: return []
        out += d.get("reviews", []); page = d.get("nextPageToken")
        if not page: break
        # stop early once we're past the cutoff
        if out and (out[-1].get("createTime","")[:10] < CUTOFF): break
    return out

def main():
    at = token()
    diag = json.load(open(os.path.join(ROOT,"data_diagnostic.json")))
    loc_by = { k.split("|")[1].strip().lower(): k for k in diag if k!="_meta" }
    D = {"_meta":{"source":"Google Business Profile reviews API (live) · rating<=3 · since "+CUTOFF,
                  "note":"Replaces warehouse external_reviews ETL (stopped 2026-05-06)."}}
    nrev = 0; flat = []
    for L in list_locations(at):
        m = re.search(r"Allo Health,?\s*([^-–|]+)", L.get("title",""))
        if not m: continue
        nm = m.group(1).strip().lower()
        key = loc_by.get(nm)                      # EXACT locality match only — substring matching cross-assigns
        if not key: continue
        loc = L["name"].split("/")[-1]
        for rv in reviews(ACCOUNT, loc, at):
            dt = rv.get("createTime","")[:10]
            if dt < CUTOFF: continue
            rating = STAR.get(rv.get("starRating"), 5)
            if rating > 3: continue
            flat.append((key, {"dt":dt, "rating":rating,
                         "author":(rv.get("reviewer") or {}).get("displayName",""),
                         "replied":1 if rv.get("reviewReply") else 0,
                         "txt":clean(rv.get("comment",""))}))
    # De-duplicate reviews cross-posted to multiple clinic listings (same reviewer + date + text):
    # keep the copy on the listing the OWNER REPLIED to (the engaged/primary one), else the first.
    flat.sort(key=lambda kr: -kr[1]["replied"])
    seen = set()
    for key, rv in flat:
        sig = (rv["author"], rv["dt"], rv["txt"][:80])
        if sig in seen: continue
        seen.add(sig); D.setdefault(key, []).append(rv); nrev += 1
    for key in D:
        if key != "_meta": D[key].sort(key=lambda x: x["dt"], reverse=True)
    json.dump(D, open(os.path.join(ROOT,"data_reviews_neg.json"),"w"), separators=(",",":"))
    print(f"data_reviews_neg.json · {len([k for k in D if k!='_meta'])} clinics · {nrev} negative reviews (deduped)")

if __name__ == "__main__":
    main()
