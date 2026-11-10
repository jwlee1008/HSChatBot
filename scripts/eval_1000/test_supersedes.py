import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']
title_map = {}
for n in notices:
    # clean title
    clean_t = re.sub(r'\[[^\]]*\]|\([^\)]*\)', '', n['title']).strip()
    title_map[n['id']] = (n['title'], clean_t)

# Check pairs where one title is a correction/extension of another
for n in notices:
    t = n['title']
    if re.search(r'\[[^\]]*수정[^\]]*\]|\[[^\]]*정정[^\]]*\]|\(수정\)|\(정정\)', t):
        clean_t = re.sub(r'\[[^\]]*수정[^\]]*\]|\[[^\]]*정정[^\]]*\]|\(수정\)|\(정정\)', '', t).strip()
        matches = [nid for nid, (orig_t, ct) in title_map.items() if nid != n['id'] and ct == clean_t]
        print(f"Correction: {t} -> potential originals: {matches}")
