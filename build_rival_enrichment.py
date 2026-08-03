#!/usr/bin/env python3
"""
build_rival_enrichment.py
Scans data_competition.json for T1 city rivals matching our auction-insight domains.
Outputs data_rival_enrichment.json:
  { "domain": { "name", "reviews", "maps_url", "nearest_clinics": [{city,loc,km,our_reviews}], "city_summary" } }
"""
import json, os, re
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(DIR, "data_competition.json")) as f:
    COMP = json.load(f)
with open(os.path.join(DIR, "data_auction_insights.json")) as f:
    AI = json.load(f)

T1 = {"Bangalore", "Chennai", "Hyderabad", "Mumbai", "Pune", "Navi Mumbai"}

# Domain → search keywords (lowercase fragments that appear in the GMB listing name)
DOMAIN_KEYWORDS = {
    "drkamarajhospital.com":        ["kamaraj"],
    "drsafehands.com":              ["safehands", "safe hands"],
    "mensclinicgroup.com":          ["men's clinic group", "mens clinic group", "men clinic group", "mens clinic"],
    "topsexologistinpune.com":      ["topsexologist in pune", "top sexologist in pune"],
    "drerandes.com":                ["erande", "dr erande"],
    "milann.co.in":                 ["milann"],
    "themenscareclinic.com":        ["mens care clinic", "men's care clinic", "medi life", "medilife"],
    "nuhospitals.com":              ["nu hospitals", "nu hospital"],
    "oasisindia.in":                ["oasis fertility", "oasis ivf", "oasis india"],
    "ovumfertility.in":             ["ovum fertility", "ovum hospital", "ovum"],
    "orangehealth.in":              ["orange health"],
    "vijayadiagnostic.com":         ["vijaya diagnostic"],
    "suburbandiagnostics.com":      ["suburban diagnostic", "suburban"],
    "metropolisindia.com":          ["metropolis"],
    "cadabamshospitals.com":        ["cadabam"],
    "amahahealth.com":              ["amaha"],
    "maargamindcare.in":            ["maarga", "maarga mind"],
    "anc.clinic":                   ["anc clinic", "anc "],
    "mpowerminds.com":              ["mpower", "m power"],
    "arunmuthuvel.com":             ["arun muthuvel", "arunmuthuvel"],
    "homeocare.in":                 ["homeo care clinic", "homeocare", "shreshta homeo"],
    "drskjainclinic.com":           ["dr sk jain", "sk jain", "burlington", "drskjain"],
    "ashakiranclinic.com":          ["asha kiran"],
    "drpriyankkothari.in":          ["priyank kothari", "priyank"],
    "kayakalpinternational.net.in": ["kayakalp", "kaya kalp"],
    "gautamayurveda.co.in":         ["gautam ayurveda", "gautamayurveda", "swapnil gautam", "dr. swapnil gautam"],
    "apollofertility.com":          ["apollo fertility"],
    "metromaleclinic.com":          ["metromale", "metro male"],
    "lalpathlabs.com":              ["lal pathlabs", "lalpath"],
    "manpravah.com":                ["manpravah"],
    "trijog.com":                   ["trijog"],
    "abhasa.org":                   ["abhasa"],
    "jagrutiwellness.com":          ["jagruti"],
    "zenuphealth.com":              ["zenup"],
    "betterhelp.com":               ["betterhelp", "better help"],
    "nityanandrehab.com":           ["nityanand"],
    "mindsightclinic.com":          ["mindsight"],
    "lissun.app":                   ["lissun"],
    "apollohospitals.com":          ["apollo hospitals", "apollo hospital"],
    "manipalhospitals.com":         ["manipal hospitals", "manipal hospital", "manipal clinics"],
}

def matches(name, keywords):
    nl = name.lower()
    return any(k in nl for k in keywords)

# Collect all matching rivals across T1 clinics
hits = defaultdict(list)  # domain → list of {city, loc, km, reviews, maps_url, our_reviews, name}

for cat in ["SH", "STI", "MH"]:
    for ck, cv in COMP[cat]["clinics"].items():
        city = cv.get("city", "")
        if city not in T1:
            continue
        loc = cv.get("loc", "")
        our_rev = cv.get("our_reviews", 0) or 0
        for comp in cv.get("competitors", []):
            cname = comp.get("name", "")
            for domain, keywords in DOMAIN_KEYWORDS.items():
                if matches(cname, keywords):
                    hits[domain].append({
                        "cat": cat,
                        "city": city,
                        "loc": loc,
                        "km": comp.get("km"),
                        "reviews": comp.get("reviews"),
                        "maps_url": comp.get("maps", ""),
                        "our_reviews": our_rev,
                        "name": cname,
                    })

# Also search top_rivals
for cat in ["SH", "STI", "MH"]:
    for citykey, cv in COMP[cat]["cities"].items():
        city = citykey
        if city not in T1:
            continue
        our_rev = cv.get("our_reviews", 0) or 0
        for r in cv.get("top_rivals", []):
            rname = r.get("name", "")
            for domain, keywords in DOMAIN_KEYWORDS.items():
                if matches(rname, keywords):
                    hits[domain].append({
                        "cat": cat,
                        "city": city,
                        "loc": None,
                        "km": None,
                        "reviews": r.get("reviews"),
                        "maps_url": r.get("maps", ""),
                        "our_reviews": our_rev,
                        "name": rname,
                    })

# Build enrichment: for each domain deduplicate by clinic, pick best
enrichment = {}
for domain, records in hits.items():
    # Deduplicate by city+loc, keep max reviews
    seen = {}
    for rec in records:
        key = f"{rec['city']}|{rec.get('loc','')}"
        if key not in seen or (rec["reviews"] or 0) > (seen[key]["reviews"] or 0):
            seen[key] = rec

    recs = list(seen.values())
    # Best review count across all records
    rev_counts = [r["reviews"] for r in recs if r["reviews"]]
    best_rev = max(rev_counts) if rev_counts else None
    # Pick a maps URL (prefer one with cid=)
    maps_urls = [r["maps_url"] for r in recs if "cid=" in str(r["maps_url"])]
    if not maps_urls:
        maps_urls = [r["maps_url"] for r in recs if r["maps_url"]]
    best_maps = maps_urls[0] if maps_urls else ""
    # Best name
    names = [r["name"] for r in recs if r["name"]]
    best_name = max(names, key=len) if names else ""
    # All clinics with km data, sorted by distance — NO cap, keep all
    with_km = [r for r in recs if r["km"] is not None]
    with_km.sort(key=lambda x: x["km"])
    # Cities where they appear
    cities_seen = sorted(set(r["city"] for r in recs))

    enrichment[domain] = {
        "name": best_name,
        "reviews": best_rev,
        "maps_url": best_maps,
        "nearest_clinics": [
            {
                "city": r["city"],
                "loc": r["loc"],
                "km": r["km"],
                "our_reviews": r["our_reviews"],
                "their_reviews": r["reviews"],       # review count at THIS specific GMB profile
                "their_maps": r["maps_url"],          # GMB URL for THIS specific profile
                "their_name": r["name"],              # GMB name at this location
                "cat": r["cat"],                      # category in which they appear
            }
            for r in with_km
        ],
        "cities": cities_seen,
    }

out = os.path.join(DIR, "data_rival_enrichment.json")
with open(out, "w") as f:
    json.dump(enrichment, f, indent=1)

print(f"Saved: {out}")
print(f"Domains enriched: {len(enrichment)}")
for domain, e in sorted(enrichment.items(), key=lambda x: -(x[1]["reviews"] or 0)):
    near = ", ".join(f"{c['loc'] or c['city']} {c['km']:.1f}km" for c in e["nearest_clinics"][:3] if c["km"])
    print(f"  {domain:<40} rev={e['reviews']:<6} gmb={'✓' if e['maps_url'] else '✗'} near=[{near}]")
