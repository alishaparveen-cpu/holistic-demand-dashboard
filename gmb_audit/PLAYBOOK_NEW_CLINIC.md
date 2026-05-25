# GMB Playbook for New Clinics — Allo Health

Targets are derived from the May 2026 inventory audit of 68 live Allo locations (`gmb_inventory.csv`, `reviews.csv`). Every benchmark below is what mature clinics in our own network actually have — not generic blog advice.

## What "good" looks like in our network

| Metric | Network median | Top-15 best profiles | Minimum acceptable |
|---|---:|---:|---:|
| Photos | 32 | 44 | **20** |
| Videos | 3 | 4 | **1** (must have at least one) |
| Services listed | 89 | 89 | **89** (standard template) |
| STI services | 31 | 31 | **31** (standard template) |
| Reviews after 90 days | 97 | — | **70** |
| Reviews after 12 months | 368 | 597 | **250** |
| Review velocity | 18.6/mo | 20.8/mo | **15/mo** (sustained) |
| Avg star rating | — | 4.85+ | **4.70** |

The 89-service / 31-STI template is non-negotiable — it's what every well-performing Allo clinic uses. Don't customize it for new clinics.

---

## Pre-launch checklist (Days −14 to 0)

Run all of these **before** the clinic accepts its first patient:

- [ ] **Create GBP profile** via Business Profile Manager (request verification 14 days before launch — verification can take 5–14 days)
- [ ] **Title** — use the exact standard template:
  `Allo Health, [Hood] - Best Sexologist in [City] | Sex Doctor | Sex Therapist | Sex Clinic | STD/STI Testing`
  - Replace `[Hood]` with neighborhood (e.g. "Koramangala", "Tambaram"). Keep the comma, en-dash, and pipe punctuation exactly as shown.
  - Replace `[City]` with the city name as Google spells it (use **"Bengaluru" not "Bangalore"**, **"Mysuru not Mysore"** — Google's locality field is authoritative). For dual-spelling cities, include both: `Mysuru / Mysore`.
  - **Do NOT add more keywords** beyond the template. The prior audit found 11 low-STI clinics had identical title hygiene to top clinics — adding more keywords doesn't help conversion and risks Google suspension for keyword stuffing. The title is already at the edge of GBP's allowed length.
- [ ] **Primary category:** `Sexologist`
- [ ] **Additional categories** (these matter — they're how GBP surfaces the profile for condition-specific searches):
  - STD clinic
  - STD testing service
  - HIV testing center
  - Sex therapist
  - Sexual health clinic
  - Family planning center (optional, for clinics offering broader services)
- [ ] **Address** — exact street address, verified pin drop on map
- [ ] **Hours** — full week including weekends; mark holidays
- [ ] **Phone** — clinic-specific number, not corporate routing (Google penalizes shared numbers across profiles)
- [ ] **Appointment URL** — direct booking link to the clinic's slot system, NOT homepage
- [ ] **Website URL** — clinic-specific landing page if available; otherwise the city page on alohealth.com
- [ ] **Description** — 750 chars max. Pattern: 2 sentences on services + 2 sentences on conditions treated. Include "STD/STI testing" naturally — do not stuff
- [ ] **Logo upload** — Allo brand logo (required; the prior audit found logo-missing clinics underperformed)
- [ ] **Cover photo** — clinic exterior or reception, brand-quality. NOT a stock image
- [ ] **Services list** — apply the standard **89-service template** (31 STI-specific + 58 general sexology). Don't ship without this — 16 currently-live Allo clinics still have zero services and they're invisible to condition-specific search

---

## Days 0–30 (launch month)

- [ ] **20+ photos uploaded** (network minimum). Cover: exterior, reception, consult room, doctor portraits, signage, before-and-after if available, certificates
- [ ] **1+ video** (network minimum). Pattern that works: 30–60 sec clinic walkthrough or doctor introduction
- [ ] **First 5 Google posts** — opening announcement, services snapshot, doctor introduction, hours, "what to expect at your first visit". One per ~5 days
- [ ] **Q&A seeded** — pre-populate 8–10 common Q&As from the chain's FAQ (cost, what tests, confidentiality, walk-in vs appointment, what to bring)
- [ ] **Request reviews from first 20 patients** — staff training: ask at end of consultation, hand the patient the Maps URI shortlink. Target 20 reviews by Day 30
- [ ] **Reply to every review** — even 5-stars. Response rate is a ranking factor; mature Allo clinics run 80–100% reply rate

**Day-30 hygiene check:**

| Check | Pass | Investigate if |
|---|---|---|
| Photos | ≥20 | <15 |
| Reviews | ≥20 | <10 (review-request workflow broken at clinic) |
| Avg ⭐ | ≥4.7 | <4.5 |
| Reply rate | 100% | any unreplied |
| GBP impressions (Insights) | rising week-on-week | flat → check profile is verified and live |

---

## Days 31–90

- [ ] **Reach 30+ photos cumulative** (network median)
- [ ] **3+ videos cumulative** (network median). Add at this stage: patient testimonial (with consent), doctor explainer on a common condition, clinic-tour update if anything new opened
- [ ] **Posts cadence: 1/week** — alternate service highlights, doctor tips, "what is X / when to test for X"
- [ ] **Review velocity: target 70–100 new reviews by Day 90** (network: median is 97, p25 is 78). This is the period where the clinic's GBP rank settles
- [ ] **Track top search queries** in GBP Insights — if a clinic is appearing for queries it shouldn't (wrong city, wrong service), the title or categories are wrong
- [ ] **Photo categories balanced**: Google distinguishes Interior / Exterior / Team / Identity (logo+cover) / Additional. Make sure each is non-empty

**Day-60 hygiene check:**

| Check | Pass | Investigate if |
|---|---|---|
| Photos | ≥25 | <18 |
| Videos | ≥2 | 0 |
| Reviews | ≥50 | <40 |
| Avg ⭐ | ≥4.75 | <4.6 |
| Review velocity (last 30d) | ≥15 | <10 (run a review push) |
| Reply rate (last 30d) | ≥90% | <80% |
| GBP impressions | growing | flat or down |

**Day-90 hygiene check (the critical one):**

| Check | Pass | Investigate if |
|---|---|---|
| Photos | ≥30 (median) | <25 |
| Videos | ≥3 | <2 |
| Services list | 89 (standard) + 31 STI | Missing any |
| Reviews | ≥70 (p25), target 97 (median) | <60 |
| Avg ⭐ | ≥4.8 | <4.7 |
| Review velocity | ≥18/mo | <15/mo |
| Reply rate (last 30d) | 100% | any unreplied ≤3-star |
| Top complaint themes | none repeating | "fees", "wait", "no-doctor" repeat → ops issue |
| Bookings from GMB channel (Redshift) | ≥10/wk | <5/wk → conversion issue, not visibility |

If a clinic fails Day-90, it's now lagging the network. Don't let it drift.

---

## Months 4–12 (steady-state)

- [ ] **Monthly review velocity 18–20** (network median 18.6/mo; p75 20.8/mo)
- [ ] **Quarterly photo refresh**: 5–8 new photos every 90 days. Stale profiles lose rank
- [ ] **Quarterly video**: 1 new video each quarter. The top-15 profiles have a median of 4 videos (one per quarter of operation)
- [ ] **Post weekly minimum**, ideally 2/week. Posts older than 7 days are de-prioritized by Google
- [ ] **Audit title once per quarter** — if Google merged the listing with another or someone edited via Maps, it can change. The Tatya Tope Nagar / Saraswathipuram bugs in the prior audit happened this way
- [ ] **Address corrections** — if Google modifies the address (it sometimes does after street-view updates), accept the correction or reject + re-verify

---

## Ongoing hygiene-check cadence

| Day post-launch | Check depth | Owner |
|---|---|---|
| Day 7 | Profile live? Verified? Title correct? | Clinic manager + central GMB owner |
| Day 30 | Full hygiene table above | Central GMB owner |
| Day 60 | Full hygiene table above | Central GMB owner |
| Day 90 | Critical hygiene check (above) + tag clinic as "live network" | Central GMB owner + Ops lead |
| Day 180 | Service list still complete? Title not corrupted? Photo refresh? | Central GMB owner |
| Day 365 | Full audit — compare to network median; identify lag clinics | Central GMB owner |
| Every quarter (perpetual) | Hygiene table + review velocity + complaint theme scan | Central GMB owner |

---

## What NOT to do (lessons from the audit)

1. **Don't stuff more keywords into the title.** The current template is already at the edge of GBP's keyword-stuffing penalty. Adding "best STD clinic, best STI testing, best HIV clinic" gets profiles suspended or down-ranked. Use the standard template verbatim.
2. **Don't customize the service list per clinic.** The 89-service / 31-STI template is what works across the network. Pruning it down "because the clinic doesn't do that yet" hides the clinic from condition-specific search.
3. **Don't treat GBP hygiene as a conversion lever for STI.** The prior 4-round audit established GMB profile completeness is identical between top and bottom STI clinics — what differs is downstream EMR tagging at the clinic. GBP hygiene is the floor (without it you don't show up), not the ceiling (with it you don't automatically convert).
4. **Don't ignore the response rate on bad reviews.** The May 2026 Bengaluru review audit found that 4 of the 12 worst recent ⭐1 reviews were unreplied. Bad reviews left hanging compound — both with the original reviewer and with prospects reading them.
5. **Don't create duplicate / unnamed profiles.** The current network has 3 admin entries with zero photos that drag the brand footprint (Sushant Lok Gurugram, an unnamed Bengaluru listing, "Allo Health — India's largest chain" Mumbai). Either populate them or take them down at launch — don't create the same problem again.
6. **Don't pump fake reviews.** Allo's review velocity benchmark of 18–20/mo is achievable from real patients; faked reviews trigger Google's filtering and the actual review counts disappear retroactively. Network has clinics with 947 reviews built honestly — match that ceiling.

---

## Related docs

- `PLAYBOOK_STI_SPECIFIC.md` — STI-specific overlay on top of this playbook
- `GMB_GAPS_LIST.md` — current gaps in live clinics (use as model of what NOT to be)
- `PATTERN_REPORT.md` — why GMB hygiene is the floor, not the lever, for STI conversion
- `GMB_REVIEW_FINDINGS.md` — what bad review trends actually look like (Bengaluru May 2026)
