import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Find guidance documents by URL suffix
url_docs = {}
for d in snapshot:
    url = d.get('url', '')
    for num in ['6225', '6226', '6227', '6228', '6229', '6234', '6236', '6248', '6249', '6264', '6096']:
        if f'/{num}/subview.do' in url:
            url_docs[num] = d

for num, d in sorted(url_docs.items()):
    print(f"=== URL {num}: {d['title']} ({d['url']}) ===")
    lines = [l.strip() for l in (d.get('content') or '').splitlines() if l.strip()]
    for l in lines[:10]:
        print("  ", l[:90])
