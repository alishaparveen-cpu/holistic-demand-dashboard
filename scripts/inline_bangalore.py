#!/usr/bin/env python3
"""Inline the Bangalore city-funnel JSONs into bangalore.html so it works from file://,
an embed, or any server (no fetch needed). Re-run after any data re-pull / assemble.
  python3 scripts/inline_bangalore.py
"""
import os, json, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html_path = os.path.join(ROOT, "bangalore.html")
def L(f): return json.load(open(os.path.join(ROOT, f)))
D  = L("data_bangalore.json")
BA = L("data_bangalore_attribution.json")
PR = L("data_practo_leads.json")
BB = L("data_bangalore_bottom.json")
PL = L("data_bangalore_pool.json")
GA = L("data_ga_city_leads.json")
PI = L("data_bangalore_paid_intent.json")
def j(o): return json.dumps(o, separators=(",", ":"))
block = ("<!--INLINE_DATA_START--><script>"
         f"window.__D__={j(D)};window.__BA__={j(BA)};window.__PRACTO__={j(PR)};window.__BBOT__={j(BB)};window.__POOL__={j(PL)};window.__GACITY__={j(GA)};window.__PAIDINT__={j(PI)};"
         "</script><!--INLINE_DATA_END-->")
html = open(html_path).read()
html = re.sub(r"<!--INLINE_DATA_START-->.*?<!--INLINE_DATA_END-->", lambda m: block, html, flags=re.S)
open(html_path, "w").write(html)
print(f"inlined D+BA+PRACTO+BBOT ({len(block)} bytes) into bangalore.html")
