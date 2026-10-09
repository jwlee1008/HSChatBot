"""Checkpoint media extraction for recent notices and image-only archive notices."""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.official_site import atomic_json
from core.extractor.knowledge import KnowledgeEnricher
from scripts.build_unified_dataset import raw_revision_signature


def enrich_archive(input_path, output_path, since="", title_only=False, limit=None, retry_failed=False):
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("Keep raw notices in a separate input file")
    records = json.loads(Path(input_path).read_text(encoding="utf-8"))
    old = {d["url"]: d for d in json.loads(Path(output_path).read_text(encoding="utf-8"))} if Path(output_path).exists() else {}
    selected = [d for d in records if (not since and not title_only)
                or (since and d.get("date", "") >= since)
                or (title_only and d.get("content_status") == "title_only")]
    if retry_failed:
        selected = [d for d in selected if old.get(d["url"], {}).get("media_extraction_status") == "failed_or_unsupported"]
    selected.sort(key=lambda d: d.get("date", ""), reverse=True)
    selected_urls = {d["url"] for d in selected[:limit]}
    results = {}
    for record in records:
        prev = old.get(record["url"])
        signature = raw_revision_signature(record)
        if prev and signature is not None and raw_revision_signature(prev) == signature:
            results[record["url"]] = {**record, **prev, "last_checked_at": record.get("last_checked_at", prev.get("last_checked_at", ""))}
        else:
            results[record["url"]] = dict(record)
    extractor = KnowledgeEnricher()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "input": str(input_path),
              "selected": len(selected), "attempted": 0, "deferred": max(0, len(selected) - len(selected_urls)), "documents": []}
    for record in selected:
        if record["url"] not in selected_urls:
            continue
        enriched = extractor.enrich(record)
        enriched["media_attempted_at"] = datetime.now(timezone.utc).isoformat()
        prev = old.get(record["url"])
        signature = raw_revision_signature(record)
        if (prev and signature is not None and raw_revision_signature(prev) == signature
                and prev.get("media_extraction_status") == "complete"
                and enriched["media_extraction_status"] not in ("complete", "not_applicable")):
            enriched = {**results[record["url"]], "media_refresh_status": enriched["media_extraction_status"],
                        "media_last_failed_attempt_at": enriched["media_attempted_at"]}
        results[record["url"]] = enriched
        report["attempted"] += 1
        report["documents"].append({"url": record["url"], "title": record["title"],
                                    "status": enriched.get("media_refresh_status", enriched["media_extraction_status"]),
                                    "content_status": enriched["content_status"]})
        atomic_json(output_path, list(results.values()))
        atomic_json(str(output_path) + ".report.json", report)
        logging.info("%d/%d %s %s", report["attempted"], len(selected_urls), enriched["content_status"], record["title"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(output_path, list(results.values()))
    atomic_json(str(output_path) + ".report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/notice_archive.json")
    parser.add_argument("--output", default="data/notice_archive_enriched.json")
    parser.add_argument("--since", default="", help="Enrich notices published on/after this date")
    parser.add_argument("--title-only", action="store_true", help="Also enrich older image-only notices")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-failed", action="store_true", help="Retry only failed media extractions in the prior output")
    args = parser.parse_args()
    if args.since:
        datetime.strptime(args.since, "%Y-%m-%d")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = enrich_archive(args.input, args.output, args.since, args.title_only, args.limit, args.retry_failed)
    print(json.dumps({k: v for k, v in report.items() if k != "documents"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
