import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

notices = [d for d in data if d.get('source_type') == 'notice']
print(f'Total notices: {len(notices)}')

for i, n in enumerate(notices[:15]):
    title = n.get('title', '')
    dt = n.get('date', '')
    cat = n.get('category', '')
    print(f'{i+1:3d}: [{dt}] [{cat}] {title[:60]}')
