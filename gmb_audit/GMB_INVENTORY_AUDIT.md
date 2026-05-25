# GMB Inventory Audit — Photos · Videos · Services · Products · Reviews

**Pulled** 2026-05-22 via Business Profile API · 68 locations · 0 API failures.

## Grand totals

| Asset | Total | Avg / clinic | STI-specific | STI share |
|---|---:|---:|---:|---:|
| Photos | **1,989** | 29 | n/a | — |
| Videos | **258** | 3.8 | n/a | — |
| Services | **4,818** | 71 | **1,488** | **31%** |
| Products | **0** | 0 | 0 | — |
| Reviews | **18,203** | 268 | **586** | **3.2%** |

Notable: **no clinic has any products listed** in GBP — that's fine for a healthcare service, but worth knowing. **Only 3.2% of reviews mention STI/STD/HIV keywords** despite STI being a primary service line — patients write about consult experience, pricing, and outcomes, not condition names.

## Tier 1 vs Tier 2

| Tier | Locations | Photos | Videos | Services | STI svcs | Reviews | STI reviews |
|---|---:|---:|---:|---:|---:|---:|---:|
| **T1** | 49 | 1,545 | 128 | 3,746 | 1,192 | 16,230 | 520 |
| **T2** | 13 | 407 | 28 | 970 | 279 | 1,684 | 66 |
| unlabeled | 6 | 37 | 102 | 102 | 17 | 289 | 0 |

T1 has ~3× the photos per clinic of T2 (32 vs 31), comparable services per clinic (76 vs 75), and ~5× more reviews per clinic (331 vs 130). Average video count is similar (2.6 vs 2.2) — but video is sparse everywhere.

## By city — STI-review mention rate is the most diagnostic column

Cities sorted by review count, with STI-mention rate as a perception indicator:

| City | Locs | Photos | Videos | Svcs | STI svcs | Reviews | STI rev | STI rev % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bengaluru | 16 | 537 | 44 | 1,258 | 373 | 6,262 | 180 | 2.9% |
| Hyderabad | 8 | 212 | 24 | 537 | 182 | 2,987 | 134 | **4.5%** |
| Mumbai | 9 | 249 | 24 | 715 | 220 | 2,985 | 63 | 2.1% |
| Pune | 7 | 185 | 9 | 581 | 197 | 1,647 | 58 | 3.5% |
| Chennai | 6 | 199 | 3 | 265 | 93 | 1,059 | 29 | 2.7% |
| Navi Mumbai | 2 | 69 | 6 | 130 | 38 | 616 | 22 | 3.6% |
| Thane | 1 | 38 | 18 | 80 | 27 | 482 | 20 | **4.1%** |
| Attapur (Hyd) | 1 | 24 | 0 | 90 | 31 | 188 | 13 | **6.9%** |
| Mangaluru | 1 | 32 | 2 | 89 | 31 | 152 | 11 | **7.2%** |
| Vijayawada | 1 | 21 | 4 | 89 | 31 | 65 | 10 | **15.4%** |
| Visakhapatnam | 1 | 25 | 0 | 89 | 31 | 19 | 4 | **21.1%** |
| Bhopal | 1 | 38 | 0 | 0 | 0 | 18 | 5 | **27.8%** |

**Pattern:** small Tier-2 cities (Vizag, Bhopal, Vijayawada) have unusually high STI-mention rates — patients there talk about STI specifically. In metro markets (Bengaluru, Mumbai) the conversation skews toward consult experience and fees. This matches the prior audit's finding that low-tier clinics get more STI search intent but convert it worse downstream.

## Inventory gaps to act on

### 16 clinics with ZERO STI services listed

If a patient searches "STI clinic near me" and lands on the GBP profile, an empty service list means Google won't surface it for that intent. Highest-traffic gaps:

| Clinic | City | Tier | Reviews | Gap |
|---|---|---|---:|---|
| Nungambakkam | Chennai | T1 | **300** | 0 STI services |
| Nashik | Nashik | T2 | 81 | 0 STI services (also: 0 services at all) |
| Corporate Office | Bengaluru | T1 | 45 | 0 STI services |
| Aurangabad | Aurangabad | T2 | 37 | 0 STI services (also: 0 services at all) |
| Nallagandla | Hyderabad | T1 | 36 | 0 STI services |
| Panvel | Mumbai | T1 | 34 | 0 STI services |
| Thoraipakkam | Chennai | T1 | 25 | 0 STI services |
| Bhopal | Bhopal | T2 | 18 | 0 STI services |
| Hubli | Hubballi | T2 | 14 | 0 STI services |
| Madhapur | Hyderabad | T1 | 4 | 0 STI services |

**The 8 clinics here that have BOTH 0 STI services AND 0 services total** are missing the service-list configuration entirely: Aurangabad, Bhopal, Hubli, Nashik, plus 2 admin/unlabeled entries.

### 25 clinics with ZERO videos (high-review subset)

These have good written reviews but no video content — patients searching for "what does the clinic look like" get text-only:

| Clinic | City | Photos | Reviews |
|---|---|---:|---:|
| Vijayanagar | Bengaluru | 39 | 463 |
| Ranchi | Ranchi | 41 | 399 |
| Dadar | Mumbai | 32 | 336 |
| Kharghar | Navi Mumbai | 29 | 248 |
| Attapur | Hyderabad | 24 | 188 |
| Kengeri | Bengaluru | 16 | 181 |
| Chinchwad | Pune | 12 | 139 |
| Dilsukhnagar | Hyderabad | 6 | 73 |

### 3 clinics with ZERO photos

Caught from the raw CSV — these are likely brand-new or admin entries. Worth verifying they should be live profiles at all.

## Best-stocked profiles (positive controls)

By photos: Indiranagar (64), HSR Layout (57), Electronic City (52), Ghatkopar (52), Velachery (52) — 4 of top-5 in Bengaluru/Mumbai.

By services: Indiranagar (262), Coimbatore (258), Andheri East (128), Borivali (106), Vashi (102). Top-2 are 2-3× richer than the rest — suggests these were manually expanded beyond the standard 75-service template.

By STI services: Borivali Mumbai (34), Koramangala Bengaluru (32), then a cluster at 31 (the standard STI template). Most STI-equipped clinics have an identical 31-service template (Herpes Treatment, Chlamydia Treatment, STD Symptom Relief Plans, STI Partner Notification Support, Walk-In STD Treatment, Herpes Specialist Consultation, Chlamydia and Gonorrhea Treatment, plus 24 more) — so STI service count is a binary "template applied / not applied" signal, not a continuous quality metric.

## Connection to prior audits

- **Bengaluru cluster decline** (per the May 22 review audit): the 16 Bengaluru locations have 1,258 services (highest of any city), 537 photos (highest), and 6,262 reviews (3× the next city). It's the **most-equipped market in the network** — yet bookings are dropping. Inventory is not the lever.
- **STI tagging conclusion** (prior 4-round audit): the 16 clinics with 0 STI services are real GMB hygiene gaps but **wouldn't fix STI tagging share** — that issue lives in EMR diagnosis recording, not in whether the GBP service list mentions STI.

So the gaps surfaced here are **legitimate hygiene fixes** (especially the 16 clinics with 0 STI services and the 25 with 0 videos) but **shouldn't be expected to move bookings materially in metros**. The Bengaluru cluster decline is downstream of GMB.

## Files

- `gmb_inventory.csv` — per-clinic totals (68 rows, 16 columns)
- `gmb_services_raw.json` — full service list per location (~17MB)
- `gmb_media_raw.json` — full media metadata per location
- `pull_inventory.py`, `analyze_reviews.py`, `pull_reviews.py` — repeatable
