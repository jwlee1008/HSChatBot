import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Sample scholarship notices
n_gagu = next(d for d in snapshot if '가구원 동의' in d.get('title', ''))
n_hisa = next(d for d in snapshot if '중소기업 취업연계 장학사업' in d.get('title', '') and '2학기' in d.get('title', ''))
n_incheon = next(d for d in snapshot if '인천인재평생교육진흥원' in d.get('title', ''))
n_insong = next(d for d in snapshot if '인송문화재단' in d.get('title', ''))

print("n_gagu:", n_gagu['id'][:10], n_gagu['title'])
print("n_hisa:", n_hisa['id'][:10], n_hisa['title'])
print("n_insong:", n_insong['id'][:10], n_insong['title'])
print("n_incheon:", n_incheon['id'][:10], n_incheon['title'])

# Let's inspect content of hisa
norm = ' '.join(n_hisa['content'].split())
print("hisa preview:", norm[:300])
