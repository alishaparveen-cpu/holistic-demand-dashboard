#!/usr/bin/env python3
"""Build data_practo_flow.json — weekly Practo demand per clinic, from the Practo transactions CSV.

Source CSV columns: Patient_Phone_Number, dt (DD-MM-YYYY), amount, amount_refunded, net_amount,
mob_no, location (= Practo "Practice Locality"), provider, type (Book | Call), Booked.

  type=Book = in-clinic appointment · type=Call = teleconsult. The two are MUTUALLY EXCLUSIVE per
  patient (a phone is only ever one), both are paid Practo conversions. So per clinic × week:
     leads = distinct phones (book + call)   book = distinct phones (Book)   call = distinct phones (Call)

Locality → clinic reconciliation reuses PRACTO_ALIAS (validated in build_source_recon.py). City comes
from the master clinic list (data_source_recon display). Unmapped Practo localities are reported, not dropped.

Output: {_meta:{weeks[asc], source, note, unmapped}, clinics:{"City|Locality":{leads[],book[],call[]}}}
Run: python3 scripts/build_practo_flow.py <path-to-csv>   (pure local — no DB)
"""
import os, sys, csv, json, datetime, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.expanduser("~"), "Downloads", "Flow Dashboard view - Sheet37 (8).csv")

# clinic-locality -> extra Practo "Practice Locality" strings that are the SAME clinic (from build_source_recon)
PRACTO_ALIAS = {
    "Electronic City": ["Electronics City"], "Sahakara Nagar": ["Sahakaranagar"],
    "Borivali": ["Borivali East"], "Dadar": ["Dadar West"], "Chinchwad": ["Pimpri-Chinchwad"],
    "Thoraipakkam": ["Okkiyam Thuraipakkam"], "Gulmohar": ["Gulmohar Colony"],
    "Suryaraopeta": ["Suryaraopet"], "Vidya Nagar": ["Hubli Vidyanagar"],
    "Vaishali Nagar": ["Khatipura"], "Ashok Nagar": ["Bariatu"],
    "Tatya Tope Nagar": ["Mankapur Ring Road"], "Falnir Rd": ["Falnir"], "Thane": ["Thane West"],
}
# extra orphans this CSV surfaced that the alias map didn't cover (clinic loc -> Practo loc)
# (Bilekahalli · Bangalore and Borabanda · Hyderabad have no matching clinic in master → left unmapped, ~24 rows)
PRACTO_ALIAS_EXTRA = {
    "Gurugram": ["Sushant Lok I"],
}


def monday(d):
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def load_master_loc_city():
    """locality(lower) -> city, from data_source_recon display ('Locality · City')."""
    d = json.load(open(os.path.join(ROOT, "data_source_recon.json")))
    m = {}
    for slug, s in d["_meta"].get("display", {}).items():
        p = str(s).split(" · ")
        if len(p) >= 2:
            m[" · ".join(p[:-1]).strip().lower()] = p[-1].strip()
    return m


def main():
    loc2city = load_master_loc_city()
    # reverse alias: practo-location(lower) -> clinic-locality
    rev = {}
    for clinicloc, aliases in list(PRACTO_ALIAS.items()) + list(PRACTO_ALIAS_EXTRA.items()):
        for a in aliases:
            rev[a.strip().lower()] = clinicloc

    def resolve(location):
        """Practo location string -> (city, clinic_locality) or (None, None)."""
        loc = location.strip()
        ll = loc.lower()
        clinicloc = rev.get(ll, loc)                 # alias -> clinic locality (else itself)
        city = loc2city.get(clinicloc.lower()) or loc2city.get(ll)
        return (city, clinicloc) if city else (None, None)

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8", errors="replace")))
    # per key -> per type -> {week: set(phones)}
    agg = collections.defaultdict(lambda: {"book": collections.defaultdict(set),
                                           "call": collections.defaultdict(set)})
    weeks_seen = set()
    unmapped = collections.Counter()
    for r in rows:
        typ = (r.get("type") or "").strip()
        if typ not in ("Book", "Call"):
            continue
        loc = (r.get("location") or "").strip()
        if not loc or loc == "#N/A":
            continue
        try:
            d = datetime.datetime.strptime((r.get("dt") or "").strip(), "%d-%m-%Y").date()
        except ValueError:
            continue
        if d.year < 2020 or d.year > 2100:            # drop the 1899 Excel-epoch junk
            continue
        ph = "".join(c for c in (r.get("mob_no") or "") if c.isdigit())[-10:]
        if len(ph) < 10:
            continue
        city, clinicloc = resolve(loc)
        if not city:
            unmapped[loc] += 1
            continue
        wk = monday(d)
        weeks_seen.add(wk)
        agg[f"{city}|{clinicloc}"][("book" if typ == "Book" else "call")][wk].add(ph)

    weeks = sorted(weeks_seen)
    widx = {w: i for i, w in enumerate(weeks)}
    NW = len(weeks)

    clinics = {}
    for key, t in agg.items():
        book = [0] * NW
        call = [0] * NW
        leads = [0] * NW
        for wk in weeks:
            i = widx[wk]
            b = t["book"].get(wk, set())
            c = t["call"].get(wk, set())
            book[i] = len(b)
            call[i] = len(c)
            leads[i] = len(b | c)                     # union (mutually exclusive, but safe)
        clinics[key] = {"leads": leads, "book": book, "call": call}

    out = {"_meta": {"weeks": weeks,
                     "source": os.path.basename(CSV_PATH),
                     "note": "Practo transactions: leads = distinct patients/wk (book+call); book = in-clinic; call = teleconsult.",
                     "unmapped": dict(unmapped.most_common())},
           "clinics": clinics}
    outp = os.path.join(ROOT, "data_practo_flow.json")
    json.dump(out, open(outp, "w"), separators=(",", ":"))

    # ---- report ----
    print(f"data_practo_flow.json · {len(clinics)} clinics · {NW} weeks ({weeks[0]}→{weeks[-1]})")
    tot = lambda f: sum(sum(c[f]) for c in clinics.values())
    print(f"  totals over window: leads {tot('leads')} · book {tot('book')} · call {tot('call')}")
    vwk = "2026-06-29"
    if vwk in widx:
        i = widx[vwk]
        L = sorted(((c["leads"][i], k) for k, c in clinics.items()), reverse=True)[:8]
        print(f"\n── {vwk} top clinics (leads = book+call) ──")
        for v, k in L:
            c = clinics[k]
            print(f"  {k:34} leads {v:4}  (book {c['book'][i]}  call {c['call'][i]})")
    if unmapped:
        print(f"\n[unmapped Practo localities — dropped] {dict(unmapped)}")


if __name__ == "__main__":
    main()
