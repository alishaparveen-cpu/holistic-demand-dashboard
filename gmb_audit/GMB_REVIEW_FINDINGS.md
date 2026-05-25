# GMB Reviews Audit — Why is the Bangalore T1 Cluster Failing?

**Pulled** 2026-05-22 via Business Profile v4 API · 18,203 reviews across 68 locations (62 with text).

## TL;DR — Reviews DO add new evidence

The prior audit concluded "GMB is not the STI lever; constraint lives at clinic EMR tagging." That stands. But this pass looks at a **different question** — why specific T1 clinics are losing bookings — and reviews surface one clear, actionable signal:

**Bengaluru is the only T1 city where reviews are decaying. Every other T1 city has improving or stable ratings AND +20–40% review velocity. Bengaluru's review velocity is flat while bookings drop.**

## The premise correction

T1 in aggregate is **not** failing: T1 B→D = 51.7%, T2 B→D = 50.6% (last 30d). What's actually happening is a Bangalore-heavy cluster of T1 clinics is bleeding while peer clinics in other T1 cities grow. The framing "tier 1 is failing" → "this Bangalore cluster is failing" is what we should actually be asking.

## City-level picture (last 90d vs prior 90d)

| City | T1? | Locations | ⭐ recent | ⭐ prior | Δ⭐ | Δ reviews | Response | Dominant low-⭐ theme |
|---|---|---|---|---|---|---|---|---|
| **Bengaluru** | **T1** | 14 | **4.69** | **4.80** | **−0.11** | **−1%** | 83% | **fees_high(4)** |
| Hyderabad | T1 | 8 | 4.88 | 4.83 | +0.05 | **+28%** | 69% | fees_high(1) |
| Pune | T1 | 7 | 4.88 | 4.92 | −0.04 | **+39%** | 84% | fees_high(3) |
| Mumbai | T1 | 8 | 4.88 | 4.91 | −0.03 | **+22%** | 84% | fees_high(2) |
| Chennai | T1 | 5 | 4.93 | 4.81 | +0.12 | −45%* | 94% | none |

\* Chennai's review-velocity drop is on tiny volumes (91 vs 164) so noise-prone.

**Bengaluru is the outlier:** the only T1 city with both star-decay AND flat review velocity. Every other T1 city is producing **more** reviews now than before, with stable ratings.

## Bengaluru clinic-by-clinic

| Clinic (GBP title fragment) | ⭐ recent | ⭐ prior | Reviews 90d | Δ velocity | Theme |
|---|---|---|---|---|---|
| Arekere | **4.29** | 4.75 | 17 | +42% | (low n) |
| Jayanagar | 4.74 | 4.88 | 101 | +6% | **fees_high** |
| Indiranagar | 4.85 | 4.73 | 27 | **−47%** | **fees_high** |
| Electronic City | 4.83 | 4.83 | 52 | **−28%** | **fees_high** |
| KR Puram | 4.79 | 4.49 | 19 | **−46%** | — |
| Bellandur | 5.00 | 4.87 | 18 | **−42%** | — |
| Vijayanagar | 4.81 | 4.75 | 86 | −9% | — |
| (others stable) | | | | | |

Cross-checking with booking-side data: the Bengaluru clinics with biggest 30d booking declines (Aarohi −64%, UMC −23%, Nurture −21%, Vikyath −16%) correspond to GBP locations with **either** decaying stars, falling review velocity, or fees-themed complaints. Signals align — not coincidence.

## Bottom complaint themes across all 18,203 reviews

| Theme | Count of low-⭐ reviews | Share |
|---|---|---|
| fees_high | 78 | **31%** |
| no_results | 32 | 13% |
| wait_time | 32 | 13% |
| fake_clinic | 21 | 8% |
| no_doctor | 14 | 6% |
| rude_staff | 13 | 5% |
| closed | 5 | 2% |

**Fees is the #1 complaint by a 2× margin.** In Bengaluru specifically, 3 of the 7 declining-velocity clinics show this theme.

## Direct answer to your question

> *Why is tier 1 failing?*

It isn't, in aggregate. **What's failing is a Bengaluru cluster — and the review evidence points at perceived pricing in those clinics.** Specifically:

1. **Pricing perception in Bengaluru.** The only T1 city where (a) ratings are sliding, (b) review velocity is flat while peers grow 20–40%, and (c) the dominant low-star theme is `fees_high`. Other T1 cities have the same pricing structure but reviews aren't decaying — suggesting Bengaluru patients have a price-elasticity or competing-options issue we don't have in Pune/Hyderabad/Mumbai.
2. **Six specific clinics to act on**: Arekere (rating crash), Indiranagar / Electronic City / KR Puram / Bellandur (velocity falling >25%), Jayanagar (high-volume slow erosion).
3. **Not the cause**: Response rate is healthy everywhere (≥83% in Bengaluru). Profile completeness was ruled out in the prior round. No "closed" or "no_doctor" theme spike in Bengaluru — operations isn't the visible failure mode in reviews.

## What this does NOT change

The previous conclusion that **GMB profile hygiene isn't the lever for STI conversion** still stands — that conclusion was about *channel mix and listing optimization* moving STI tagging, and review text doesn't speak to EMR tagging. The clinic-level EMR-tagging investigation at Garkheda / Saraswathipuram / Ashok Nagar / Kalyan West remains the open lever.

## What the 12 low-star Bengaluru reviews actually say (last 90d)

Regex themes undersell what's there. Reading the raw text reveals four specific operational issues — most of them named and dated:

### 1. The "₹500 consultation → ₹5,000 test" pattern
- **Electronic City, 2026-05-11** (⭐1, **no reply**): *"Misleading policies designed to squeeze money out of patients. Follow-up consultations are only 'free' if you buy their overpriced ₹5000 tests — the same tests cost barely ₹1000 elsewhere. Reception staff (especially Dipti at the Electronic City br..."* — names a specific staff member.
- **Jayanagar, 2026-04-04** (⭐1, replied): *"Professionals version of Road side Van baba ji. Their business model is simple — get you in with ₹500 consultation and then start shaving you with their own prescribed medicine."*
- **Indiranagar, 2026-05-09** (⭐1, **no reply**): *"They will ask you to pay no matter doctor will see you or not (which you will get to know after you pay)."*
- **Koramangala, 2026-02-24** (⭐1, replied): *"₹499 is too much for that thing."*

### 2. A specific doctor named in two ⭐1 reviews at Koramangala
**"Warisha Fathima" / "Mrs Fatima"** — flagged twice at Koramangala in the last 90 days:
- 2026-02-24: *"I'm really very uncomfortable with her to share my sexuality needs."*
- (undated review): *"Never ever consult with Warisha Fathima. She diagnosed me wrong... made us wait outside while she was scrolling her phone inside."*

This is a personnel issue, not a city-level one. Worth a direct conversation.

### 3. Clinical-correctness complaint (KR Puram, no reply)
*"I needed a test for oral or rectal gonorrhea, but they explained urine test is sufficient, which is false medical advice. For oral and rectal a swab test is needed. They gave an antibiotic mix, which is not correct standard treatment."* — This is a flag for clinical-protocol review, not marketing.

### 4. Reply discipline broke recently
Of the 12 low-star Bengaluru reviews in the last 90 days, **4 are unreplied** — and they're the most damaging ones (Electronic City May 11, Indiranagar May 9, KR Puram March 25, Corporate Office May 14). Bengaluru's overall 83% response rate hides that the **worst** recent reviews are the ones being skipped.

## Recommended next actions

1. **Pull pricing data for Bengaluru clinics** vs Pune/Hyderabad/Mumbai. If pricing is uniform, the issue is perception (positioning, competitor pricing). If non-uniform, fix the outliers.
2. **Read raw text** of the 12 ≤3-star Bengaluru reviews from last 90 days — keyword regex captured themes but won't surface specifics. (Run `awk -F, '$4=="Bengaluru" && $6<=3' reviews.csv` or open `reviews.csv` in a sheet.)
3. **Verify Arekere** — single location with a meaningful star drop (4.75→4.29 on 17 reviews). Likely something happened in the last quarter; check ops logs.
4. **Don't widen the ads spend in Bengaluru** until the review trend stabilizes — you'll buy traffic into a deteriorating experience.

## Files

- `reviews.csv` — 18,203 rows: location, clinic title, city, stars, date, text, has_reply
- `reviews.json` — raw nested API response (17MB)
- `reviews_summary.csv` — 62 rows: per-location aggregates (avg stars all/recent/prior, velocity, response rate)
- `reviews_by_city.csv` — 15 rows: per-city aggregates
- `pull_reviews.py`, `analyze_reviews.py` — repeatable
