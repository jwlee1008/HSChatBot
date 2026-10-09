"""Run retrieval checks against one snapshot without changing the service DB."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--cases", type=Path, required=True, help="Dated expectations for this refresh")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    report = json.loads((candidate / "refresh_report.json").read_text())
    if report["status"] != "validated_candidate":
        parser.error("Candidate must pass strict synchronization first")
    os.environ["CHROMA_PERSIST_DIR"] = str(candidate / "chroma_db")
    os.environ["CHROMA_COLLECTION_NAME"] = report["collection"]
    os.environ["NOTICES_PATH"] = str(candidate / "unified_campus_knowledge.json")
    from core.rag import CampusRAG
    rag = CampusRAG(load_llm=False)
    checks = json.loads(args.cases.read_text())["cases"]
    results = []
    for case in checks:
        docs = rag.retrieve(case["question"], top_k=args.top_k)
        relevant = [d for d in docs if d.metadata.get("url") in case["expected_urls"]
                    and (not case.get("expected_ids") or d.metadata.get("parent_id", d.metadata.get("id")) in case["expected_ids"])]
        text = "\n".join(d.page_content for d in relevant)
        normalized = re.sub(r"\s+", "", text)
        missing = [term for term in case.get("required_terms", []) if re.sub(r"\s+", "", term) not in normalized]
        results.append({"id": case["id"], "question": case["question"], "url_hit": bool(relevant),
                        "facts_present": bool(relevant) and not missing, "missing_terms": missing,
                        "required": case.get("required", True),
                        "returned": [{"url": d.metadata.get("url"), "title": d.metadata.get("title"),
                                      "chunk_id": d.metadata.get("chunk_id"), "content": d.page_content} for d in docs]})
    output = {"checked_at": datetime.now(timezone.utc).isoformat(), "retrieval_only": True,
              "candidate": str(candidate), "cases": str(args.cases.resolve()), "top_k": args.top_k,
              "passed": sum(r["facts_present"] for r in results), "total": len(results), "results": results}
    (candidate / "retrieval_report.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "results"}, ensure_ascii=False, indent=2))
    for result in results:
        print(result["id"], "PASS" if result["facts_present"] else "FAIL", result["missing_terms"])
    return int(any(r["required"] and not r["facts_present"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
