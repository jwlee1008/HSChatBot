"""Offline acceptance probes against frozen real notice text; never opens a DB.

Run: PYTHONPATH=. .venv/bin/python scripts/verify_real_notice_acceptance.py
An exit status of 1 means acceptance expectations were not met, not a runner error.
The first-2000-character probe is diagnostic, not the actual retrieval chunk.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.schedules.extraction import extract_schedule_candidates

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    fixture = json.loads((ROOT / "tests/fixtures/real_notice_acceptance_cases.json").read_text())
    dataset = ROOT / "data/unified_campus_knowledge.json"
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == fixture["dataset_sha256"]
    documents = {d["id"]: d for d in json.loads(dataset.read_text())}
    results = []
    for case in fixture["cases"]:
        doc = documents[case["doc_id"]]
        body = doc["content"]
        assert case["anchor"] in body, case["id"]
        text = case.get("input_excerpt", body)
        assert text in body
        response = extract_schedule_candidates(text, reference_time=fixture["reference_time"])
        candidates = [c.model_dump() for c in response.candidates]
        if "expected_count" in case:
            passed = len(candidates) == case["expected_count"]
        else:
            def matches(c):
                start = c.get("start_datetime") or c.get("start_date")
                end = c.get("end_datetime") or c.get("end_date")
                return (
                    end == case["expected_end"]
                    and ("expected_start" not in case or start == case["expected_start"])
                    and any(k in c["title"] for k in case["title_keywords"])
                )
            passed = any(matches(c) for c in candidates)
        grounded = all(c["source_quote"] in text for c in candidates)
        prefix = extract_schedule_candidates(text[:2000], reference_time=fixture["reference_time"])
        results.append({
            "case_id": case["id"], "doc_id": doc["id"], "title": doc["title"],
            "url": doc["url"], "input_characters": len(text),
            "anchor": case["anchor"], "anchor_in_prefix2000": case["anchor"] in text[:2000],
            "expected": {k: v for k, v in case.items() if k.startswith("expected_")},
            "passed": passed and grounded, "source_quotes_grounded": grounded,
            "candidates": candidates, "prefix2000_candidate_count": prefix.total_candidates,
        })
    print(json.dumps({"scope": fixture["scope"], "results": results,
                      "passed": sum(r["passed"] for r in results), "total": len(results)},
                     ensure_ascii=False, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
