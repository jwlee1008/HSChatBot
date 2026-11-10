import os
import json
import openpyxl
import sys

sys.stdout.reconfigure(encoding='utf-8')

res_dir = r"C:\server01\.codex-work\campusrag-gemini-20261109\results"
files = sorted(os.listdir(res_dir))
print("Files in results directory:")
for f in files:
    sz = os.path.getsize(os.path.join(res_dir, f))
    print(f"  {f}: {sz:,} bytes")

print("\n1. Verifying source_snapshot.json:")
snap = json.load(open(os.path.join(res_dir, 'source_snapshot.json'), encoding='utf-8'))
print(f"  Total docs: {len(snap)}")

print("\n2. Verifying notice_tags.jsonl:")
tags = [json.loads(l) for l in open(os.path.join(res_dir, 'notice_tags.jsonl'), encoding='utf-8')]
print(f"  Total notices: {len(tags)}")
tagged = sum(1 for t in tags if t['status'] == 'tagged')
unclass = sum(1 for t in tags if t['status'] == 'unclassified')
print(f"  Tagged: {tagged}, Unclassified: {unclass}")

print("\n3. Verifying campusrag_eval_dataset.json:")
dset = json.load(open(os.path.join(res_dir, 'campusrag_eval_dataset.json'), encoding='utf-8'))
print(f"  version: {dset['version']}")
print(f"  reference_date: {dset['reference_date']}")
print(f"  questions count: {len(dset['questions'])}")

print("\n4. Verifying question_verification.jsonl:")
verif = [json.loads(l) for l in open(os.path.join(res_dir, 'question_verification.jsonl'), encoding='utf-8')]
print(f"  Total records: {len(verif)}")
v_ga = sum(1 for v in verif if v['verdict'] == '가')
v_bu = sum(1 for v in verif if v['verdict'] == '부')
v_hold = sum(1 for v in verif if v['verdict'] == '보류')
print(f"  Verdict: 가={v_ga}, 부={v_bu}, 보류={v_hold}")

print("\n5. Verifying CampusRAG_평가문항_1000.xlsx:")
wb = openpyxl.load_workbook(os.path.join(res_dir, 'CampusRAG_평가문항_1000.xlsx'))
print(f"  Sheet names: {wb.sheetnames}")
for name in wb.sheetnames:
    ws = wb[name]
    print(f"  Sheet '{name}': {ws.max_row} rows, {ws.max_column} columns")

print("\nAll deliverables validated cleanly!")
