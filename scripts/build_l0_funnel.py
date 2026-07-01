#!/usr/bin/env python3
"""L0 book2done funnel (NEW page) from production.public.bookings_data_raw.
NEW SC = phone_rank=1, dated by apt_create_dt week. Offline clinics only.
Per clinic x week x channel(L0-native) x done-category:
  booked (new SC)
  done_first  = this booking's apt_status_final='COMPLETED'  (matches colleague's book2done)
  done_ever   = the patient EVER completed an SC             (credits reschedule/rebook — true conversion)
  purchased   = patient ever had a paid consult
  rev         = patient's paid consult revenue (payable_amount)
Category (diag_cat, done only): STI / SH / Other  (no MH offline). Bookings carry NO category.
Writes data_l0_funnel.json. Run: AWS_PROFILE=redshift-data python3 scripts/build_l0_funnel.py
"""
import os, sys, json, subprocess, datetime
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RQ = os.path.join(ROOT, "scripts", "redshift_query.py")
def run_sql(sql):
    p = subprocess.run([sys.executable, RQ], input=sql, capture_output=True, text=True)
    if p.returncode != 0 or "ERROR" in (p.stderr or ""):
        sys.stderr.write("query failed: " + (p.stderr or "")[:800] + "\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

# ---- 52 IST-Monday weeks ending at the last complete week (matches the other funnels' window) ----
LO_DATE = datetime.date(2025, 6, 30)            # Monday
WEEKS = [(LO_DATE + datetime.timedelta(weeks=i)).isoformat() for i in range(52)]
idx = {w: i for i, w in enumerate(WEEKS)}; NW = len(WEEKS); LO = WEEKS[0]; HI = "2026-06-29"
def Z(): return [0]*NW
MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
def wlabel(ws):
    y,m,d = map(int, ws.split('-')); s = datetime.date(y,m,d); e = s + datetime.timedelta(days=6)
    return '%d %s–%d %s'%(s.day, MON[s.month-1], e.day, MON[e.month-1])

CHANNEL_CASE = """CASE
  WHEN b.source='Organic' AND b.organic_l2='Google Listing' THEN 'GMB'
  WHEN b.source='Organic' AND b.organic_l2='PC-Inbound' THEN 'Call-in (PCC)'
  WHEN b.source='Organic' AND b.organic_l2='Walk In' THEN 'Walk-in'
  WHEN b.source='Organic' AND b.organic_l2='WA-Inbound' THEN 'WhatsApp'
  WHEN b.source='Organic' AND b.organic_l2 IN ('Clinic Page','Doctor Pages','Sexologist','Treatment Page','Login Page','Healthfeed','Webbot','Homepage','Blog','STD Testing') THEN 'Website'
  WHEN b.source='Organic' THEN 'Organic (untagged)'
  WHEN b.source='Google' THEN 'Google Ads'
  WHEN b.source IN ('Fb','Instagram') THEN 'Meta'
  WHEN b.source='Justdial' THEN 'JustDial'
  WHEN b.source LIKE 'Practo%' THEN 'Practo'
  WHEN b.source IS NULL THEN 'Untracked'
  ELSE 'Other' END"""
CHANNELS = ['GMB','Google Ads','Meta','Call-in (PCC)','Walk-in','Website','WhatsApp','Practo','JustDial','Organic (untagged)','Other','Untracked']
CATS = ['STI','SH','Other']

SQL = """WITH win AS (
  SELECT phone_no, appointment_id, consultation_id, apt_create_dt, apt_status_final, diag_cat,
         source, organic_l2, phone_rank, locality, city, payable_amount
  FROM production.public.bookings_data_raw
  WHERE offline_location_flag=1 AND date(apt_create_dt) >= '{lo}' AND date(apt_create_dt) < '{hi}'),
 pat AS (   -- per phone: ever completed, the completed diag_cat, revenue, purchased
  SELECT phone_no,
    MAX(CASE WHEN apt_status_final='COMPLETED' THEN 1 ELSE 0 END) ever_done,
    MAX(CASE WHEN apt_status_final='COMPLETED' THEN diag_cat END) done_cat,
    COALESCE(SUM(DISTINCT CASE WHEN apt_status_final='COMPLETED' THEN payable_amount END),0)/100.0 rev,
    MAX(CASE WHEN apt_status_final='COMPLETED' AND payable_amount>0 THEN 1 ELSE 0 END) purchased
  FROM win GROUP BY 1)
SELECT b.city, b.locality,
  TO_CHAR(DATE_TRUNC('week', b.apt_create_dt::date),'YYYY-MM-DD') wk,
  {chan} channel,
  CASE WHEN p.done_cat='STI' THEN 'STI'
       WHEN p.done_cat IN ('ED+','PE+','ED+PE+','NSSD') THEN 'SH'
       ELSE 'Other' END dcat,
  COUNT(*) booked,
  SUM(CASE WHEN b.apt_status_final='COMPLETED' THEN 1 ELSE 0 END) done_first,
  SUM(COALESCE(p.ever_done,0)) done_ever,
  SUM(COALESCE(p.purchased,0)) purchased,
  SUM(COALESCE(p.rev,0)) rev
FROM win b JOIN pat p ON p.phone_no=b.phone_no
WHERE b.phone_rank=1
GROUP BY 1,2,3,4,5;""".format(lo=LO, hi=HI, chan=CHANNEL_CASE)

def slugify(loc, city):
    s = lambda x: "".join(ch if ch.isalnum() else "_" for ch in (x or "").strip().lower())
    return s(loc) + "_" + s(city)

MEAS = ['booked','done_first','done_ever','purchased','rev']
clinics = {}
def blank():
    return {'tot': {m: Z() for m in MEAS},
            'chan': defaultdict(lambda: {m: Z() for m in MEAS}),
            'chan_cat': defaultdict(lambda: defaultdict(lambda: {m: Z() for m in MEAS})),
            'city': ''}
for r in run_sql(SQL):
    if len(r) < 10: continue
    city, loc, wk, chan, dcat, bk, df, de, pu, rv = r[:10]
    if wk not in idx or not loc: continue
    i = idx[wk]
    try: bk=int(float(bk)); df=int(float(df)); de=int(float(de)); pu=int(float(pu)); rv=int(round(float(rv)))
    except ValueError: continue
    if chan not in CHANNELS: chan = 'Other'
    if dcat not in CATS: dcat = 'Other'
    slug = slugify(loc, city)
    c = clinics.setdefault(slug, blank()); c['city'] = city; c['_loc'] = loc
    vals = {'booked':bk,'done_first':df,'done_ever':de,'purchased':pu,'rev':rv}
    for m in MEAS:
        c['tot'][m][i]+=vals[m]; c['chan'][chan][m][i]+=vals[m]; c['chan_cat'][chan][dcat][m][i]+=vals[m]

# sparsify + finalize
out_clin = {}
for slug, c in clinics.items():
    chan = {ch: {m: v for m, v in d.items()} for ch, d in c['chan'].items() if any(any(a) for a in d.values())}
    ccat = {}
    for ch, cats in c['chan_cat'].items():
        cc = {ct: {m: v for m, v in d.items()} for ct, d in cats.items() if any(any(a) for a in d.values())}
        if cc: ccat[ch] = cc
    disp = (c.get('_loc') or slug.rsplit('_',1)[0].replace('_',' ').title()) + ' · ' + c['city']
    out_clin[slug] = {'disp': disp, 'city': c['city'], 'tot': c['tot'], 'chan': chan, 'chan_cat': ccat}

out = {'_meta': {'weeks': WEEKS, 'week_labels': {w: wlabel(w) for w in WEEKS}, 'channels': CHANNELS, 'cats': CATS,
                 'note': 'L0 book2done · new SC (phone_rank=1) · done_first=first-booking COMPLETED · done_ever=patient ever completed · offline · from bookings_data_raw'},
       'clinics': out_clin}
json.dump(out, open(os.path.join(ROOT, "data_l0_funnel.json"), "w"), separators=(",", ":"))

tb = sum(sum(c['tot']['booked']) for c in out_clin.values())
tdf = sum(sum(c['tot']['done_first']) for c in out_clin.values())
tde = sum(sum(c['tot']['done_ever']) for c in out_clin.values())
print("clinics:%d  booked:%d  done_first:%d (%.0f%%)  done_ever:%d (%.0f%%)" %
      (len(out_clin), tb, tdf, 100*tdf/tb if tb else 0, tde, 100*tde/tb if tb else 0))
