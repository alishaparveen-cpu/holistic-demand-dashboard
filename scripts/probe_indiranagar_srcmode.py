#!/usr/bin/env python3
"""ONE-SHOT probe: Indiranagar (Bengaluru) SC bookings → by SOURCE → by VIA-MODE (call/web/whatsapp/walk-in).
Runs profile + level-1 + level-2 in a single invocation so it beats the short SSO token.

MODEL (matches build_coimbatore_funnel.py):
  source of a CALL   = which Exotel tracking number the patient dialed (exophone map below)
  source of WEB / WA = the patient's lead utm_source; mode from origin / user_flow / source_url
  A booking's MODE   = Call if the patient's phone hit one of our inbound lead_to_call numbers;
                       else WhatsApp (origin~whatsapp), else Web (user_flow / clinic-url), else Walk-in.

Run: AWS_PROFILE=redshift-data python3 scripts/probe_indiranagar_srcmode.py
"""
import os, sys, subprocess
from collections import defaultdict, Counter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def q(sql):
    p = subprocess.run(['python3', os.path.join(ROOT, 'scripts', 'redshift_query.py')],
                       input=sql, capture_output=True, text=True)
    if 'UnauthorizedSSOToken' in p.stderr or 'expired' in p.stderr:
        sys.exit("SSO token expired — run:  aws sso login --profile redshift-data")
    if p.returncode != 0 or 'FAIL' in p.stderr:
        sys.stderr.write("query failed: " + (p.stderr or '')[:300] + "\n"); sys.exit(1)
    return [l.split('\t') for l in p.stdout.splitlines() if l.strip()]

# exophone → source (from exophone_categorisation.xlsx). GMB 8047160881 = Indiranagar's own; rest shared.
EXO = {'8047160881':'GMB','8071175797':'GMB','8046801373':'GMB','4045901977':'GMB',
       '8045680561':'Google','8071176846':'Practo',
       '8046810621':'Meta','8046801869':'Meta','8047095288':'Meta',
       '8046800927':'Organic','8045684567':'Organic','8047095391':'Organic','7314621004':'Organic',
       '8046810589':'Organic','8045687158':'Organic','8045680040':'Organic',
       '8046809944':'Others','7949107957':'Meta'}   # JustDial→Others, IG→Meta
NUMS = "','".join(EXO.keys())
WK = "TO_CHAR(DATE_TRUNC('week', a.start_time + INTERVAL '5.5 hours'),'YYYY-MM-DD')"

def main():
    # 0) SC-offline bookings at Indiranagar, last 8 wks → distinct (patient, week)
    bk = q(f"""SELECT DISTINCT a.patient_id, p.phone_no,
        {WK} AS wk
      FROM allo_consultations.appointments a
      JOIN allo_consultations.types t ON a.type_id=t.id AND t.name='Screening Call'
      JOIN allo_health.locations loc ON a.location_id=loc.id AND loc.deleted_at IS NULL
      JOIN allo_persons.patient p ON p.id=a.patient_id
      WHERE a.deleted_at IS NULL AND p.deleted_at IS NULL
        AND LOWER(loc.locality)='indiranagar' AND LOWER(loc.city) IN ('bengaluru','bangalore')
        AND a.start_time >= DATEADD(week,-8,CURRENT_DATE)""")
    pat_phones = {(r[0], r[2]): (r[1] or '')[-10:] for r in bk if len(r) >= 3}
    booked_phones = set(v for v in pat_phones.values() if v)
    print(f"SC bookings at Indiranagar (last 8 wks): {len(pat_phones)} patient-weeks, {len(booked_phones)} distinct phones\n")
    if not booked_phones: return
    ph_in = "','".join(booked_phones)

    # 1) CALLS: which tracked number did each booked phone dial (inbound lead_to_call) → source
    calls = q(f"""SELECT RIGHT("from",10) AS ph, RIGHT(exotel_number,10) AS num, COUNT(*) c
      FROM allo_vendors.exotel_calls
      WHERE direction='inbound' AND routed_to='lead_to_call' AND deleted_at IS NULL
        AND RIGHT(exotel_number,10) IN ('{NUMS}')
        AND RIGHT("from",10) IN ('{ph_in}')
        AND start_time >= DATEADD(week,-14,CURRENT_DATE)
      GROUP BY 1,2""")
    call_src = {}   # phone -> source (by most-dialed tracked number)
    tally = defaultdict(Counter)
    for r in calls:
        if len(r) < 3: continue
        tally[r[0]][r[1]] += int(r[2])
    for ph, c in tally.items():
        call_src[ph] = EXO.get(c.most_common(1)[0][0], 'Others')

    # 2) LEADS: origin / utm_source / user_flow / source_url for the booked phones (for web/WA + profile)
    leads = q(f"""SELECT RIGHT(phone_no,10) ph, LOWER(COALESCE(utm_source,'')) us,
        LOWER(COALESCE(origin,'')) orig, CASE WHEN user_flow IS NOT NULL THEN 1 ELSE 0 END uf,
        LOWER(COALESCE(source_url,'')) surl,
        ROW_NUMBER() OVER (PARTITION BY RIGHT(phone_no,10) ORDER BY created_at ASC) lr
      FROM allo_persons.lead
      WHERE phone_no IS NOT NULL AND LEN(phone_no)>=10 AND RIGHT(phone_no,10) IN ('{ph_in}')""")
    lead = {r[0]: r for r in leads if len(r) >= 6 and r[5] == '1'}

    def src_bucket(us):
        if us in ('gmb','googlelisting','google listing'): return 'GMB'
        if us == 'google': return 'Google'
        if us == 'practo': return 'Practo'
        if us in ('fb','facebook','meta','ig','instagram'): return 'Meta'
        if 'organic' in us: return 'Organic'
        if us == '': return 'Direct / none'
        return 'Others'

    # ---- PROFILE (verify WA / web signals) ----
    print("=== PROFILE · lead origin values for booked patients (top 15) ===")
    oc = Counter(lead[p][2] for p in booked_phones if p in lead)
    for o, n in oc.most_common(15): print(f"  {n:4}  {o[:70]}")
    print()

    # ---- ATTRIBUTE each booking-patient-week → source × mode ----
    grid = Counter()
    for (patid, wk), ph in pat_phones.items():
        if ph in call_src:
            src, mode = call_src[ph], '1·Call'
        elif ph in lead:
            _, us, orig, uf, surl, _ = lead[ph]
            src = src_bucket(us)
            if 'whatsapp' in orig:                                   mode = '3·WhatsApp'
            elif uf == '1' or 'http' in orig or 'allohealth' in orig or 'http' in surl: mode = '2·Web'
            elif orig == '' and us == '':                            mode = '5·Walk-in / no-lead'
            else:                                                    mode = '4·Other-web'
        else:
            src, mode = 'Direct / none', '5·Walk-in / no-lead'
        grid[(src, mode)] += 1

    # ---- OUTPUT: source × mode ----
    print("=== INDIRANAGAR · SC bookings by SOURCE × VIA-MODE (last 8 wks) ===")
    srcs = sorted({s for s, m in grid}, key=lambda s: -sum(v for (ss, mm), v in grid.items() if ss == s))
    modes = sorted({m for s, m in grid})
    hdr = f"{'source':16} | " + " | ".join(f"{m[2:]:>10}" for m in modes) + " |  TOTAL"
    print(hdr); print('-'*len(hdr))
    for s in srcs:
        cells = [grid.get((s, m), 0) for m in modes]
        print(f"{s:16} | " + " | ".join(f"{c:>10}" for c in cells) + f" |  {sum(cells):>5}")
    tot = [sum(grid.get((s, m), 0) for s in srcs) for m in modes]
    print('-'*len(hdr)); print(f"{'TOTAL':16} | " + " | ".join(f"{c:>10}" for c in tot) + f" |  {sum(tot):>5}")

if __name__ == "__main__":
    main()
