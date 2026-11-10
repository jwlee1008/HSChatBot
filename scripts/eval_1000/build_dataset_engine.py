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
    u = d.get('url', '')
    if u and u not in DOC_BY_URL:
        DOC_BY_URL[u] = d

def normalize_text(text):
    return ' '.join((text or '').split())

def check_quote_in_doc(doc_id, quote):
    doc = DOC_BY_ID.get(doc_id)
    if not doc:
        return False, f"doc_id {doc_id} not in snapshot"
    t_norm = normalize_text(doc.get('title', ''))
    c_norm = normalize_text(doc.get('content', ''))
    q_norm = normalize_text(quote)
    if q_norm in t_norm or q_norm in c_norm:
        return True, "ok"
    return False, f"quote '{quote}' not found in doc_id {doc_id} ({doc.get('title')})"

def build_single(qid, category, split, family_id, question, expected_answer, doc_id, claim, quote, term=None):
    doc = DOC_BY_ID[doc_id]
    url = doc['url']
    ok, err = check_quote_in_doc(doc_id, quote)
    if not ok:
        raise ValueError(f"Error in {qid}: {err}")
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

def build_multi(qid, category, split, family_id, question, expected_answer, evidences, term=None):
    urls = []
    seen = set()
    ev_list = []
    for doc_id, claim, quote in evidences:
        doc = DOC_BY_ID[doc_id]
        url = doc['url']
        ok, err = check_quote_in_doc(doc_id, quote)
        if not ok:
            raise ValueError(f"Error in {qid}: {err}")
        if url not in seen:
            urls.append(url)
            seen.add(url)
        ev_list.append({
            "doc_id": doc_id,
            "url": url,
            "claim": claim,
            "quote": quote
        })
    if len(urls) < 2:
        raise ValueError(f"Error in {qid}: Multi requires at least 2 distinct URLs, got {len(urls)}")
    return {
        "id": qid,
        "category": category,
        "split": split,
        "origin": "llm",
        "family_id": family_id,
        "case_type": "multi",
        "question": question,
        "expected_answer": expected_answer,
        "reference_urls": urls,
        "evidence": ev_list,
        "term": term
    }

def build_abstain(qid, category, split, family_id, question, expected_answer, term=None):
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

print("Dataset engine loaded.")
