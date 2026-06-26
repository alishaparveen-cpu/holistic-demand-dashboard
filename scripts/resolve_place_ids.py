#!/usr/bin/env python3
"""Resolve each clinic's Maps short-URL -> feature-id -> ChIJ place_id (no Places API).
Reads /tmp/clinic_mapurls.tsv (key<TAB>map_url), writes data_clinic_place_ids.json {key: place_id}.
"""
import subprocess, re, base64, struct, json, sys
def hexpair_to_chij(cell_hex, feat_hex):
    inner = bytes([0x09])+struct.pack('<Q',int(cell_hex,16))+bytes([0x11])+struct.pack('<Q',int(feat_hex,16))
    return base64.urlsafe_b64encode(bytes([0x0a,len(inner)])+inner).decode().rstrip('=')
out={}; rows=[l for l in open('/tmp/clinic_mapurls.tsv').read().splitlines() if '\t' in l]
for n,line in enumerate(rows,1):
    key,url=line.split('\t',1)
    if not url.startswith('http'): continue
    try:
        h=subprocess.run(['curl','-sIL','--max-time','15',url],capture_output=True,text=True).stdout
        m=re.search(r'0x([0-9a-fA-F]+):0x([0-9a-fA-F]+)',h)
        if m: out[key]=hexpair_to_chij(m.group(1),m.group(2))
    except Exception: pass
    if n%15==0: print('resolved %d/%d'%(len(out),len(rows)),flush=True)
json.dump(out,open('data_clinic_place_ids.json','w'),indent=0)
print('PLACEIDS_DONE %d/%d resolved'%(len(out),len(rows)),flush=True)
