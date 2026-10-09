#!/usr/bin/env python3
"""Collect official sources and validate a new knowledge DB without activating it.

python scripts/refresh_knowledge.py
python scripts/refresh_knowledge.py --skip-collect
python scripts/refresh_knowledge.py --enrich --max-media-documents 30

Successful raw fetches are checkpointed even if a later fetch fails. Failed or
incomplete collection stops DB construction. Every DB is a new candidate; an
operator must explicitly change the service configuration after reviewing it.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOG = logging.getLogger(__name__)


@dataclass
class RefreshOptions:
    output_root: Path | None = None
    since: str | None = None
    skip_collect: bool = False
    enrich: bool = False
    guidance_max_pages: int = 200
    faq_max_pages: int = 30
    notice_max_pages: int = 20
    notice_max_notices: int = 300
    forms_max_pages: int = 20
    forms_max_notices: int = 150
    max_media_documents: int = 30
    max_media_assets: int = 60
    max_pdf_pages: int = 10
    collection: str = "campus_knowledge"
    batch_size: int = 100


class RefreshFailed(RuntimeError):
    pass


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def active_db_path():
    import config
    return Path(config.CHROMA_PERSIST_DIR).resolve()


def validate_output_root(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError("Candidate output must be inside the repository")
    protected = [active_db_path(), *(ROOT / "data" / name for name in (
        "chroma_db", "integrated_eval_chroma_db", "verify_demo_chroma_db", "eval_chroma_db"))]
    for db in protected:
        if path == db.resolve() or path.is_relative_to(db.resolve()):
            raise ValueError(f"Candidate output overlaps a protected DB: {db}")
    return path


def collect_guidance(options):
    from crawler.official_site import collect
    return collect(ROOT / "data/official_pages.json", ROOT / "data/official_site_inventory.json",
                   max_pages=options.guidance_max_pages)


def collect_faq(options):
    # The existing CLI publishes FAQ only after all advertised pages succeed,
    # and retains its existing snapshot when its 14-day check is not due.
    subprocess.run([sys.executable, "-m", "crawler.faq", "--output",
                    str(ROOT / "data/official_faq.json"), "--max-pages",
                    str(options.faq_max_pages)], cwd=ROOT, check=True)
    return {"status": "complete_or_not_due", "output": "data/official_faq.json"}


def collect_board(board, options, report_path):
    from crawler.notice_archive import collect
    forms = board == 2195
    return collect([board], ROOT / "data" / ("official_forms.json" if forms else "notice_archive.json"),
                   since="1900-01-01" if forms else options.since,
                   max_pages=options.forms_max_pages if forms else options.notice_max_pages,
                   max_notices=options.forms_max_notices if forms else options.notice_max_notices,
                   refresh=True, report_path=report_path)


def require_complete(report, stage):
    if report.get("errors"):
        raise RuntimeError(f"{stage}: {len(report['errors'])} collection error(s)")
    if report.get("limit_reached") or any(
        target.get("collection_status") == "deferred_limit" for target in report.get("targets", [])
    ):
        raise RuntimeError(f"{stage}: collection budget exhausted; increase the relevant limit")
    for board, scope in report.get("boards", {}).items():
        if not scope.get("reached_since") and not scope.get("list_complete"):
            raise RuntimeError(f"{stage}: board {board} did not finish its requested date range")


def make_enricher(max_pdf_pages):
    from core.extractor.knowledge import KnowledgeEnricher
    return KnowledgeEnricher(max_pdf_pages=max_pdf_pages)


def enrich_sources(options, report_path):
    """Bound media work across guidance, forms and notice records; keep raw JSON."""
    from scripts.build_unified_dataset import raw_revision_signature
    enricher = make_enricher(options.max_pdf_pages)
    report = {"documents": 0, "assets": 0, "deferred": 0, "coverage_warnings": []}
    # Recent and image-only notices get the bounded budget before older guides.
    for stem in ("notice_archive", "official_forms", "official_pages"):
        source = ROOT / "data" / f"{stem}.json"
        if not source.exists():
            continue
        output = ROOT / "data" / f"{stem}_enriched.json"
        previous = {d["url"]: d for d in json.loads(output.read_text())} if output.exists() else {}
        records = json.loads(source.read_text())
        if stem == "notice_archive":
            records = [d for d in records if d.get("date", "") >= options.since
                       or d.get("content_status") == "title_only"]
            records.sort(key=lambda d: d.get("date", ""), reverse=True)
        else:
            # Changed and incomplete guides precede already complete guides.
            records.sort(key=lambda d: previous.get(d["url"], {}).get("media_extraction_status") == "complete")
        for record in records:
            assets = len(record.get("images", [])) + len(record.get("attachments", []))
            if not assets:
                continue
            if (report["documents"] >= options.max_media_documents
                    or report["assets"] + assets > options.max_media_assets):
                report["deferred"] += 1
                continue
            enriched = enricher.enrich(record)
            stamp = datetime.now(timezone.utc).isoformat()
            enriched["media_attempted_at"] = stamp
            status = enriched["media_extraction_status"]
            if status not in ("complete", "not_applicable"):
                # Unsupported formats and bounded-PDF partials describe coverage,
                # not a failed HTML snapshot. Preserve the warning for review.
                report["coverage_warnings"].append({"url": record["url"], "status": status})
                old = previous.get(record["url"])
                signature = raw_revision_signature(record)
                if (old and signature is not None and raw_revision_signature(old) == signature
                        and old.get("media_extraction_status") == "complete"):
                    enriched = {**old, "media_refresh_status": status, "media_last_failed_attempt_at": stamp,
                                "coverage_status": "previous_media_retained_after_refresh_failure"}
            previous[record["url"]] = enriched
            report["documents"] += 1
            report["assets"] += assets
            write_json(output, list(previous.values()))
            write_json(report_path, report)
    write_json(report_path, report)
    return report


def build_dataset(dataset, manifest):
    from scripts.build_unified_dataset import build_unified_dataset
    return build_unified_dataset(output_path=dataset, manifest_path=manifest)


def ingest_dataset(dataset, database, options):
    from scripts.ingest_unified_db import ingest_unified
    # The ingester changes environment variables for isolation; restore the
    # caller's settings so a reusable refresh function cannot redirect it.
    names = ("CHROMA_PERSIST_DIR", "CHROMA_COLLECTION_NAME")
    previous = {name: os.environ.get(name) for name in names}
    try:
        return ingest_unified(dataset_path=dataset, persist_dir=database,
                              collection_name=options.collection, batch_size=options.batch_size)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def inspect_dataset(dataset, database, collection):
    from scripts.check_data_status import inspect_data_status
    return inspect_data_status(json_path=str(dataset), db_path=str(database),
                               collection_name=collection, strict=True)


def refresh_knowledge(options=None):
    options = options or RefreshOptions()
    options.since = options.since or (datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=35)).isoformat()
    datetime.strptime(options.since, "%Y-%m-%d")
    for name, value in vars(options).items():
        if (name.endswith("max_pages") or name.endswith("max_notices")
                or name.startswith("max_") or name == "batch_size") and value < 1:
            raise ValueError(f"{name} must be positive")
    parent = validate_output_root(options.output_root or ROOT / "data/knowledge_snapshots")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = parent / f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    dataset = run_dir / "unified_campus_knowledge.json"
    manifest = run_dir / "unified_manifest.json"
    database = run_dir / "chroma_db"
    report_path = run_dir / "refresh_report.json"
    report = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "since": options.since, "collection_skipped": options.skip_collect,
              "dataset": str(dataset), "manifest": str(manifest), "database": str(database),
              "collection": options.collection, "activation_required": True, "stages": {}}
    write_json(report_path, report)
    try:
        if not options.skip_collect:
            for name, operation in (("guidance", collect_guidance), ("faq", collect_faq)):
                LOG.info("Collecting %s", name)
                result = operation(options)
                report["stages"][name] = result
                write_json(report_path, report)
                require_complete(result, name)
            for board in (2127, 2128, 2203, 2195):
                name = f"board_{board}"
                LOG.info("Collecting %s", name)
                result = collect_board(board, options, run_dir / f"{name}_report.json")
                report["stages"][name] = result
                write_json(report_path, report)
                require_complete(result, name)
        if options.enrich:
            report["stages"]["enrichment"] = enrich_sources(options, run_dir / "enrichment_report.json")
            require_complete(report["stages"]["enrichment"], "enrichment")
        LOG.info("Building candidate dataset and DB in %s", run_dir)
        report["stages"]["build"] = build_dataset(dataset, manifest)
        report["stages"]["ingest"] = ingest_dataset(dataset, database, options)
        check = inspect_dataset(dataset, database, options.collection)
        write_json(run_dir / "sync_report.json", check)
        report["stages"]["strict_sync"] = check
        if not check.get("in_sync"):
            raise RuntimeError("Candidate DB failed strict synchronization: " + "; ".join(check.get("issues", [])))
        report["status"] = "validated_candidate"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise RefreshFailed(f"{error}\nReport: {report_path}") from error
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, help="Candidate parent inside this repository")
    parser.add_argument("--since", help="Notice refresh start date (default: 35 days ago, Asia/Seoul)")
    parser.add_argument("--skip-collect", action="store_true", help="Build from existing source JSON")
    parser.add_argument("--enrich", action="store_true", help="Attempt bounded image/attachment extraction")
    for name in ("guidance_max_pages", "faq_max_pages", "notice_max_pages", "notice_max_notices",
                 "forms_max_pages", "forms_max_notices", "max_media_documents", "max_media_assets",
                 "max_pdf_pages", "batch_size"):
        parser.add_argument("--" + name.replace("_", "-"), type=int,
                            default=getattr(RefreshOptions(), name))
    parser.add_argument("--collection", default="campus_knowledge")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        report = refresh_knowledge(RefreshOptions(**vars(args)))
    except (RefreshFailed, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    summary = {key: report[key] for key in (
        "status", "dataset", "database", "collection", "report_path", "activation_required")}
    media = report["stages"].get("enrichment")
    if media:
        summary["media_coverage"] = {"attempted_documents": media["documents"],
                                     "deferred_documents": media["deferred"],
                                     "warning_count": len(media["coverage_warnings"])}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
