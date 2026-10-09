import json
from pathlib import Path

import pytest

from scripts import refresh_knowledge as refresh


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    active = tmp_path / "data/active_db"
    active.mkdir(parents=True)
    sentinel = active / "important.txt"
    sentinel.write_text("active database")
    monkeypatch.setattr(refresh, "active_db_path", lambda: active)
    monkeypatch.setattr(refresh, "build_dataset", lambda *args: {"documents": 2})

    def ingest(dataset, database, options):
        database.mkdir()
        (database / "candidate.txt").write_text("new database")
        return {"stored_chunks_count": 2}

    monkeypatch.setattr(refresh, "ingest_dataset", ingest)
    monkeypatch.setattr(refresh, "inspect_dataset", lambda *args: {"in_sync": True, "issues": []})
    return sentinel


def test_skip_collect_creates_unique_candidates_and_preserves_active(isolated, monkeypatch):
    monkeypatch.setattr(refresh, "collect_guidance", lambda *args: pytest.fail("network collection attempted"))
    first = refresh.refresh_knowledge(refresh.RefreshOptions(skip_collect=True))
    second = refresh.refresh_knowledge(refresh.RefreshOptions(skip_collect=True))
    assert first["status"] == "validated_candidate"
    assert first["activation_required"] is True
    assert first["database"] != second["database"]
    assert Path(first["database"]).is_relative_to(refresh.ROOT)
    assert isolated.read_text() == "active database"
    assert json.loads(Path(first["report_path"]).read_text())["status"] == "validated_candidate"


def test_collection_is_sequential_and_recent_boards_separate_from_forms(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(refresh, "collect_guidance", lambda options: calls.append("guidance") or {"errors": []})
    monkeypatch.setattr(refresh, "collect_faq", lambda options: calls.append("faq") or {})

    def collect_board(board, options, report):
        calls.append(board)
        assert options.since == "2026-09-03"
        assert report.name == f"board_{board}_report.json"
        return {"boards": {str(board): {"reached_since": True}}, "errors": []}

    monkeypatch.setattr(refresh, "collect_board", collect_board)
    refresh.refresh_knowledge(refresh.RefreshOptions(since="2026-09-03"))
    assert calls == ["guidance", "faq", 2127, 2128, 2203, 2195]
    assert isolated.read_text() == "active database"


@pytest.mark.parametrize("result", [
    {"errors": [{"url": "failed"}]},
    {"errors": [], "targets": [{"collection_status": "deferred_limit"}]},
    {"errors": [], "limit_reached": True},
    {"errors": [], "boards": {"2127": {"reached_since": False, "list_complete": False}}},
])
def test_partial_collection_stops_before_build_and_records_failure(isolated, monkeypatch, result):
    monkeypatch.setattr(refresh, "collect_guidance", lambda options: result)
    monkeypatch.setattr(refresh, "build_dataset", lambda *args: pytest.fail("must not build partial refresh"))
    with pytest.raises(refresh.RefreshFailed):
        refresh.refresh_knowledge()
    reports = list(refresh.ROOT.glob("data/knowledge_snapshots/*/refresh_report.json"))
    assert json.loads(reports[0].read_text())["status"] == "failed"
    assert isolated.read_text() == "active database"


def test_out_of_sync_candidate_never_reports_success(isolated, monkeypatch):
    monkeypatch.setattr(refresh, "inspect_dataset", lambda *args: {"in_sync": False, "issues": ["stale"]})
    with pytest.raises(refresh.RefreshFailed, match="strict synchronization"):
        refresh.refresh_knowledge(refresh.RefreshOptions(skip_collect=True))
    report = next(refresh.ROOT.glob("data/knowledge_snapshots/*/refresh_report.json"))
    assert json.loads(report.read_text())["status"] == "failed"
    assert isolated.read_text() == "active database"


def test_output_must_be_in_repo_and_outside_active_db(isolated, tmp_path):
    for path in (tmp_path.parent / "outside-repository", isolated.parent / "candidates"):
        with pytest.raises(ValueError):
            refresh.refresh_knowledge(refresh.RefreshOptions(output_root=path, skip_collect=True))
    assert isolated.read_text() == "active database"


def test_enrichment_budget_preserves_raw_and_reports_failed_media(isolated, monkeypatch):
    raw = refresh.ROOT / "data/official_pages.json"
    records = [{"url": f"https://www.hansung.ac.kr/{index}", "title": "title", "content": "HTML",
                "images": [{"url": f"https://www.hansung.ac.kr/{index}.png"}]} for index in range(3)]
    raw.write_text(json.dumps(records))
    original = raw.read_bytes()

    class FailedEnricher:
        def enrich(self, record):
            return {**record, "html_content": record["content"], "media_extraction_status": "failed_or_unsupported"}

    monkeypatch.setattr(refresh, "make_enricher", lambda *args: FailedEnricher())
    report = refresh.enrich_sources(refresh.RefreshOptions(max_media_documents=1, max_media_assets=1),
                                    refresh.ROOT / "data/enrichment_report.json")
    assert report["documents"] == report["assets"] == 1
    assert report["deferred"] == 2
    assert len(report["coverage_warnings"]) == 1
    assert raw.read_bytes() == original
    assert (raw.parent / "official_pages_enriched.json").exists()


@pytest.mark.parametrize("same_source", [True, False])
def test_failed_media_reuses_complete_text_only_for_unchanged_source(isolated, monkeypatch, same_source):
    data = refresh.ROOT / "data"
    record = {"url": "https://www.hansung.ac.kr/guide", "title": "guide", "content": "current HTML",
              "images": [{"url": "https://www.hansung.ac.kr/poster.png"}]}
    old = {**record, "html_content": record["content"] if same_source else "old HTML",
           "content": "previous extracted media", "media_extraction_status": "complete"}
    (data / "official_pages.json").write_text(json.dumps([record]))
    output = data / "official_pages_enriched.json"
    output.write_text(json.dumps([old]))

    class FailedEnricher:
        def enrich(self, doc):
            return {**doc, "html_content": doc["content"], "media_extraction_status": "failed_or_unsupported"}

    monkeypatch.setattr(refresh, "make_enricher", lambda *args: FailedEnricher())
    refresh.enrich_sources(refresh.RefreshOptions(), data / "enrichment_report.json")
    saved = json.loads(output.read_text())[0]
    assert saved["content"] == (old["content"] if same_source else record["content"])


def test_recent_notice_gets_media_budget_before_guidance(isolated, monkeypatch):
    data = refresh.ROOT / "data"
    record = {"url": "https://www.hansung.ac.kr/notice", "title": "notice", "content": "HTML",
              "date": "2026-10-08", "images": [{"url": "https://www.hansung.ac.kr/poster.png"}]}
    (data / "notice_archive.json").write_text(json.dumps([record]))
    (data / "official_pages.json").write_text(json.dumps([{**record, "url": "https://www.hansung.ac.kr/guide"}]))
    attempted = []

    class Enricher:
        def enrich(self, doc):
            attempted.append(doc["url"])
            return {**doc, "html_content": doc["content"], "media_extraction_status": "partial"}

    monkeypatch.setattr(refresh, "make_enricher", lambda *args: Enricher())
    report = refresh.enrich_sources(refresh.RefreshOptions(since="2026-09-03", max_media_documents=1),
                                    data / "enrichment_report.json")
    assert attempted == [record["url"]]
    assert report["deferred"] == 1
    assert len(report["coverage_warnings"]) == 1


@pytest.mark.parametrize("previous", [None, "/active/database"])
def test_ingest_restores_callers_environment_even_on_failure(monkeypatch, tmp_path, previous):
    import os
    from scripts import ingest_unified_db

    names = ("CHROMA_PERSIST_DIR", "CHROMA_COLLECTION_NAME")
    for name in names:
        if previous is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, previous)

    def failing_ingest(**kwargs):
        os.environ["CHROMA_PERSIST_DIR"] = str(kwargs["persist_dir"])
        os.environ["CHROMA_COLLECTION_NAME"] = kwargs["collection_name"]
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(ingest_unified_db, "ingest_unified", failing_ingest)
    with pytest.raises(RuntimeError, match="embedding failed"):
        refresh.ingest_dataset(tmp_path / "source.json", tmp_path / "candidate", refresh.RefreshOptions())
    assert all(os.environ.get(name) == previous for name in names)
