# GMB Pattern Report — STI Share Drivers (v3, with keyword data)

**Sources joined:**
1. STI share data (internal Redshift) — % of consultations diagnosed STI per clinic
2. `locations.xlsx` — full GMB profile fields for 66 locations
3. `insights.csv` — 30-day GMB performance (impressions, calls, directions, clicks)
4. **`search_keywords.csv`** — 5,175 keyword-impression rows pulled from GBP Performance API for 64 locations

**Buckets** (≥10 total calls): Top (≥28% STI, n=10) | Mid (12–28%, n=27) | Low (<12%, n=9)

---

## TL;DR — The gap is NOT in GMB

After three rounds of analysis (titles → profile fields → search keywords), **GMB is not the lever**:

| Driver | Top tier | Low tier | Verdict |
|---|---|---|---|
| Profile completeness (cats, description, photos, hours, links) | Identical | Identical | ❌ not the lever |
| Title format & keyword stuffing | Same template, mostly | Same template | ❌ not the lever |
| STI-intent keyword impressions reaching profile | **5.0%** of impressions | **4.6%** of impressions | ❌ not the lever |
| Brand search share | 7.9% | 7.6% | Same |
| Sexologist-query share | 16.5% | **21.6%** | Low tier gets *more* sexologist queries |
| Generic-query share | 65.2% | 45.4% | Top tier ironically gets *more* generic queries |

**The search intent reaching each profile is almost identical.** Yet top clinics convert 25%+ of consultations to STI tags vs 4% for the bottom tier.

→ **The variance is downstream of GMB**, not in GMB.

---

## Where the gap actually lives (most likely)

Now that we've ruled out GMB profile and GMB search intent, the remaining explanations are:

1. **Diagnosis tagging discipline at the clinic level.** STI share comes from `allo_analytics.encounter_tags` where `tag_type='sti'`. If doctors at low-tier clinics record the same STI patients under a different tag (e.g. "ed_plus", "others", or no tag), STI share will look low even when underlying demand is the same. **This is testable.**

2. **Demographics of the clinic catchment.** Chennai metros and Bangalore IT corridors have a younger, more sexually-active patient mix. Smaller cities skew older / more ED-PE focused. Real, but not really fixable through GMB.

3. **Channel mix per clinic.** GMB is only one channel. Top clinics may pull STI patients through Practo, direct, paid search — channels where queries can be STI-specific. We haven't joined channel-level data per clinic.

4. **Intake/operations.** When a patient calls or walks in, are low-tier clinics steering them to consultations that get labeled as "STI" or as something more generic? Needs an in-clinic audit.

---

## Evidence trail

### Per-clinic intent share (top 10 by STI%)

| Clinic | STI share | Total impressions | STI keyword % | Brand % | Sexologist % | Generic % |
|---|---:|---:|---:|---:|---:|---:|
| Velachery (Chennai) | **39%** | 13,488 | 3.3% | 5.6% | 15.3% | 73.0% |
| Mogappair (Chennai) | 35% | 1,940 | 9.6% | 13.4% | 29.7% | 36.6% |
| Nungambakkam (Chennai) | 34% | 14,880 | 3.3% | 4.5% | 14.5% | **75.3%** |
| HSR Layout (Bangalore) | 32% | 5,410 | 5.3% | 11.1% | 24.8% | 50.6% |
| Koramangala (Bangalore) | 31% | 6,019 | 12.5% | 15.0% | 12.7% | 53.8% |
| Bellandur (Bangalore) | 28% | 3,196 | 10.4% | 17.3% | 23.4% | 32.4% |
| Electronic City (Bangalore) | 28% | 11,867 | 3.0% | 2.6% | 4.8% | **85.0%** |
| Kondapur (Hyderabad) | 28% | 9,979 | 5.2% | 8.4% | 25.7% | 54.6% |

**Velachery** — 39% STI consultations but only **3.3% STI-keyword impressions**. The vast majority of GMB traffic is generic ("sexologist near me", "clinic near me"), yet it converts at the highest STI rate in the network. 

### Per-clinic intent share (bottom 9 by STI%)

| Clinic | STI share | Total impressions | STI keyword % | Brand % | Sexologist % | Generic % |
|---|---:|---:|---:|---:|---:|---:|
| Ashok Nagar (Ranchi) | **2%** | 1,947 | **16.1%** | 5.8% | 44.7% | 18.3% |
| Arekere (Bangalore) | 4% | 3,952 | 3.0% | 10.6% | 21.5% | 54.6% |
| Kalyan West (Mumbai) | 4% | 2,140 | 4.1% | 20.4% | 37.6% | 21.0% |
| Nallagandla (Hyderabad) | 5% | 4,741 | 0.6% | 7.6% | 10.3% | 52.2% |
| Chinchwad (Pune) | 6% | 1,969 | **11.4%** | 12.1% | 29.0% | 29.4% |
| Tatya Tope Nagar (Nagpur) | 7% | 6,573 | 1.3% | 3.9% | 18.7% | 46.5% |
| Saraswathipuram (Mysuru) | 7% | 3,824 | 4.0% | 4.9% | 17.3% | 62.8% |
| Garkheda (Aurangabad) | 7% | 2,100 | 2.9% | 3.9% | 29.2% | 45.3% |
| Panvel (Mumbai) | 7% | 3,178 | 10.6% | 6.8% | 15.2% | 44.0% |

**Counter-intuitive examples:**
- **Ashok Nagar (Ranchi) — 2% STI consultations yet 16% STI-keyword impressions.** People searching `"sti test"` *do* reach this profile, but the resulting consultations don't get tagged STI.
- **Chinchwad — 11.4% STI keywords but 6% STI consults.** Same pattern.
- **Velachery — 3.3% STI keywords but 39% STI consults.** Reverse pattern at the top.

This is the strongest signal that **the issue is downstream of GMB matching** — exposure to STI-search demand isn't the constraint.

---

## Top STI-intent keywords (across all clinics, monthly impressions)

| Impressions | Keyword |
|---:|---|
| 1,318 | std |
| 1,246 | sti |
| 1,039 | sti test |
| 726 | syphilis treatment |
| 666 | std test |
| 489 | hiv test |
| 407 | hiv treatment |
| 372 | hiv |
| 245 | std testing near me |
| 181 | herpes test |
| 121 | hpv vaccination near me |
| 113 | std testing |
| 105 | chlamydia test |
| 100 | sti testing |
| 90 | syphilis test |

These are the queries actually bringing STI-intent traffic. Note how rare the volume is — only ~5K total monthly STI-keyword impressions across all 64 profiles. STI search demand is small; the conversion side has to be strong to compensate.

---

## What this changes about your action plan

### Drop these from the plan
- ❌ Rewriting business titles (template is mostly the same; doesn't move STI%)
- ❌ Adding keywords to descriptions (already there in 100% of top and 82% of low — same)
- ❌ Uploading more photos to underperformers (top has photos, low has photos)

### Keep these (they're still good housekeeping but not high-STI-leverage)
- ✅ Add logo photo to all 56 (0/56 have it — basic completeness)
- ✅ Add appointment URL to all 56 (universal gap)
- ✅ Fix Vijayanagar Bangalore — 0 GMB impressions = profile is broken / unranked
- ✅ Create Surat (Bhimrad) GMB listing — doesn't exist
- ✅ Fix Tatya Tope Nagar title (says "Nashik")

### NEW priorities — the real investigation

1. **Diagnosis tagging audit.** Pull last 30 days of consultations at 3 top clinics (Velachery, HSR, Koramangala) vs 3 bottom (Ashok Nagar, Arekere, Nallagandla). For each, look at:
   - % of consultations with ANY tag in `encounter_tags`
   - % tagged STI vs other tag types
   - Tag distribution per provider (is one doctor underreporting STI tags?)
   - Same patient seen at top vs low clinic — are the tags consistent?

2. **Cross-channel STI mix.** For each clinic, break STI share by booking source (GMB, Practo, direct, paid). The hypothesis is that **Practo + direct contribute disproportionately to top-tier STI**, not GMB. If Velachery's STI patients all come via Practo, that explains why low-tier GMB-heavy clinics underperform.

3. **Intake script review.** Listen to recorded GMB calls (if recorded) at 2 top and 2 bottom clinics. Are receptionists asking "are you here for STI testing?" or steering to generic "consultation"?

---

## Files in this audit

- `PATTERN_REPORT.md` — this file (v3, final)
- `LOW_TIER_EDIT_LIST.md` — per-clinic edits (still valid for housekeeping fixes)
- `full_audit.py` — joins all 4 data sources, produces tiered comparison
- `pull_keywords.py` — pulls GBP keywords via API
- `analyze_keywords.py` — classifies keywords by intent, produces the tables above
- `per_clinic_intent.csv` — per-clinic intent share for downstream analysis
- `search_keywords.csv` — raw GBP keyword data (5,175 rows)
- `gbp_locations.json`, `gbp_accounts.json` — raw GBP listing data
