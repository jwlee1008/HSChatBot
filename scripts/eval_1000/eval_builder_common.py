import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

SNAPSHOT_PATH = r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json'

with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

DOC_BY_ID = {d['id']: d for d in snapshot}
DOC_BY_URL = {}
for d in snapshot:
    url = d.get('url', '')
    if url and url not in DOC_BY_URL:
        DOC_BY_URL[url] = d

def normalize_text(text):
    return ' '.join(text.split())

def verify_quote(doc_id, quote):
    doc = DOC_BY_ID.get(doc_id)
    if not doc:
        return False, f"doc_id {doc_id} not in snapshot"
    title_norm = normalize_text(doc.get('title', ''))
    content_norm = normalize_text(doc.get('content', '') or '')
    q_norm = normalize_text(quote)
    if q_norm in title_norm or q_norm in content_norm:
        return True, "ok"
    return False, f"quote '{quote}' not found in doc {doc_id}"

def make_single_question(qid, category, split, family_id, question, expected_answer, doc_id, claim, quote, term=None):
    doc = DOC_BY_ID[doc_id]
    url = doc['url']
    ok, msg = verify_quote(doc_id, quote)
    if not ok:
        raise ValueError(f"Single Q [{qid}] verification failed: {msg}")
    return {
        "id": qid,
        "category": category,
        "split": split,
        "origin": "llm",
        "family_id": family_id,
        "case_type": "single",
        "question": question,
        "expected_answer": expected_answer,
        "reference_urls": [url],
        "evidence": [
            {
                "doc_id": doc_id,
                "url": url,
                "claim": claim,
                "quote": quote
            }
        ],
        "term": term
    }

def make_multi_question(qid, category, split, family_id, question, expected_answer, evidences, term=None):
    # evidences is list of (doc_id, claim, quote)
    ref_urls = []
    ev_list = []
    seen_urls = set()
    for doc_id, claim, quote in evidences:
        doc = DOC_BY_ID[doc_id]
        url = doc['url']
        ok, msg = verify_quote(doc_id, quote)
        if not ok:
            raise ValueError(f"Multi Q [{qid}] verification failed: {msg}")
        if url not in seen_urls:
            ref_urls.append(url)
            seen_urls.add(url)
        ev_list.append({
            "doc_id": doc_id,
            "url": url,
            "claim": claim,
            "quote": quote
        })
    if len(ref_urls) < 2:
        raise ValueError(f"Multi Q [{qid}] must have at least 2 distinct URLs, got {len(ref_urls)}")
    return {
        "id": qid,
        "category": category,
        "split": split,
        "origin": "llm",
        "family_id": family_id,
        "case_type": "multi",
        "question": question,
        "expected_answer": expected_answer,
        "reference_urls": ref_urls,
        "evidence": ev_list,
        "term": term
    }

def make_abstain_question(qid, category, split, family_id, question, expected_answer, term=None):
    return {
        "id": qid,
        "category": category,
        "split": split,
        "origin": "llm",
        "family_id": family_id,
        "case_type": "abstain",
        "question": question,
        "expected_answer": expected_answer,
        "reference_urls": [],
        "evidence": [],
        "term": term
    }

print("Common eval builder initialized successfully.")
