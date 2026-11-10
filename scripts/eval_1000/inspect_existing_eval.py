import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\services\hs-chatbot\data\eval_campus_questions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for i, q in enumerate(data['questions']):
    print(f"{i+1:2d}: [{q['id']}] [{q.get('category')}] {q['question']}")
    print(f"    Expected: {q['expected_answer']}")
    print(f"    Refs: {q.get('reference_urls')}")
