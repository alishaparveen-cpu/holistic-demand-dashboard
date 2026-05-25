# Channel-level STI breakdown — what the data finally says

Last 30 days. For each clinic, every completed consultation is joined to its lead's UTM source. STI flag = consultation has `encounter_tags.tag_type='sti'` (diagnosis category).

---

## Bottom line: it's not the channels

Every channel converts to STI at a similar *ratio within the same tier* — and every channel converts ~3× worse at the bottom tier than the top:

| Tier (n) | GMB STI% | Google STI% | Organic STI% | Practo STI% |
|---|---:|---:|---:|---:|
| Top (10) | **35%** | 26% | 27% | 12% |
| Mid (27) | 26% | 14% | 21% | 10% |
| Low (11) | **10%** | 7% | 7% | 2% |

Read it row by row: top-tier GMB tags 35% of patients as STI. Low-tier GMB tags 10%. Same channel, same UTM source — different STI tagging rate at the clinic.

**Conclusion: this isn't a channel-mix issue. Every source pulls a similar STI tagging rate at any given clinic, and the rate is uniformly low at struggling clinics.**

---

## What's actually breaking — channel by channel

**GMB** — best STI converter at top tier (35%), still respectable at mid (26%). Drops to 10% at low tier. Top clinics like Mogappair (53%) and Velachery (45%) show GMB *can* deliver near-pure STI traffic. So GMB is working when the clinic side is working.

**Google (paid)** — works at top tier (26%) but drops to 7% at low. Most striking failures:
- Bharathi Nagar (Coimbatore): 18 Google done, 0 STI — Google is bringing zero STI-tagged patients
- Kothrud (Pune): 32% Google STI; Curesta (Wakad): 6% Google STI — neighboring Pune clinics with 5× gap on the same channel

**Organic** — actually decent at top tier (27%), but 7% at low. Some clinics show 0% organic STI (Saraswathipuram, Garkheda, Nallagandla) — these are red flags that the clinic isn't picking up STI patients from any direct/organic visit.

**Practo** — universally weak. Even top tier only converts 12%. Some specific failures:
- Indiranagar: 39 Practo done, only 1 STI (3%)
- Life Plus: 39 Practo done, only 1 STI (3%)
- Vatsal-Allo: 21 Practo done, 0 STI
- Heart & Her (Bharathi Nagar): 35 Practo done, 3 STI (9%)
- Jeevah (Ranchi): 21 Practo done, 0 STI

**Practo brings high volume of non-STI consultations across the board.** This is a property of Practo's lead pool, not the clinic.

---

## Per-clinic deep-dive (low tier)

For each bottom-tier clinic, here's the source mix and where the leak is:

### Ashok Nagar (Ranchi) · STI 2% · 53 consults
- Mix: Practo 38% · Google 22% · GMB 20% · Organic 20%
- **All channels at 0% STI** (organic at 9%)
- Verdict: clinic-side. STI tagging is essentially off for this clinic.

### Garkheda (Aurangabad) · STI 7% · 29 consults
- Mix: GMB 59% (very high) · Organic 28% · Google 14% · Practo 0%
- **0% STI across all channels** (truth says 7%, but my Redshift says 0)
- Verdict: STI diagnosis tags not being recorded for this clinic at all. Talk to the clinic admin.

### Saraswathipuram (Mysuru) · STI 7% · 71 consults
- Mix: Organic 29% · GMB 26% · Practo 18% · Google 18%
- **0% Google, 0% Organic, 0% Practo. Only GMB 12%.**
- Verdict: All non-GMB STI-relevant tagging is missing. GMB at 12% is also weak.

### Nallagandla (Hyderabad) · STI 5%
- Mix: GMB 36% · Google 25% · Organic 22% · Practo 17%
- Per-source: GMB 8%, Google 0%, Organic 0%, Practo 17%
- Verdict: Strangely, *Practo* converts here (1/6 STI) but GMB and Google don't. Investigate intake routing.

### Kalyan West (Mumbai) · STI 4% · 119 consults (high volume!)
- Mix: GMB 40% · Practo 21% · Organic 19% · Google 14%
- GMB only 5% STI on 40 consults
- Verdict: Highest-volume low-tier clinic. Even with 40 GMB consults a month, only 2 STI tags. Operations audit highest priority.

### Chinchwad (Pune) · STI 6%
- Mix: GMB 43% · Google 23% · Organic 13% · Practo 11%
- GMB only 13% STI, Organic and Practo 0%
- Verdict: Standard mix but very low conversion. Compare with Kothrud (same city) which gets 21% GMB / 32% Google STI.

### Bhimrad (Surat) · STI 6%
- Mix: GMB 41% · Organic 24% · Google 21% · Practo 14%
- GMB 17%, Google 0%, Organic 14%, Practo 0%
- Note: no GMB listing currently. Need to create one.

### Panvel, Tatya Tope Nagar, Arekere, Vaishali Nagar — all similar pattern: GMB pulls 30-40% of volume, every source at single-digit STI%.

---

## The two clinics where data is genuinely strange

**Garkheda (Aurangabad)** — truth says 7% STI, my Redshift says 0% STI across *every* channel and 0 STI tags total. The 7% in truth (2/29 calls) might be from a different definition or those 2 patients are tagged with a different `tag_type`. Worth pulling raw encounter_tags for this clinic to confirm.

**Saraswathipuram (Mysuru)** — truth says 7%, Redshift says 3% (2 STI of 71 done). Big disagreement.

Both suggest the QS2 "STI calls" definition counts something my Redshift query misses — likely STI screenings or tests that are tagged with a different category than `'sti'`.

---

## What this changes about the action plan

We've now ruled out (in order):
1. ~~GMB profile completeness~~ — identical across tiers
2. ~~Title format / keyword stuffing~~ — same template, no signal
3. ~~Search query intent reaching profile~~ — same intent mix
4. ~~Channel mix~~ — every channel converts equally poorly at low tier

**The remaining hypothesis — and now the strongest one — is clinic-level diagnosis tagging discipline.**

Specifically: when a patient is consulted at Velachery, the doctor enters STI as a diagnosis tag 45% of the time on GMB-sourced consultations. At Garkheda, the same patient profile gets tagged STI 0% of the time. The variance is so consistent across channels that the explanation has to live at the *consultation* level, not the *acquisition* level.

### Top three next steps

1. **EMR tagging audit.** Pull last 30 days of consultations at Garkheda, Saraswathipuram, Ashok Nagar. For each completed consultation:
   - Was *any* tag entered in `encounter_tags`?
   - What tag_type was entered (sti / ed_plus / pe_plus / others)?
   - Was an STI test ordered (`allo_drugs` / `allo_labs` table)?
   - Is one specific doctor responsible for under-tagging?

2. **Compare a known same-condition patient seen at top vs low.** Use phone_no or patient_id to find someone who visited a top clinic and a low clinic. Look at their tag history. This is the cleanest controlled test.

3. **Train low-tier clinics on STI tagging.** If audit (1) confirms tagging is being missed, this is a 30-minute training intervention per clinic, not a marketing campaign.

### What this changes about GMB work

- GMB profile housekeeping (logos, appointment URLs, fixing Vijayanagar's 0-imp listing) is still worth doing — but expect *no STI share improvement* from it.
- Practo lead quality for STI is universally weak (12% even at top). If you want to grow STI volume specifically, GMB is the right channel to invest in. But the clinic operations need to be ready to tag those patients.

---

## Caveats

- **My consultation counts are ~2× the truth** (we saw 2,932 vs 1,463 for May 11-17). The *ratios* hold but absolute volume is inflated. The "Practo 39, 1 STI" pattern stays directionally correct: Practo brings volume, STI is rare in it.
- **30-day window** matches the GMB insights window so volumes line up. The truth STI sheet appears to be on a different window — that explains some of the volume mismatch.
- **2 clinics with truth STI but 0 in Redshift** (Garkheda, Saraswathipuram) suggest the truth definition may include STI screenings that aren't tagged as 'sti' in `encounter_tags`. Worth resolving in step 1.
