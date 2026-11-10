"""Capture CampusRAG evidence and compare reviewed runs on a frozen dataset."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data/eval_campus_questions.json"
REASONS = {"검색 실패", "생성 오류", "링크 오류", "최신성 문제", "근거 없는 답변"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, payload, *, new=False):
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if new:
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
        return
    draft = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            draft = Path(temp.name)
            temp.write(content)
        draft.replace(path)
    finally:
        if draft is not None:
            draft.unlink(missing_ok=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def question_set(path, split):
    data = read_json(path)
    questions = data["questions"]
    if len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Duplicate question IDs")
    for q in questions:
        if not 1 <= len(q["question"]) <= 500:
            raise ValueError(f"Invalid question length: {q['id']}")
        if q["split"] not in {"dev", "test"} or q["origin"] not in {"llm", "student"}:
            raise ValueError(f"Invalid split or origin: {q['id']}")
    selected = [q for q in questions if split == "all" or q["split"] == split]
    if not selected:
        raise ValueError("No questions in selected split")
    return selected


def collect(args):
    questions = question_set(args.dataset, args.split)
    snapshot = args.snapshot.resolve()
    knowledge = snapshot / "unified_campus_knowledge.json"
    db = snapshot / "chroma_db"
    report = read_json(db / "ingest_report.json")
    index_files = sorted(path for path in db.rglob("*") if path.is_file()
                         and (path.suffix in {".bin", ".pickle"} or path.name == "chroma.sqlite3"))
    snapshot_hashes = {path.relative_to(snapshot).as_posix(): sha256(path)
                       for path in [knowledge, *index_files]}
    if "chroma_db/chroma.sqlite3" not in snapshot_hashes:
        raise ValueError("Missing snapshot database")

    os.environ["CHROMA_PERSIST_DIR"] = str(db)
    os.environ["CHROMA_COLLECTION_NAME"] = report["collection_name"]
    os.environ["NOTICES_PATH"] = str(knowledge)
    sys.path.insert(0, str(ROOT))
    import config
    from core.rag import CampusRAG

    provider = config.LLM_PROVIDER.lower()
    run = {
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset_sha256": sha256(args.dataset),
        "split": args.split,
        "snapshot": snapshot_hashes,
        "pipeline": {name: sha256(ROOT / name) for name in
                     ("config.py", "core/rag.py", "core/prompts.py", "core/embedder.py")},
        "config": {
            "mode": args.mode,
            "collection": report["collection_name"],
            "top_k": args.top_k,
            "provider": provider,
            "model": {"local": config.LOCAL_LLM_MODEL, "gemini": config.GEMINI_MODEL,
                      "openai": config.OPENAI_MODEL}[provider],
            "local_max_tokens": config.LOCAL_LLM_MAX_NEW_TOKENS,
            "embedding": config.EMBEDDING_MODEL_NAME,
            "threshold": config.RELEVANCE_THRESHOLD,
            "device": config.get_device(),
            "packages": {package: version(package) for package in
                         ("chromadb", "langchain-core", "sentence-transformers", "torch", "transformers")},
        },
        "results": [{"case": q, "status": "not_run"} for q in questions],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, run, new=True)
    rag = CampusRAG(load_llm=args.mode == "query")
    for i, row in enumerate(run["results"], 1):
        case = row["case"]
        try:
            if args.mode == "query":
                result = rag.query(case["question"], top_k=args.top_k, include_retrieved=True)
                row.update({key: result[key] for key in
                            ("answer", "sources", "status", "retrieved", "api_called")})
                if result.get("error_type"):
                    row["error_type"] = result["error_type"]
            else:
                docs = rag.retrieve(case["question"], top_k=args.top_k)
                row["status"] = "retrieval_only"
                row["retrieved"] = [{"content": doc.page_content, "metadata": doc.metadata}
                                    for doc in docs]
        except Exception as exc:
            row.update(status="capture_error", error_type=type(exc).__name__)
        write_json(args.output, run)
        print(f"{i}/{len(questions)} {case['id']} {row['status']}", flush=True)
        if row.get("error_type") in {"rate_limit", "auth_error"}:
            break


def review_template(run_path):
    run = read_json(run_path)
    return {
        "run_sha256": sha256(run_path),
        "reviewer": "",
        "reviewer_type": "",
        "judgments": {
            row["case"]["id"]: {"answer": None, "links": None, "reasons": [], "note": ""}
            for row in run["results"]
        },
    }


def review_rows(run_path, review_path, ids):
    if review_path is None:
        return None, {}
    review = read_json(review_path)
    if review["run_sha256"] != sha256(run_path):
        raise ValueError(f"Review belongs to a different run: {review_path}")
    if review["reviewer_type"] not in {"human", "ai"} or not review["reviewer"].strip():
        raise ValueError("Set reviewer and reviewer_type (human or ai)")
    judgments = review["judgments"]
    if set(judgments) - ids:
        raise ValueError(f"Review contains unknown question IDs: {review_path}")
    return review["reviewer_type"], judgments


def metric(passes, total):
    return {"pass": passes, "total": total, "percent": round(100 * passes / total, 2) if total else None}


def reference_hit(row, sources):
    expected = set(row["case"]["reference_urls"])
    urls = {item.get("url") or item.get("parent_url") for item in sources}
    return bool(expected) and expected <= urls


def summarize(rows, judgments, mode):
    answers, links, failures = [], [], Counter()
    applicable = [row for row in rows if row["case"]["reference_urls"]]
    for row in rows:
        case = row["case"]
        judgment = judgments.get(case["id"], {})
        answer, link = judgment.get("answer"), judgment.get("links")
        if any(value not in (None, "가", "부") for value in (answer, link)):
            raise ValueError(f"Invalid judgment: {case['id']}")
        if answer is None and link is None:
            continue
        if row["status"] not in {"success", "no_context", "title_only_notice"}:
            raise ValueError(f"Cannot grade an incomplete response: {case['id']}")
        if link is not None and not case["reference_urls"]:
            raise ValueError(f"Link grade requires a source-backed question: {case['id']}")
        if "부" in (answer, link):
            reasons = set(judgment["reasons"])
            if not reasons or not reasons <= REASONS or not judgment["note"].strip():
                raise ValueError(f"Failure requires valid reason(s) and note: {case['id']}")
            failures.update(reasons)
        if answer is not None:
            answers.append(answer)
        if link is not None:
            links.append(link)
    return {
        "cases": len(rows),
        "status": dict(Counter(row["status"] for row in rows)),
        "answer_reviewed": len(answers),
        "link_reviewed": len(links),
        "answer_accuracy": metric(answers.count("가"), len(rows)) if len(answers) == len(rows) else None,
        "link_accuracy": metric(links.count("가"), len(applicable)) if len(links) == len(applicable) else None,
        "failures_by_reason": dict(failures),
        "reference_retrieval_coverage": metric(sum(reference_hit(row, [
            doc["metadata"] for doc in row.get("retrieved", [])
        ]) for row in applicable), len(applicable)),
        "reference_citation_coverage": metric(
            sum(reference_hit(row, row.get("sources", [])) for row in applicable), len(applicable)
        ) if mode == "query" else None,
    }


def compare(args):
    before, after = read_json(args.before), read_json(args.after)
    for key in ("dataset_sha256", "split", "snapshot", "config"):
        if before[key] != after[key]:
            raise ValueError(f"Runs differ in {key}")
    if [row["case"] for row in before["results"]] != [row["case"] for row in after["results"]]:
        raise ValueError("Runs contain different questions")
    ids = {row["case"]["id"] for row in before["results"]}
    before_type, before_reviews = review_rows(args.before, args.before_review, ids)
    after_type, after_reviews = review_rows(args.after, args.after_review, ids)
    if before_type != after_type:
        raise ValueError("Use the same reviewer type for both runs")
    result = {"reviewer_type": before_type, "groups": {}}
    for group in ("all", "dev", "test"):
        first_rows = [row for row in before["results"] if group == "all" or row["case"]["split"] == group]
        second_rows = [row for row in after["results"] if group == "all" or row["case"]["split"] == group]
        if not first_rows:
            continue
        first = summarize(first_rows, before_reviews, before["config"]["mode"])
        second = summarize(second_rows, after_reviews, after["config"]["mode"])
        delta = {}
        for key in ("answer_accuracy", "link_accuracy"):
            if first[key] and second[key] and first[key]["total"]:
                delta[key] = round(second[key]["percent"] - first[key]["percent"], 2)
        result["groups"][group] = {"before": first, "after": second, "delta_pp": delta}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("collect")
    capture.add_argument("--dataset", type=Path, default=DATASET)
    capture.add_argument("--snapshot", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--split", choices=("all", "dev", "test"), default="all")
    capture.add_argument("--mode", choices=("query", "retrieve"), default="query")
    capture.add_argument("--top-k", type=int, choices=range(1, 11), default=3)
    review = commands.add_parser("review")
    review.add_argument("run", type=Path)
    review.add_argument("output", type=Path)
    comparison = commands.add_parser("compare")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    comparison.add_argument("--before-review", type=Path)
    comparison.add_argument("--after-review", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        collect(args)
    elif args.command == "review":
        write_json(args.output, review_template(args.run), new=True)
    else:
        compare(args)


if __name__ == "__main__":
    main()
