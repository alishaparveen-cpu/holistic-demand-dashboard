#!/usr/bin/env python3
# Build enriched competitor dataset (data_competition_v2.json) from local repo sources.
import pandas as pd, numpy as np, json, re
from datetime import timedelta
from collections import defaultdict

import os
BASE=os.path.dirname(os.path.abspath(__file__))+'/'
OUT=BASE+'data_competition_v2.json'
serp=pd.read_csv(BASE+'data_serp_competitors.tsv',sep='\t')
comp=json.load(open(BASE+'data_competition.json'))
ai=json.load(open(BASE+'data_auction_insights.json'))
rev=pd.read_csv(BASE+'all_gmb_reviews_last12mo.csv')

CATS=['SH','STI','MH']
serp['is_maps']=serp.domain.astype(str).str.contains('google.com',na=False)
serp['appearances']=pd.to_numeric(serp.appearances,errors='coerce').fillna(0)
serp['reviews']=pd.to_numeric(serp.reviews,errors='coerce').fillna(0)
serp['rating']=pd.to_numeric(serp.rating,errors='coerce')
serp['avg_pos']=pd.to_numeric(serp.avg_pos,errors='coerce')
serp['ever_sponsored']=serp.ever_sponsored.astype(str).str.lower().eq('true')

# pathy lookup from data_competition (name -> pathy)
pathy={}
for cat in CATS:
    for k,v in comp.get(cat,{}).get('clinics',{}).items():
        for c in v.get('competitors',[]):
            if c.get('name') and c.get('pathy'): pathy[c['name']]=c['pathy']
def guess_pathy(name):
    n=str(name).lower()
    if any(w in n for w in['unani','hakim','sattar']):return 'Unani'
    if 'ayurved' in n or 'ayur' in n:return 'Ayurvedic'
    if 'homeo' in n:return 'Homeopathic'
    return pathy.get(name,'')

# ---- our review velocity/recency per city (from dated reviews) ----
rev['review_date']=pd.to_datetime(rev.review_date,errors='coerce')
rev=rev.dropna(subset=['review_date'])
rev['star_rating']=pd.to_numeric(rev.star_rating,errors='coerce')
CITYMAP={'Bengaluru':'Bangalore','Hubballi':'Hubli','Vijayawada':'Vijayawada'}
rev['city']=rev['city'].replace(CITYMAP)
maxd=rev.review_date.max()
vel={}
for city,g in rev.groupby('city'):
    last90=g[g.review_date> maxd-timedelta(days=90)]
    prior90=g[(g.review_date<=maxd-timedelta(days=90))&(g.review_date>maxd-timedelta(days=180))]
    vel[city]=dict(
        per_mo=round(len(last90)/3,1),
        prev_per_mo=round(len(prior90)/3,1),
        days_since_last=int((maxd-g.review_date.max()).days),
        recent_rating=round(float(last90.star_rating.mean()),2) if len(last90) else None,
        n12mo=int(len(g)))

# ---- auction (paid) rivals per city/cat ----
def paid_rivals(city,cat):
    d=ai.get('byCity',{}).get(city,{}).get(cat)
    if not d: return []
    out=[]
    for c in d.get('competitors',[])[:6]:
        out.append(dict(domain=c.get('domain'),is_=c.get('is'),posAbove=c.get('posAbove'),absTop=c.get('absTop')))
    return dict(you=d.get('you'), youAbsTop=d.get('youRow',{}).get('absTop'), competitors=out)

SOCIAL=('facebook.com','threads.com','instagram.com','youtube.com','twitter.com','linkedin.com','justdial.com','sulekha')
def is_noise(dom):
    d=str(dom).lower()
    return any(s in d for s in SOCIAL)

out={'_meta':{'built':str(maxd.date()),'cats':CATS,
     'note':'Rivals ranked by real SERP appearances (who actually shows against us), split by surface: GMB/Maps, Organic-web, Paid. Reviews shown with rating; our review velocity from dated GMB reviews.'}}

for cat in CATS:
    sc=serp[serp.cat==cat]
    cities={}
    # funnel/conversion levers + our reviews/rating from data_competition
    cf=comp.get(cat,{}).get('cities',{})
    for city in sorted(sc.city.unique()):
        cd=sc[sc.city==city]
        # our stats
        our_rev=int(cd.our_reviews.dropna().max()) if cd.our_reviews.notna().any() else None
        our_rat=round(float(cd.our_rating.dropna().max()),2) if cd.our_rating.notna().any() else None
        # maps rivals (appearance-ranked)
        def agg(df,key):
            g=df.groupby(key).agg(ap=('appearances','sum'),rev=('reviews','max'),rat=('rating','max'),
                                  pos=('avg_pos','mean'),spons=('ever_sponsored','max')).reset_index()
            g=g[g.ap>0].sort_values('ap',ascending=False)
            return g
        maps=agg(cd[cd.is_maps],'comp_name').head(6)
        web=agg(cd[(~cd.is_maps)&(~cd.domain.map(is_noise))],'domain').head(6)
        def rows(g,namecol):
            r=[]
            for _,x in g.iterrows():
                d=dict(name=x[namecol],ap=int(x.ap),reviews=int(x.rev) if x.rev==x.rev else None,
                       rating=round(float(x.rat),1) if x.rat==x.rat else None,
                       pos=round(float(x.pos),1) if x.pos==x.pos else None,
                       sponsored=bool(x.spons))
                if namecol=='comp_name': d['pathy']=guess_pathy(x[namecol])
                r.append(d)
            return r
        funnel=cf.get(city,{}).get('funnel',{})
        cities[city]=dict(
            our=dict(reviews=our_rev,rating=our_rat,**({k:vel[city][k] for k in vel[city]} if city in vel else {})),
            funnel={k:funnel.get(k) for k in['IS','locpct','loc2ld','ld2bk','bk2dn','cpl','leads','spend','locclicks','clicks']} if funnel else {},
            maps=rows(maps,'comp_name'),
            web=rows(web,'domain'),
            paid=paid_rivals(city,cat),
        )
        # verdict vs top appearing MAPS rival (fallback web)
        top=cities[city]['maps'][0] if cities[city]['maps'] else (cities[city]['web'][0] if cities[city]['web'] else None)
        if top and our_rev is not None and top.get('reviews'):
            ratio=our_rev/max(top['reviews'],1)
            v='WINNING' if ratio>=1 else ('DEFEND' if ratio>=0.5 else 'BUILD REVIEWS')
        else: v='—'
        cities[city]['verdict']=v
    out[cat]={'cities':cities}

json.dump(out,open(OUT,'w'),separators=(',',':'))
# verify
import os
print('written',os.path.getsize(OUT),'bytes')
for city in ['Bangalore','Mumbai','Pune']:
    d=out['SH']['cities'].get(city,{})
    print('\n###',city,'SH  our',d['our'].get('reviews'),'rev @',d['our'].get('rating'),' vel',d['our'].get('per_mo'),'/mo (prev',d['our'].get('prev_per_mo'),')  verdict',d.get('verdict'))
    print('  MAPS:',[(r['name'][:24],r['ap'],r['reviews'],r['rating'],'AD' if r['sponsored'] else '') for r in d['maps'][:3]])
    print('  WEB :',[(r['name'][:26],r['ap'],r['reviews']) for r in d['web'][:3]])
    pd_=d.get('paid') or {}
    print('  PAID:',[(c['domain'][:20],c['is_']) for c in (pd_.get('competitors',[]) if isinstance(pd_,dict) else [])][:3])
    print('  levers:',d.get('funnel'))
