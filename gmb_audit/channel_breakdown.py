"""
Channel-level breakdown per clinic.
For each STI-tracked locality, computes the source mix of completed consultations
in the last 30 days and how much of each source ends up tagged STI.

Identifies clinics where:
  - source mix is heavily skewed (e.g., >70% GMB but other sources missing)
  - GMB volume is high but STI conversion is low (operations/intake issue)
  - Practo / Google / FB are pulling no STI (channel-mix issue)
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


# ---- Hard-coded match: STI locality → Redshift clinic name (by address substring) ----
# Derived from inspecting allo_health.locations.address
LOCALITY_TO_CLINIC = {
    # Bangalore
    "Kengeri": "Aarohi_Allo_Clinic",
    "Jayanagar": "Adhventha_Allo_Clinic",
    "Koramangala": "Cudur_Allo_Clinic",
    "KR Puram": "HealthPlus_Allo_Clinic",
    "Vijayanagar": "Jeevasare_Allo_Clinic",
    "Indiranagar": "Life_Plus_Allo_Clinic",
    "Electronic City": "NEO- Allo_Clinic",
    "Bellandur": "Nurture_Allo_Clinic",
    "Arekere": "Svasti_Allo_Clinic",
    "Whitefield": "TIDE_Allo Clinic",
    "HSR Layout": "UMC",
    "Sahakara Nagar": "Vikyath_Allo_Clinic",
    # Chennai
    "Nungambakkam": "Birthwave_Allo_Clinic",
    "Velachery": "Lapser_Allo_Clinic",
    "Mogappair": "MMRV_Allo_Clinic",
    "Thoraipakkam": "Pearl_Singapore_Allo_Clinic",
    "Tambaram": "Sai_Doctors_Allo_Clinic ",  # note trailing space
    # Coimbatore
    "Bharathi Nagar": "Heart_&_Her_Allo_Clinic",
    # Hyderabad
    "Kondapur": "HALE-Allo_Clinic",
    "Narsingi": "MedSurge_Allo_Clinic",
    "Sainikpuri": "Olive_Tree_Allo_Clinic",
    "Ameerpet": "RAD_Allo_Clinic",
    "Kukatpally": "Sravanthi_Allo_Clinic",
    "Nallagandla": "Sree_vedha_Allo_Clinic",
    # Jaipur
    "Vaishali Nagar": "Asha_Clinic_Allo_Clinic",
    # Mangaluru
    "Falnir Rd": "Lifeline_Allo_Clinic",
    # Mumbai
    "Andheri East": "Apple_Allo-Clinic",
    "Dadar": "Thakur_Allo_Clinic",
    "Kalyan West": "Vatsal-Allo Clinic",
    "Ghatkopar": "Vedant_Allo_Clinic",
    "Malad": "Zenith_Allo_Clinic",
    # Mysuru
    "Saraswathipuram": "DHC- Allo Health Sexual Wellness Clinic",
    # Nagpur
    "Tatya Tope Nagar": "Medicure_Allo_Clinic",
    # Nashik
    "Trimurti Chowk": "Trimurti_Allo_Clinic",
    # Navi Mumbai
    "Thane": "Infinity_Allo_Clinic",  # address says Thane
    "Panvel": "Bhusare_Allo_Clinic",
    "Kharghar": "Kharghar_Multispeciality_Allo_Clinic",
    # Pune
    "Baner": "Baner_Allo_Health",
    "Wakad": "Curesta_Allo_Clinic",
    "Kothrud": "DMS_Allo_Clinic",
    "Kharadi": "Pune_SSC_Allo_Clinic",
    "Katraj": "Sainath_Allo_Clinic",
    "Hadapsar": "Savali_Allo_Clinic",
    "Chinchwad": "Shree_Sadguru_Allo_Clinic",
    # Ranchi
    "Ashok Nagar": "Jeevah_Allo_Clinic",
    # Surat
    "Bhimrad": "Bombay_Multi_Allo_Clinic",
    # Visakhapatnam
    "MVP Colony": "Lalit_Healthcare_Allo_Clinic",
    # Aurangabad
    "Garkheda": "MediArts_Hospital_Allo_Clinic",
    # Hubli
    "Vidya Nagar": "Ashoka_Multi-Specialty_Allo_Clinic",
    # Vijayawada
    "Suryaraopeta": "Medicare_Allo_Clinic",
}


def load_sti():
    rows = []
    with open(HERE / "sti_share.csv") as f:
        for r in csv.DictReader(f):
            r["avg_sti_pct"] = float(r["avg_sti_pct"]) if r["avg_sti_pct"] else None
            r["total_calls"] = int(r["total_calls"])
            r["sti_calls"] = int(r["sti_calls"])
            rows.append(r)
    return rows


def load_channel_data(path: Path) -> dict:
    """clinic_name → {source: {done, sti_done}}"""
    out = defaultdict(lambda: defaultdict(lambda: {"done": 0, "sti_done": 0}))
    with open(path) as f:
        for r in csv.DictReader(f):
            clinic = r["clinic"]
            src = r["source"]
            out[clinic][src]["done"] += int(r["done"])
            out[clinic][src]["sti_done"] += int(r["sti_done"])
    return out


def tier_of(pct):
    if pct is None: return None
    if pct >= 28: return "top"
    if pct >= 12: return "mid"
    return "low"


def main():
    sti = load_sti()
    chan = load_channel_data(HERE / "redshift_clinic_source.csv")

    SOURCES = ["gmb", "google", "organic", "practo", "fb", "directwalkin", "other"]

    print("=" * 110)
    print("PER-CLINIC SOURCE-MIX (last 30d, COMPLETED + tagged) — sorted by truth STI%")
    print("=" * 110)
    print(f"{'Clinic':<22} {'City':<14} {'truth STI%':>10} | {'src':<6} {'done':>5} {'sti':>4} {'sti%':>5}    {'src':<6} {'done':>5} {'sti':>4} {'sti%':>5}    {'src':<6} {'done':>5} {'sti':>4} {'sti%':>5}")
    print("-" * 110)

    insights = []
    for s in sorted(sti, key=lambda r: -(r['avg_sti_pct'] or -1)):
        if s["avg_sti_pct"] is None or s["total_calls"] < 10:
            continue
        clinic = LOCALITY_TO_CLINIC.get(s["clinic"])
        if not clinic or clinic not in chan:
            continue
        src_data = chan[clinic]
        # Get top-3 sources by done
        top_srcs = sorted(src_data.items(), key=lambda x: -x[1]["done"])[:3]
        line = f"{s['clinic']:<22} {s['city']:<14} {s['avg_sti_pct']:>9.0f}% | "
        for src_name, d in top_srcs:
            sti_pct = (d["sti_done"]/d["done"]*100) if d["done"] else 0
            line += f"{src_name:<6} {d['done']:>5} {d['sti_done']:>4} {sti_pct:>4.0f}%    "
        print(line)

        # Compute clinic-level metrics
        total_done = sum(d["done"] for d in src_data.values())
        total_sti = sum(d["sti_done"] for d in src_data.values())
        gmb_done = src_data.get("gmb", {}).get("done", 0)
        gmb_sti = src_data.get("gmb", {}).get("sti_done", 0)
        practo_done = src_data.get("practo", {}).get("done", 0)
        practo_sti = src_data.get("practo", {}).get("sti_done", 0)
        google_done = src_data.get("google", {}).get("done", 0)
        google_sti = src_data.get("google", {}).get("sti_done", 0)
        organic_done = src_data.get("organic", {}).get("done", 0)
        organic_sti = src_data.get("organic", {}).get("sti_done", 0)

        insights.append({
            "clinic": s["clinic"], "city": s["city"], "tier": tier_of(s["avg_sti_pct"]),
            "truth_sti_pct": s["avg_sti_pct"], "truth_total_calls": s["total_calls"], "truth_sti_calls": s["sti_calls"],
            "rs_total_done": total_done, "rs_sti_done": total_sti,
            "rs_sti_pct": (total_sti/total_done*100) if total_done else 0,
            "gmb_share_of_done": gmb_done/total_done*100 if total_done else 0,
            "practo_share_of_done": practo_done/total_done*100 if total_done else 0,
            "google_share_of_done": google_done/total_done*100 if total_done else 0,
            "organic_share_of_done": organic_done/total_done*100 if total_done else 0,
            "gmb_sti_pct": (gmb_sti/gmb_done*100) if gmb_done else 0,
            "practo_sti_pct": (practo_sti/practo_done*100) if practo_done else 0,
            "google_sti_pct": (google_sti/google_done*100) if google_done else 0,
            "organic_sti_pct": (organic_sti/organic_done*100) if organic_done else 0,
        })

    print()
    print("=" * 110)
    print("PER-SOURCE STI% BY TIER (avg across clinics)")
    print("=" * 110)
    print(f"{'Tier':<10} {'n':>3} {'GMB STI%':>10} {'Google STI%':>13} {'Organic STI%':>14} {'Practo STI%':>13}")
    for tier in ("top","mid","low"):
        rows = [i for i in insights if i["tier"] == tier]
        if not rows:
            continue
        def avg(key):
            valid = [r[key] for r in rows if r[key] > 0 or True]  # include zeros
            return sum(valid) / len(valid) if valid else 0
        print(f"{tier.upper():<10} {len(rows):>3} {avg('gmb_sti_pct'):>9.1f}% {avg('google_sti_pct'):>12.1f}% {avg('organic_sti_pct'):>13.1f}% {avg('practo_sti_pct'):>12.1f}%")
    print()

    print("=" * 110)
    print("LOW-TIER DEEP DIVE — what's the issue per clinic?")
    print("=" * 110)
    for i in sorted([i for i in insights if i["tier"] == "low"], key=lambda r: r["truth_sti_pct"]):
        flags = []
        if i["gmb_share_of_done"] > 60: flags.append(f"over-dependent on GMB ({i['gmb_share_of_done']:.0f}%)")
        if i["gmb_sti_pct"] < 10 and i["gmb_share_of_done"] > 20: flags.append(f"GMB STI conv weak ({i['gmb_sti_pct']:.0f}%)")
        if i["practo_share_of_done"] < 5: flags.append("Practo absent")
        if i["google_sti_pct"] < 5 and i["google_share_of_done"] > 10: flags.append(f"paid Google STI conv weak ({i['google_sti_pct']:.0f}%)")
        if i["organic_sti_pct"] < 10 and i["organic_share_of_done"] > 10: flags.append(f"organic STI conv weak ({i['organic_sti_pct']:.0f}%)")
        print(f"  {i['clinic']} ({i['city']})  truth STI={i['truth_sti_pct']:.0f}%  rs STI={i['rs_sti_pct']:.0f}%")
        print(f"    Source mix: GMB {i['gmb_share_of_done']:.0f}% · Google {i['google_share_of_done']:.0f}% · Organic {i['organic_share_of_done']:.0f}% · Practo {i['practo_share_of_done']:.0f}%")
        print(f"    Per-source STI%: GMB {i['gmb_sti_pct']:.0f}% · Google {i['google_sti_pct']:.0f}% · Organic {i['organic_sti_pct']:.0f}% · Practo {i['practo_sti_pct']:.0f}%")
        print(f"    Flags: {'; '.join(flags) if flags else 'none'}")
        print()

    # Save full per-clinic results
    with open(HERE / "per_clinic_channel.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(insights[0].keys()))
        w.writeheader()
        w.writerows(insights)
    print(f"Saved per-clinic channel breakdown → per_clinic_channel.csv ({len(insights)} rows)")


if __name__ == "__main__":
    main()
