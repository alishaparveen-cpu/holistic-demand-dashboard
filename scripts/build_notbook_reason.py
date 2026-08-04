#!/usr/bin/env python3
"""Classify WHY a not-booked lead didn't book — from the call summary/transcript — into data_nbreason.json.

Only leads that CONNECTED on a call can be classified (others are web/Practo forms with no call).
Two modes:
  • ANTHROPIC_API_KEY set → auto-classify each unclassified lead via Claude, append to data_nbreason.json.
  • no key → print the leads' summaries so you (or Claude Code) can classify them by hand.

Taxonomy (label shown in the sc-calendar 'Why not booked' column):
  Wrong number / not a patient · Dropped / no response · Wanted online (only in-clinic offered) ·
  Considering (offered, not confirmed) · Advised walk-in (no slot booked) · No slot at wanted time ·
  Cost concern · ⚠ Agent said booked — no SC record · Other

Run: AWS_PROFILE=redshift-data [ANTHROPIC_API_KEY=…] python3 scripts/build_notbook_reason.py
"""
import os, sys, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = "INTERVAL '5 hours 30 minutes'"
def q(sql):
    p = subprocess.run([sys.executable, os.path.join(ROOT,"scripts","redshift_query.py")], input=sql, capture_output=True, text=True)
    if p.returncode!=0 or "ERROR" in (p.stderr or ""): sys.stderr.write((p.stderr or "")[:600]+"\n"); sys.exit(1)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l.strip()]

cube = json.load(open(os.path.join(ROOT,"data_sc_calendar.json")))
S, E = cube["_meta"]["week"].split("→"); E = (__import__("datetime").date.fromisoformat(E)+__import__("datetime").timedelta(days=2)).isoformat()
nbf = os.path.join(ROOT,"data_nbreason.json")
nb = json.load(open(nbf)) if os.path.exists(nbf) else {"_meta":{}, "leads":{}}

# not-booked leads that connected on a call, not already classified
todo=set()
for c in cube["clinics"].values():
    for day in c["days"].values():
        for l in day["leads"]:
            if not l.get("booked") and any(r["d"]>0 for r in l.get("recs",[])):
                ph=(l.get("p") or "")[-10:]
                if ph and ph not in nb["leads"]: todo.add(ph)
if not todo:
    print("nothing new to classify"); sys.exit(0)
print(f"{len(todo)} not-booked-connected leads to classify")

# pull each lead's representative inbound call summary + transcript
inlist = "','".join(sorted(todo))
rows = q(f"""
SELECT RIGHT(ec."from",10) ph,
  LEFT(REPLACE(REPLACE(COALESCE(ca.analysis.summary::varchar,''),CHR(10),' '),CHR(9),' '),500) summ,
  LEFT(REPLACE(REPLACE(COALESCE(ec.transcription,''),CHR(10),' '),CHR(9),' '),900) transcript
FROM allo_vendors.exotel_calls ec
LEFT JOIN allo_analytics.call_analyses ca ON ca.call_id=ec.call_id
WHERE ec.direction='inbound' AND ec.status='completed' AND RIGHT(ec."from",10) IN ('{inlist}')
  AND (ec.start_time + {IST})>='{S}' AND (ec.start_time + {IST})<'{E}'
""")
best={}   # phone → (summ, transcript) — keep the longest summary
for ph, summ, tr in [(r[0], r[1] if len(r)>1 else "", r[2] if len(r)>2 else "") for r in rows]:
    if ph not in best or len(summ) > len(best[ph][0]): best[ph]=(summ, tr)

TAXO = ("Wrong number / not a patient | Dropped / no response | Wanted online (only in-clinic offered) | "
        "Considering (offered, not confirmed) | Advised walk-in (no slot booked) | No slot at wanted time | "
        "Cost concern | ⚠ Agent said booked — no SC record | Other")
key = os.environ.get("ANTHROPIC_API_KEY")
if key:
    import anthropic
    cli = anthropic.Anthropic(api_key=key)
    for ph,(summ,tr) in best.items():
        txt = summ or tr
        prompt = (f"A lead called our health clinic but our records show NO screening-call booking for them. "
                  f"From this call, classify the single best reason they didn't book, choosing EXACTLY one label from:\n{TAXO}\n\n"
                  f"Call: {txt}\n\nReply as JSON: {{\"label\":\"<one label>\",\"note\":\"<=20-word specific reason>\"}}")
        try:
            m = cli.messages.create(model="claude-sonnet-5", max_tokens=200, messages=[{"role":"user","content":prompt}])
            j = json.loads(m.content[0].text[m.content[0].text.find("{"):m.content[0].text.rfind("}")+1])
            nb["leads"][ph] = {"reason":"llm", "label":j.get("label","Other"), "note":j.get("note","")}
            print(f"  {ph}: {j.get('label')}")
        except Exception as e:
            sys.stderr.write(f"  {ph}: classify failed ({e})\n")
    nb["_meta"]["week"]=cube["_meta"]["week"]
    json.dump(nb, open(nbf,"w"), indent=2, ensure_ascii=False)
    print(f"wrote {nbf} — now re-run build_sc_calendar.py (or its merge step) to attach")
else:
    print("\nNo ANTHROPIC_API_KEY — classify these by hand (add to data_nbreason.json 'leads'):\n")
    for ph,(summ,tr) in best.items():
        print(f"[{ph}] {(summ or tr)[:280]}\n")
    print(f"Taxonomy labels: {TAXO}")
