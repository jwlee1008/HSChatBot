import sys
import json
import zipfile

sys.stdout.reconfigure(encoding='utf-8')

z = zipfile.ZipFile(r'C:\server01\.codex-work\campusrag-gemini-20261109\CampusRAG_Gemini_input.zip')
for shard_name in sorted(z.namelist()):
    if shard_name.startswith('sources/notice-'):
        content = z.read(shard_name).decode('utf-8')
        lines = [line for line in content.splitlines() if line.strip()]
        first = json.loads(lines[0])
        print(f"{shard_name}: {len(lines)} lines | Sample title: {first['title'][:40]} | publisher: {first.get('publisher')}")
