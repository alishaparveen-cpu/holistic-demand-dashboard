#!/usr/bin/env python3
"""Extract the manager's per-campaign Google Ads WoW funnel (the 'consolidated' HTML export)
into data_ga_funnel.json for the master dashboard's Channel view.

Each campaign block is <h3 id="slug">Name</h3> ... <table> with rows:
  Spend / impression / · Location Impressions / click / · Loc Clicks /
  · Web Leads (UTM Campaign) / · City Phone Calls (Google Paid) /
  · GMB Phone Calls (Organic) / · Location Click to Category Specific Leads / book / done
Each row = <td>label</td> + 5 weekly <td> values (oldest→newest).
Weeks pinned by the change-log link (latest col = 2026-06-15→21) to Monday weeks:
  2026-05-18, 2026-05-25, 2026-06-01, 2026-06-08, 2026-06-15.

Category / type / city / tier are parsed from the campaign NAME (robust & self-contained).
Run: python3 scripts/extract_ga_funnel.py "/path/to/consolidated (3).html"
"""
import os, re, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKS = ["2026-05-18", "2026-05-25", "2026-06-01", "2026-06-08", "2026-06-15"]  # oldest→newest

# funnel row label (normalised, lowercased, no leading '·') -> json key
ROWMAP = {
    "spend": "spend", "impression": "impression", "location impressions": "loc_impr",
    "click": "click", "loc clicks": "loc_click", "web leads (utm campaign)": "web_leads",
    "city phone calls (google paid)": "city_calls", "gmb phone calls (organic)": "gmb_calls",
    "location click to category specific leads": "cat_leads", "book": "book", "done": "done",
}
TAG = re.compile(r"<[^>]+>")
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)


def clean(s):
    return TAG.sub("", s or "").replace("&nbsp;", " ").strip()


def num(s):
    s = clean(s).replace(",", "").replace("₹", "").replace("%", "").strip()
    if s in ("", "·", "-", "—", "–", "n/a", "NA"):
        return 0
    try:
        return round(float(s))
    except ValueError:
        return 0


CAT_TOK = {"MH": "MH", "SH": "SH", "STD": "STD", "STI": "STD", "PE": "SH", "ED": "SH"}


def classify(name):
    """category / type / city / tier from the campaign name."""
    toks = [t for t in re.split(r"[_\s]+", name) if t]
    up = name.upper()
    tier = toks[0] if toks else ""
    # category — first category token found, else Brand / Other
    cat = None
    catidx = None
    for i, t in enumerate(toks):
        if t.upper() in CAT_TOK:
            cat = CAT_TOK[t.upper()]
            catidx = i
            break
    if cat is None:
        cat = "Brand" if "BRAND" in up else "Other"
    # type: Local (city-mapped) / Online (national telehealth) / Lead
    if re.search(r"local", name, re.I):
        typ = "Local"
    elif re.search(r"online|highintent|hi_exact|_lt_", name, re.I) or tier.upper() in ("ROI", "ONL", "CC"):
        typ = "Online"
    else:
        typ = "Lead"
    # city — for T1/T2 local, the tokens between tier and the category token (handles Navi_Mumbai)
    city = ""
    if tier in ("T1", "T2") and catidx and catidx > 1:
        city = " ".join(toks[1:catidx])
    elif tier in ("T1", "T2") and len(toks) > 1:
        city = toks[1]
    elif up.startswith("BRAND"):
        city = "Brand"
    elif typ == "Online":
        city = "Online / National"
    return cat, typ, city, tier


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/consolidated (3).html")
    html = open(src, encoding="utf-8", errors="replace").read()
    # split into campaign blocks by <h3 id="...">Name</h3>
    heads = list(re.finditer(r'<h3 id="([^"]+)"[^>]*>(.*?)</h3>', html, re.S | re.I))
    camps = []
    for i, h in enumerate(heads):
        slug = h.group(1)
        name = clean(h.group(2).split("<span", 1)[0])   # drop the trailing status chip
        block = html[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        cid_m = re.search(r"campaign_id=(\d+)", block)
        cid = cid_m.group(1) if cid_m else None
        cat, typ, city, tier = classify(name)
        rows = {}
        for trm in TR.finditer(block):
            tds = TD.findall(trm.group(1))
            if len(tds) < 2:
                continue
            label = clean(tds[0]).lstrip("·").strip().lower()
            key = ROWMAP.get(label)
            if not key or key in rows:
                continue
            vals = [num(x) for x in tds[1:6]]
            if len(vals) == 5:
                rows[key] = vals
        if "spend" not in rows and "impression" not in rows:
            continue  # not a funnel table
        for k in ROWMAP.values():
            rows.setdefault(k, [0] * 5)
        camps.append({"slug": slug, "name": name, "id": cid, "category": cat,
                      "type": typ, "city": city, "tier": tier, "rows": rows})

    out = {"_meta": {"weeks": WEEKS, "source": os.path.basename(src),
                     "note": "Manager's per-campaign Google Ads WoW funnel (frozen 5-wk snapshot 2026-05-18→06-15). Category/type/city from campaign name.",
                     "n": len(camps)},
           "campaigns": camps}
    dst = os.path.join(ROOT, "data_ga_funnel.json")
    json.dump(out, open(dst, "w"), separators=(",", ":"))
    # summary
    from collections import Counter
    bycat = Counter(c["category"] for c in camps)
    bytyp = Counter(c["type"] for c in camps)
    tot = {k: sum(sum(c["rows"][k]) for c in camps) for k in ("spend", "impression", "click", "loc_click", "web_leads", "book", "done")}
    print("campaigns:", len(camps), "| by cat:", dict(bycat), "| by type:", dict(bytyp))
    print("totals (5wk):", tot)
    print("sample:", {k: camps[0][k] for k in ("name", "category", "type", "city", "tier")}, camps[0]["rows"]["spend"])


if __name__ == "__main__":
    main()
