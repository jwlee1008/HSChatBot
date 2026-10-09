"""Refresh regressions: current HTML reaches the DB without discarding valid OCR."""
import json

import pytest

from scripts import build_unified_dataset as builder


def document(content="신청 마감은 10월 20일", **changes):
    return {
        "id": "page-1",
        "url": "https://www.hansung.ac.kr/hansung/6231/subview.do",
        "title": "신청 안내",
        "content": content,
        "content_status": "text",
        "date": "2026-09-01",
        "last_checked_at": "2026-09-15T00:00:00Z",
        "images": [],
        "attachments": [],
        **changes,
    }


def enriched(**changes):
    return document(**{
        "content": "신청 마감은 10월 20일\n\n[자료: 신청서]\n제출 방법은 이메일",
        "html_content": "신청 마감은 10월 20일",
        "content_status": "mixed",
        "media_attempted_at": "2026-09-15T00:05:00Z",
        **changes,
    })


@pytest.mark.parametrize("status", ["mixed", "ocr", "ocr_enhanced", "attachment"])
def test_unchanged_html_later_check_preserves_media_text(status):
    old = enriched(content_status=status)
    raw = document(last_checked_at="2026-10-08T00:00:00Z")
    chosen, source, reason = builder.resolve_document_conflict(old, raw, "official_pages_enriched", "official_pages")
    assert chosen is old
    assert source == "official_pages_enriched"
    assert "preserve_ocr" in reason


@pytest.mark.parametrize("reverse", [False, True])
def test_changed_html_beats_stale_enrichment_in_either_input_order(reverse):
    old = enriched()
    raw = document(content="정정: 10월 10일 마감", last_checked_at="2026-10-08T00:00:00Z")
    if reverse:
        args = (raw, old, "official_pages", "official_pages_enriched")
    else:
        args = (old, raw, "official_pages_enriched", "official_pages")
    chosen, source, _ = builder.resolve_document_conflict(*args)
    assert chosen is raw
    assert source == "official_pages"


def test_changed_attachment_link_is_a_revision_even_with_equal_content_hash():
    old = enriched(attachments=[{"url": "https://www.hansung.ac.kr/old.hwp", "text": "과거 제출 기한"}], content_hash="same-hash")
    raw = document(attachments=[{"url": "https://www.hansung.ac.kr/new.hwp"}], content_hash="same-hash", last_checked_at="2026-10-08T00:00:00Z")
    chosen, _, reason = builder.resolve_document_conflict(old, raw, "official_forms_enriched", "official_forms")
    assert chosen is raw
    assert "revision" in reason


@pytest.mark.parametrize("status", ["empty", "fetch_failed", "text", "title_only"])
@pytest.mark.parametrize("content", ["", None])
def test_empty_newer_crawl_never_overwrites_success(status, content):
    old = enriched()
    raw = document(content=content, content_status=status, last_checked_at="2026-10-08T00:00:00Z", date="2026-10-08")
    chosen, source, reason = builder.resolve_document_conflict(old, raw, "official_pages_enriched", "official_pages")
    assert chosen is old
    assert source == "official_pages_enriched"
    assert "preserve" in reason


@pytest.mark.parametrize("known_html", [False, True])
def test_replaced_poster_does_not_keep_old_ocr_even_when_new_body_is_empty(known_html):
    old = enriched(images=[{"url": "https://www.hansung.ac.kr/old.png", "text": "이전 마감 기한"}])
    if not known_html:
        old.pop("html_content")
        old.pop("last_checked_at")
    new = document(content="", content_status="title_only", images=[{"url": "https://www.hansung.ac.kr/corrected.png"}], attachment_extraction_status="pending", last_checked_at="2026-10-08T00:00:00Z")
    chosen, _, reason = builder.resolve_document_conflict(old, new, "missing_notices_refreshed", "notice_archive")
    assert chosen is new
    assert "media_replacement" in reason


def test_successfully_observed_html_removal_discards_old_ocr():
    old = enriched()
    new = document(content="", content_status="title_only", attachment_extraction_status="not_applicable", last_checked_at="2026-10-08T00:00:00Z")
    chosen, _, reason = builder.resolve_document_conflict(old, new, "notice_archive_enriched", "notice_archive")
    assert chosen is new
    assert "source_removal" in reason


def test_unobserved_empty_or_stale_poster_preserves_success():
    old = enriched(images=[{"url": "https://www.hansung.ac.kr/old.png"}])
    new = document(content="", content_status="title_only", images=[{"url": "https://www.hansung.ac.kr/new.png"}], attachment_extraction_status="pending")
    chosen, _, _ = builder.resolve_document_conflict(old, new, "official_pages_enriched", "notice_archive")
    assert chosen is old


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    for name in ("official_pages_enriched", "official_faq", "official_forms_enriched", "missing_notices_refreshed", "notice_archive"):
        (data / f"{name}.json").write_text("[]", encoding="utf-8")
    return data


def write_documents(data, name, docs):
    (data / f"{name}.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def build(data, output=None):
    output = output or data / "unified.json"
    manifest = builder.build_unified_dataset(output, data / "manifest.json")
    return json.loads(output.read_text(encoding="utf-8")), manifest


def test_builder_includes_new_raw_guidance_forms_and_regular_notices(data_root):
    for index, (name, source_type) in enumerate((
        ("official_pages", "guidance"),
        ("official_forms", "form"),
        ("crawled_notices", "notice"),
        ("crawled_notices_enriched", "notice"),
        ("notice_archive_enriched", "notice"),
    )):
        write_documents(data_root, name, [document(id=f"doc-{index}", url=f"https://www.hansung.ac.kr/{index}", source_type="notice" if source_type == "form" else source_type)])
    docs, manifest = build(data_root)
    assert len(docs) == 5
    assert {d["source_type"] for d in docs} == {"guidance", "form", "notice"}
    assert docs[1]["source_type"] == "form"
    assert all(name in manifest["input_sources"] for name in ("official_pages", "official_forms", "crawled_notices", "crawled_notices_enriched", "notice_archive_enriched"))


def test_builder_advances_html_check_without_claiming_new_media_validation(data_root):
    old = enriched()
    raw = document(last_checked_at="2026-10-08T00:00:00Z")
    write_documents(data_root, "official_pages_enriched", [old])
    write_documents(data_root, "official_pages", [raw])
    docs, manifest = build(data_root)
    assert len(docs) == 1
    assert docs[0]["content"] == old["content"]
    assert docs[0]["last_checked_at"] == "2026-10-08T00:00:00+00:00"
    assert docs[0]["media_attempted_at"] == old["media_attempted_at"]
    assert "_source_name" not in docs[0]
    assert "html_check_advanced" in manifest["deduplication_summary"]["resolution_log_sample"][0]["reason"]


def test_builder_adopts_current_correction_over_old_ocr(data_root):
    write_documents(data_root, "official_pages_enriched", [enriched()])
    raw = document(content="정정: 10월 10일 마감", last_checked_at="2026-10-08T00:00:00Z")
    write_documents(data_root, "official_pages", [raw])
    docs, manifest = build(data_root)
    assert docs[0]["content"] == raw["content"]
    assert docs[0]["content_status"] == "text"
    assert manifest["deduplication_summary"]["overwritten_higher_quality"]["official_pages"] == 1


def test_failed_crawl_does_not_advance_last_successful_check(data_root):
    old = enriched()
    write_documents(data_root, "official_pages_enriched", [old])
    write_documents(data_root, "official_pages", [document(content=None, content_status="empty", last_checked_at="2026-10-08T00:00:00Z")])
    docs, _ = build(data_root)
    assert docs[0]["content"] == old["content"]
    assert docs[0]["last_checked_at"] == old["last_checked_at"]


def test_builder_failure_status_cannot_claim_successful_source_removal(data_root):
    old = enriched()
    write_documents(data_root, "official_pages_enriched", [old])
    write_documents(data_root, "notice_archive", [document(content=None, content_status="fetch_failed", attachment_extraction_status="not_applicable", last_checked_at="2026-10-08T00:00:00Z")])
    docs, _ = build(data_root)
    assert docs[0]["content"] == old["content"]
    assert "_crawl_failed" not in docs[0]


def test_builder_can_write_snapshot_outside_repository(data_root, tmp_path):
    output = tmp_path.parent / f"{tmp_path.name}-snapshot" / "unified.json"
    docs, manifest = build(data_root, output)
    assert docs == []
    assert manifest["output_summary"]["output_file"] == str(output)
