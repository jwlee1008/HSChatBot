"""Archive media refresh must preserve prior success without keeping stale OCR."""
import copy
import json

import pytest

from scripts import enrich_notice_archive as archive


def notice(key="old", date="2026-09-01", **changes):
    return {
        "id": key,
        "url": f"https://www.hansung.ac.kr/bbs/hansung/2127/{key}/artclView.do",
        "title": "신청 안내",
        "content": "신청 마감은 10월 20일",
        "content_status": "text",
        "date": date,
        "last_checked_at": "2026-10-08T00:00:00Z",
        "images": [{"url": "https://www.hansung.ac.kr/poster.png"}],
        "attachments": [],
        **changes,
    }


def previous(record, **changes):
    return {
        **record,
        "html_content": record["content"],
        "content": record["content"] + "\n\n[자료: 포스터]\n이메일 제출",
        "content_status": "mixed",
        "last_checked_at": "2026-09-15T00:00:00Z",
        "media_attempted_at": "2026-09-15T00:05:00Z",
        "media_extraction_status": "complete",
        **changes,
    }


@pytest.fixture
def mocked_extraction(monkeypatch):
    """No real downloader, OCR, embedding model, or external API can run."""
    attempted = []
    response_status = {}

    class MockExtractor:
        def enrich(self, record):
            attempted.append(record["url"])
            status = response_status.get(record["url"], "complete")
            return {
                **copy.deepcopy(record),
                "html_content": record.get("html_content", record["content"]),
                "content": record["content"] + ("\n\n신규 OCR 근거" if status == "complete" else ""),
                "content_status": "mixed" if status == "complete" else record["content_status"],
                "media_extraction_status": status,
            }

    monkeypatch.setattr(archive, "KnowledgeEnricher", MockExtractor)
    return attempted, response_status


def run(tmp_path, raw, old=(), **options):
    source = tmp_path / "raw.json"
    output = tmp_path / "enriched.json"
    source.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    output.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    report = archive.enrich_archive(source, output, **options)
    saved = {d["url"]: d for d in json.loads(output.read_text(encoding="utf-8"))}
    on_disk_report = json.loads((tmp_path / "enriched.json.report.json").read_text(encoding="utf-8"))
    assert on_disk_report == report
    assert json.loads(source.read_text(encoding="utf-8")) == raw
    return saved, report


def test_recent_or_title_only_selection_retains_entire_archive(tmp_path, mocked_extraction):
    attempted, _ = mocked_extraction
    recent = notice("recent", "2026-10-08")
    image_only = notice("image", "2026-08-20", content="", content_status="title_only")
    excluded = notice("excluded", "2026-08-19")
    saved, report = run(tmp_path, [excluded, image_only, recent], since="2026-09-15", title_only=True)
    assert attempted == [recent["url"], image_only["url"]]
    assert set(saved) == {d["url"] for d in [excluded, image_only, recent]}
    assert saved[excluded["url"]] == excluded
    assert report["selected"] == report["attempted"] == 2
    assert report["deferred"] == 0


def test_limit_prioritizes_latest_notice_and_counts_deferral(tmp_path, mocked_extraction):
    attempted, _ = mocked_extraction
    older = notice("older", "2026-09-20")
    latest = notice("latest", "2026-10-08")
    middle = notice("middle", "2026-10-01")
    saved, report = run(tmp_path, [older, latest, middle], since="2026-09-15", limit=1)
    assert attempted == [latest["url"]]
    assert saved[middle["url"]] == middle
    assert saved[older["url"]] == older
    assert report["selected"] == 3
    assert report["attempted"] == 1
    assert report["deferred"] == 2


def test_unselected_same_html_and_media_keeps_success_and_advances_html_check(tmp_path, mocked_extraction):
    attempted, _ = mocked_extraction
    raw = notice()
    old = previous(raw)
    saved, report = run(tmp_path, [raw], [old], since="2026-10-01")
    result = saved[raw["url"]]
    assert attempted == []
    assert report["attempted"] == 0
    assert result["content"] == old["content"]
    assert result["content_status"] == "mixed"
    assert result["last_checked_at"] == raw["last_checked_at"]
    assert result["media_attempted_at"] == old["media_attempted_at"]


@pytest.mark.parametrize("change", [
    {"content": "정정: 10월 10일 마감"},
    {"images": [{"url": "https://www.hansung.ac.kr/replacement.png"}]},
    {"images": []},
    {"attachments": [{"url": "https://www.hansung.ac.kr/new.hwp"}]},
])
def test_unselected_source_revision_discards_old_ocr(tmp_path, mocked_extraction, change):
    original = notice()
    raw = {**original, **change}
    saved, _ = run(tmp_path, [raw], [previous(original)], since="2026-10-01")
    assert saved[raw["url"]] == raw
    assert "이메일 제출" not in saved[raw["url"]]["content"]


@pytest.mark.parametrize("status", ["failed_or_unsupported", "partial"])
def test_failed_same_source_refresh_retains_complete_extraction(tmp_path, mocked_extraction, status):
    _, response_status = mocked_extraction
    raw = notice("recent", "2026-10-08")
    old = previous(raw)
    response_status[raw["url"]] = status
    saved, report = run(tmp_path, [raw], [old], since="2026-09-15")
    result = saved[raw["url"]]
    assert result["content"] == old["content"]
    assert result["media_extraction_status"] == "complete"
    assert result["media_refresh_status"] == status
    assert result["media_attempted_at"] == old["media_attempted_at"]
    assert result["media_last_failed_attempt_at"] > old["media_attempted_at"]
    assert result["last_checked_at"] == raw["last_checked_at"]
    assert report["documents"][0]["status"] == status


def test_failed_changed_html_cannot_restore_stale_complete_extraction(tmp_path, mocked_extraction):
    _, response_status = mocked_extraction
    original = notice("recent", "2026-10-08")
    raw = {**original, "content": "정정: 10월 10일 마감"}
    response_status[raw["url"]] = "failed_or_unsupported"
    saved, report = run(tmp_path, [raw], [previous(original)], since="2026-09-15")
    result = saved[raw["url"]]
    assert result["content"] == raw["content"]
    assert "이메일 제출" not in result["content"]
    assert result["media_extraction_status"] == "failed_or_unsupported"
    assert report["documents"][0]["status"] == "failed_or_unsupported"


def test_successful_refresh_replaces_prior_extraction(tmp_path, mocked_extraction):
    raw = notice("recent", "2026-10-08")
    saved, _ = run(tmp_path, [raw], [previous(raw)], since="2026-09-15")
    result = saved[raw["url"]]
    assert "신규 OCR 근거" in result["content"]
    assert "이메일 제출" not in result["content"]
    assert result["media_extraction_status"] == "complete"


def test_enrichment_rejects_raw_output_collision_before_reading(tmp_path, mocked_extraction):
    source = tmp_path / "raw.json"
    with pytest.raises(ValueError, match="separate input"):
        archive.enrich_archive(source, source)
    assert not source.exists()
