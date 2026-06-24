#!/usr/bin/env python3
"""Build the Pune deep-dive HTML report (Chinchwad / Kharadi / Baner), Hyderabad-style.
Reads the /tmp pulls + data_reviews.json + the Practo CSV. Self-contained HTML out."""
import csv, json, datetime, os
from collections import defaultdict

WK=["2026-04-13","2026-04-20","2026-04-27","2026-05-04","2026-05-11","2026-05-18","2026-05-25","2026-06-01","2026-06-08","2026-06-15"]
MO=["2026-01","2026-02","2026-03","2026-04","2026-05","2026-06"]
CLIN=["Chinchwad","Kharadi","Baner"]
PRACTO_NAME={"Chinchwad":"Pimpri-Chinchwad","Kharadi":"Kharadi","Baner":"Baner"}

def tsv(f):
    try: return [r for r in csv.reader(open(f),delimiter="\t") if r]
    except FileNotFoundError: return []

# weekly book/done
wb=defaultdict(lambda:defaultdict(int)); wd=defaultdict(lambda:defaultdict(int))
for r in tsv("/tmp/p2.tsv"):
    if len(r)==4: wb[r[0]][r[1]]=int(r[2]); wd[r[0]][r[1]]=int(r[3])
# monthly
mb=defaultdict(lambda:defaultdict(int)); md=defaultdict(lambda:defaultdict(int))
for r in tsv("/tmp/mo.tsv"):
    if len(r)==4: mb[r[0]][r[1]]=int(r[2]); md[r[0]][r[1]]=int(r[3])
# leads by channel
lc=defaultdict(lambda:defaultdict(lambda:defaultdict(int)))
for r in tsv("/tmp/pl.tsv"):
    if len(r)==4: lc[r[0]][r[1]][r[2]]=int(r[3])
# availability
avwd=defaultdict(lambda:defaultdict(int)); avwe=defaultdict(lambda:defaultdict(int))
for r in tsv("/tmp/av.tsv"):
    if len(r)==4: avwd[r[0]][r[1]]=int(r[2]); avwe[r[0]][r[1]]=int(r[3])
# doctor b2d
doc=defaultdict(lambda:defaultdict(lambda:defaultdict(int)))
for r in tsv("/tmp/docb.tsv"):
    if len(r)==5: doc[r[0]][r[1]][r[2]]=(int(r[3]),int(r[4]))
# practo from CSV
practo=defaultdict(lambda:defaultdict(int))
for row in csv.DictReader(open("/Users/alishaparveen/Downloads/Flow Dashboard view - Sheet37 (5).csv")):
    try: d=datetime.datetime.strptime(row["dt"],"%d-%m-%Y").date()
    except: continue
    if row["type"] in ("Book","Call"):
        wk=str(datetime.date.fromisocalendar(*d.isocalendar()[:2],1)); practo[row["location"]][wk]+=1
# reviews
rev=json.load(open("data_reviews.json")); rwk=rev["_meta"]["weeks"]  # newest-first

def spark(vals,color="#1F6F5C",w=180,h=34):
    v=[x if x is not None else 0 for x in vals]; n=len(v); mx=max(1,max(v))
    pad=3; X=lambda i:pad+i*(w-2*pad)/(n-1); Y=lambda val:h-pad-(val/mx)*(h-2*pad)
    p="".join(("M" if i==0 else "L")+f"{X(i):.1f},{Y(val):.1f} " for i,val in enumerate(v))
    dots=f'<circle cx="{X(n-1):.1f}" cy="{Y(v[-1]):.1f}" r="2.8" fill="{color}"/>'
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><path d="{p}" fill="none" stroke="{color}" stroke-width="1.8"/>{dots}</svg>'

def pct(a,b): return f"{a/b*100:.0f}%" if b else "—"
def row_cells(vals,fmt=lambda x:str(x)): return "".join(f"<td>{fmt(v) if v not in (0,None) else ('0' if v==0 else '—')}</td>" for v in vals)

H=[]
def w(s): H.append(s)

# ---- per-clinic config (verdict) ----
VERDICT={
 "Chinchwad":("DEMAND DIP · recovering","bad","Lead-driven (GMB calls + Google paid), not the doctor. Availability was full at the trough."),
 "Kharadi":("HEALTHY · rostering only","good","Clinic growing on organic. Dr. Shaunak's fall = 2nd doctor (Dr. Mane) onboarded Jun 15 — load-share, not demand."),
 "Baner":("OPS · completion","warn","Demand stable (Practo growing 3→12). Real issue: book→done fell 92%→53% — show-up/ops."),
}
CH_ORDER=["GMB call","Google","GMB web","Organic/other","Meta","Other"]
CH_LABEL={"GMB call":"GMB call","Google":"Google paid","GMB web":"GMB web","Organic/other":"Organic web","Meta":"Meta","Other":"Other (offline/ref)"}

w('''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pune Deep Dive — Chinchwad · Kharadi · Baner</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#F6F4EE;--sheet:#fff;--inset:#F4F2EB;--ink:#1A2B26;--ink2:#52605A;--muted:#8A8A80;--line:#E5E2D9;--line2:#EEEBE2;--accent:#1F6F5C;--good:#1F6F5C;--goodbg:#EDF4F0;--bad:#B23A2E;--badbg:#FBEEEC;--warn:#B8862E;--warnbg:#FBF4E6}
*{box-sizing:border-box}body{font-family:Inter,sans-serif;background:var(--bg);color:var(--ink);margin:0;font-size:13px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:22px 24px 90px}
h1{font-family:Fraunces,serif;font-size:32px;font-weight:600;margin:6px 0 2px}
h2{font-family:Fraunces,serif;font-size:22px;font-weight:600;margin:30px 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.tldr{background:var(--sheet);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}
.tldr b{color:var(--ink)}
.clinic{background:var(--sheet);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:18px 0}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:4px 10px;border-radius:999px;vertical-align:middle;margin-left:10px}
.badge.bad{background:var(--badbg);color:var(--bad)}.badge.good{background:var(--goodbg);color:var(--good)}.badge.warn{background:var(--warnbg);color:var(--warn)}
.ch{font-family:Fraunces,serif;font-size:20px;font-weight:600;margin:0 0 2px;display:inline-block}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:12.5px}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--line2);font-family:'JetBrains Mono';font-variant-numeric:tabular-nums;white-space:nowrap}
th:first-child,td:first-child{text-align:left;font-family:Inter}
th{font-size:9.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:600;background:var(--inset)}
td.lbl{font-weight:500;color:var(--ink)}
tr.hi td{background:var(--badbg)}
.cap{font-family:'JetBrains Mono';font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;margin:14px 0 2px}
.what{background:var(--inset);border-radius:9px;padding:11px 14px;margin-top:10px;font-size:12.5px}
.what b{color:var(--ink)}
.act{background:#FBF9F3;border:1px dashed var(--line);border-radius:9px;padding:10px 14px;margin-top:8px;font-size:12.5px}
.kpis{display:flex;gap:18px;flex-wrap:wrap;margin:8px 0}
.kpi{background:var(--inset);border-radius:9px;padding:8px 13px;min-width:120px}
.kpi .k{font-size:9.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.kpi .v{font-family:Fraunces,serif;font-size:21px;font-weight:600}
.up{color:var(--good)}.down{color:var(--bad)}
</style></head><body><div class="wrap">''')
w('<h1>Pune Deep Dive</h1>')
w('<div class="sub">Chinchwad · Kharadi · Baner — Jan–Jun 2026 · complete diagnosis (bookings · leads incl. Practo · doctors · B2D · availability · reviews). Bookings = unique-patient Screening Calls, reschedules excluded.</div>')

# TLDR
w('<div class="tldr"><b>The headline:</b> only <b>one</b> of the three had a real demand drop. ')
w('<b>Chinchwad</b> dipped late-May→Jun 8 on the <b>call channels</b> (GMB calls 17→8, Google paid →0) with availability full — demand, now recovering. ')
w('<b>Kharadi</b> is healthy and growing on organic; Dr. Shaunak\'s "drop" is just a <b>2nd doctor (Dr. Mane) onboarded Jun 15</b> splitting a flat 40. ')
w('<b>Baner</b>\'s demand is stable (Practo ramping 3→12), but <b>book→done collapsed 92%→53%</b> — an ops/show-up problem, not demand.</div>')

# Level 1 overview — monthly trajectory
w('<h2>Level 1 · Pune overview — monthly trajectory</h2>')
w('<div class="sub">Jun is a partial month (~3 weeks).</div>')
w('<table><tr><th>Clinic</th>'+''.join(f'<th>{m[5:]}</th>' for m in MO)+'<th>trend (bk)</th></tr>')
for c in CLIN:
    bvals=[mb[c].get(m,0) for m in MO]
    w(f'<tr><td class="lbl">{c} · booked</td>'+row_cells(bvals)+f'<td>{spark(bvals[:-1],"#3E6F8E")}</td></tr>')
    dvals=[md[c].get(m,0) for m in MO]
    w(f'<tr style="color:var(--ink2)"><td>&nbsp;&nbsp;↳ done</td>'+row_cells(dvals)+f'<td>{spark(dvals[:-1],"#B8862E")}</td></tr>')
w('</table>')
w('<div class="what"><b>Read:</b> Chinchwad built steadily (64→114 by May, May = peak). Kharadi is the big, stable clinic (~120–150/mo). Baner is volatile — near-dark in Mar (16), then ramped hard from Apr (85). None is in structural decline.</div>')

# per clinic
for c in CLIN:
    vb,bd,note=VERDICT[c]
    w(f'<div class="clinic"><span class="ch">{c}</span><span class="badge {bd}">{vb}</span>')
    # doctor name
    docs=list(doc[c].keys())
    w(f'<div class="sub" style="margin-top:4px">Doctor(s): {", ".join(docs)}</div>')
    # KPIs
    wkvals=[wb[c].get(w_,0) for w_ in WK]; this=wkvals[-1]; sixavg=sum(wkvals[3:9])/6
    dnvals=[wd[c].get(w_,0) for w_ in WK]
    b2d_this=pct(dnvals[-1],wkvals[-1])
    pr_this=practo[PRACTO_NAME[c]].get("2026-06-15",0); pr6=sum(practo[PRACTO_NAME[c]].get(x,0) for x in WK[3:9])/6
    w('<div class="kpis">')
    w(f'<div class="kpi"><div class="k">Booked this wk</div><div class="v">{this}</div></div>')
    d=this-sixavg; w(f'<div class="kpi"><div class="k">vs 6-wk avg</div><div class="v {"up" if d>=0 else "down"}">{d/sixavg*100:+.0f}%</div></div>')
    w(f'<div class="kpi"><div class="k">B2D this wk</div><div class="v">{b2d_this}</div></div>')
    w(f'<div class="kpi"><div class="k">Practo this wk</div><div class="v">{pr_this}</div></div>')
    w('</div>')
    # bookings + done weekly
    w('<div class="cap">Bookings &amp; done · weekly</div>')
    w('<table><tr><th></th>'+''.join(f'<th>{x[5:]}</th>' for x in WK)+'<th>trend</th></tr>')
    w(f'<tr><td class="lbl">Booked</td>'+row_cells(wkvals)+f'<td>{spark(wkvals,"#3E6F8E")}</td></tr>')
    w(f'<tr style="color:var(--ink2)"><td>Done</td>'+row_cells(dnvals)+f'<td>{spark(dnvals,"#B8862E")}</td></tr>')
    b2dvals=[round(dnvals[i]/wkvals[i]*100) if wkvals[i] else None for i in range(len(WK))]
    w(f'<tr style="color:var(--muted)"><td>B2D %</td>'+"".join(f"<td>{v}%</td>" if v is not None else "<td>—</td>" for v in b2dvals)+'<td></td></tr>')
    w('</table>')
    # leads by channel (+ practo)
    w('<div class="cap">Leads by channel · weekly (incl. Practo)</div>')
    w('<table><tr><th>Channel</th>'+''.join(f'<th>{x[5:]}</th>' for x in WK)+'<th>trend</th></tr>')
    for ch in CH_ORDER:
        vals=[lc[c][ch].get(x,0) for x in WK]
        if sum(vals)==0: continue
        hi=' class="hi"' if ch in ("GMB call","Google") and c=="Chinchwad" else ''
        w(f'<tr{hi}><td class="lbl">{CH_LABEL[ch]}</td>'+row_cells(vals)+f'<td>{spark(vals,"#2E7D5B")}</td></tr>')
    prvals=[practo[PRACTO_NAME[c]].get(x,0) for x in WK]
    w(f'<tr><td class="lbl">Practo (sheet)</td>'+row_cells(prvals)+f'<td>{spark(prvals,"#B8862E")}</td></tr>')
    w('</table>')
    # doctors
    w('<div class="cap">Doctors · SC booked / done / B2D · weekly</div>')
    w('<table><tr><th>Doctor</th>'+''.join(f'<th>{x[5:]}</th>' for x in WK)+'</tr>')
    for dname in docs:
        bvals=[doc[c][dname].get(x,(0,0))[0] for x in WK]
        if sum(bvals)<3: continue
        w(f'<tr><td class="lbl">{dname}</td>'+row_cells(bvals)+'</tr>')
    w('</table>')
    # availability + reviews
    awd=[avwd[c].get(x,0) for x in WK]; awe=[avwe[c].get(x,0) for x in WK]
    rk="Pune|"+c; rn=rev.get(rk,{}).get("n",[]); rr=rev.get(rk,{}).get("rating",[])
    rn_recent=list(reversed(rn))[-6:] if rn else []
    avg_rating=next((x for x in rr if x), None)
    w('<div class="cap">Availability (active days · target wkday 4 / wkend 2) &amp; reviews</div>')
    w('<table><tr><th></th>'+''.join(f'<th>{x[5:]}</th>' for x in WK)+'</tr>')
    w(f'<tr><td class="lbl">Weekday active</td>'+row_cells(awd)+'</tr>')
    w(f'<tr><td class="lbl">Weekend active</td>'+row_cells(awe)+'</tr>')
    w('</table>')
    w(f'<div class="sub">GMB reviews (recent 6 wk): {rn_recent} · rating ~{avg_rating or "n/a"}★ · no negatives flagged.</div>')
    # what's happening + actions
    w(f'<div class="what"><b>What\'s happening:</b> {note}</div>')
    ACT={"Chinchwad":"→ <b>gmb-audit</b> (recover GMB calls 17→8) · ask Google Ads why Chinchwad paid went to 0 · <b>grow/stabilise Practo</b> (it exists ~4/wk but wobbled to 0 on Jun 1; other Pune clinics run far more).",
         "Kharadi":"→ <b>Rostering decision</b>: two doctors now split a flat 40 — confirm Dr. Mane was an intended ramp (else one is under-utilised). Demand healthy; keep feeding organic. No marketing action needed.",
         "Baner":"→ <b>Ops handoff</b>: book→done 92%→53% — investigate Dr. Neha's no-shows / scheduling. Demand fine (Practo carrying it, 3→12). No demand action."}
    w(f'<div class="act"><b>Action:</b> {ACT[c]}</div>')
    w('</div>')

# summary
w('<h2>Consolidated verdict</h2>')
w('<table><tr><th>Clinic</th><th>Doctor(s)</th><th>Real issue</th><th>Type</th><th>Owner</th></tr>')
w('<tr><td class="lbl">Chinchwad</td><td>Shantanu Chitale (sole)</td><td>GMB calls −53% + Google paid→0 (recovering)</td><td>Demand</td><td>gmb-audit + Google</td></tr>')
w('<tr><td class="lbl">Kharadi</td><td>Shaunak + Mane (new)</td><td>2-doctor load-split on a flat 40</td><td>Rostering</td><td>Supply planning</td></tr>')
w('<tr><td class="lbl">Baner</td><td>Neha Jeswani (sole)</td><td>book→done 92%→53%</td><td>Ops</td><td>Ops / show-up</td></tr>')
w('</table>')
w('<div class="what" style="margin-top:14px"><b>Bottom line:</b> Pune is healthy overall. The only genuine demand drop is <b>Chinchwad</b> (call channels, recovering, lead-side not doctor-side). <b>Kharadi</b> grew and just added a doctor. <b>Baner</b>\'s demand is fine — its gap is completion, which belongs to ops.</div>')
w('</div></body></html>')

out="/Users/alishaparveen/Downloads/pune_report.html"
open(out,"w").write("\n".join(H))
print("wrote",out,os.path.getsize(out),"bytes")
