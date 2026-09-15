#!/usr/bin/env python3
"""
CampusRAG 통합 데이터셋 빌더 및 매니페스트 생성 스크립트

5대 공식 정보원(상시안내, FAQ, 서식, 보강공지, 공지아카이브)을 체계적으로 통합하여
중복을 제거하고 출처 메타데이터를 보존한 통합 지식 데이터셋과 매니페스트를 생성한다.
"""

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def compute_file_sha256(filepath: Path) -> str:
    """파일의 SHA-256 해시를 계산한다."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def compute_text_sha256(text: str) -> str:
    """텍스트의 SHA-256 해시를 계산한다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_url(url: str | None) -> str:
    """URL에서 해시/프래그먼트를 제거하고 정규화한다."""
    if not url:
        return ""
    return url.split("#")[0].strip()


def parse_iso_datetime(val: str | None) -> datetime | None:
    """날짜/시각 문자열을 타임존 인식 UTC datetime 객체로 정규화 변환한다."""
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass

    m = re.match(r"^(\d{4})[-.](\d{2})[-.](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hour = int(m.group(4) or 0)
            minute = int(m.group(5) or 0)
            sec = int(m.group(6) or 0)
            return datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def extract_doc_timestamp(doc: dict) -> str:
    """문서의 유효 수정일/게시일/확인일 추출 (호환성 유지용)."""
    for field in ("source_updated_at", "last_changed_at", "date", "last_checked_at", "collected_at"):
        val = doc.get(field)
        if val and isinstance(val, str) and len(val.strip()) >= 8:
            return val.strip()[:10]
    return ""


def resolve_document_conflict(existing: dict, new_doc: dict, existing_source: str, new_source: str) -> tuple[dict, str, str]:
    """
    중복 발생 시 결정적이고 투명한 규칙에 따라 문서를 채택/기각한다.
    원문 수정일(source_updated_at), 게시일(date), 확인/수집 시각(last_checked_at)을 구분 처리한다.
    반환: (chosen_doc, chosen_source, reason)
    """
    ex_status = existing.get("content_status", "text")
    new_status = new_doc.get("content_status", "text")
    ex_content = str(existing.get("content", "")).strip()
    new_content = str(new_doc.get("content", "")).strip()
    ex_len = len(ex_content)
    new_len = len(new_content)

    # 1) 실패 보존 및 극복
    # 기존이 유효 본문인데 신규가 빈 본문/수집 실패(title_only)인 경우 기존 보존
    if ex_status in ("text", "mixed", "ocr", "ocr_enhanced", "attachment") and new_status == "title_only":
        return existing, existing_source, "preserve_existing_valid_content_over_empty_crawl"

    # 기존이 title_only인데 신규가 유효 본문을 확보한 경우 신규 채택
    if ex_status == "title_only" and new_status in ("text", "mixed", "ocr", "ocr_enhanced", "attachment"):
        return new_doc, new_source, "recover_from_title_only_with_valid_content"

    # 2) 원문 수정일 (source_updated_at / last_changed_at) 비교
    # 원문 수정일은 확인/수집 시각보다 작성자의 실질 변경을 나타내는 강한 근거임
    ex_src_upd = parse_iso_datetime(existing.get("source_updated_at") or existing.get("last_changed_at"))
    new_src_upd = parse_iso_datetime(new_doc.get("source_updated_at") or new_doc.get("last_changed_at"))

    if ex_src_upd and new_src_upd:
        if new_src_upd > ex_src_upd:
            if new_status != "title_only":
                return new_doc, new_source, f"newer_source_updated_at_adopted ({new_src_upd.isoformat()} > {ex_src_upd.isoformat()})"
        elif new_src_upd < ex_src_upd:
            return existing, existing_source, f"stale_source_updated_at_rejected ({new_src_upd.isoformat()} < {ex_src_upd.isoformat()})"
    elif ex_src_upd and not new_src_upd:
        # 기존 문서는 권위있는 원문 수정일을 보유한 반면 신규 문서는 원문 수정일 부재
        return existing, existing_source, f"preserve_authoritative_source_updated_at ({ex_src_upd.isoformat()})"
    elif not ex_src_upd and new_src_upd:
        if new_status != "title_only":
            return new_doc, new_source, f"adopt_authoritative_source_updated_at ({new_src_upd.isoformat()})"

    # 3) 게시일/등록일 (date) 비교
    ex_date = parse_iso_datetime(existing.get("date"))
    new_date = parse_iso_datetime(new_doc.get("date"))

    if ex_date and new_date and ex_date != new_date:
        if new_date > ex_date:
            if new_status != "title_only":
                return new_doc, new_source, f"newer_date_adopted ({new_date.date()} > {ex_date.date()})"
        else:
            return existing, existing_source, f"stale_date_rejected ({new_date.date()} < {ex_date.date()})"

    # 4) 게시일이 동일하거나 둘 다 없는 경우: 확인 시각(last_checked_at/collected_at) 및 본문 변경 확인
    # 게시일이 유지된 상태에서 마감 정정/본문 축소 등이 재수집된 경우 반영
    ex_check = parse_iso_datetime(existing.get("last_checked_at") or existing.get("collected_at"))
    new_check = parse_iso_datetime(new_doc.get("last_checked_at") or new_doc.get("collected_at"))

    ex_hash = existing.get("content_hash") or compute_text_sha256(ex_content)[:16]
    new_hash = new_doc.get("content_hash") or compute_text_sha256(new_content)[:16]
    is_content_changed = bool(ex_hash != new_hash)

    if is_content_changed and ex_check and new_check:
        if new_check > ex_check:
            if new_status != "title_only":
                return new_doc, new_source, f"newer_crawl_revision_adopted ({new_check.isoformat()} > {ex_check.isoformat()})"
        elif new_check < ex_check:
            return existing, existing_source, f"stale_crawl_rejected ({new_check.isoformat()} < {ex_check.isoformat()})"

    # 5) 첨부/OCR 보강본 우선: 기존이 OCR 보강본인데 신규가 단순 HTML 텍스트이면 보존
    if ex_status in ("mixed", "ocr", "ocr_enhanced") and new_status == "text":
        return existing, existing_source, "preserve_ocr_enriched_over_plain_text"
    if ex_status == "text" and new_status in ("mixed", "ocr", "ocr_enhanced"):
        return new_doc, new_source, "adopt_ocr_enriched_over_plain_text"

    # 6) 소스 우선순위 비교
    source_rank = {
        "official_pages_enriched": 1,
        "official_faq": 2,
        "official_forms_enriched": 3,
        "missing_notices_refreshed": 4,
        "notice_archive": 5,
    }
    ex_rank = source_rank.get(existing_source, 99)
    new_rank = source_rank.get(new_source, 99)

    is_conflict = bool(ex_hash and new_hash and ex_hash != new_hash)

    if new_rank < ex_rank:
        reason = f"higher_authority_source ({new_source} > {existing_source})"
        if is_conflict:
            reason += " [version_conflict_resolved]"
        return new_doc, new_source, reason
    elif new_rank > ex_rank:
        reason = f"lower_authority_source ({new_source} < {existing_source})"
        if is_conflict:
            reason += " [version_conflict_ignored]"
        return existing, existing_source, reason

    # 7) 동일 랭크 내에서는 본문 길이 비교
    if new_len > ex_len:
        return new_doc, new_source, "longer_content_adopted"
    else:
        return existing, existing_source, "existing_content_equal_or_longer_retained"


def build_unified_dataset(
    output_path: Path = ROOT / "data/unified_campus_knowledge.json",
    manifest_path: Path = ROOT / "data/unified_manifest.json",
) -> dict:
    """
    5개 데이터 소스를 로드하여 단일 정규화 지식 데이터셋 및 매니페스트를 구축한다.
    """
    data_dir = ROOT / "data"

    sources_spec = [
        {
            "name": "official_pages_enriched",
            "file": data_dir / "official_pages_enriched.json",
            "default_source_type": "guidance",
            "description": "공식 상시 안내 HTML 및 미디어/첨부(PDF/HWP) 보강본",
            "priority": 1,
        },
        {
            "name": "official_faq",
            "file": data_dir / "official_faq.json",
            "default_source_type": "faq",
            "description": "공식 학사 FAQ (18개 목록 페이지의 179개 개별 질의응답)",
            "priority": 2,
        },
        {
            "name": "official_forms_enriched",
            "file": data_dir / "official_forms_enriched.json",
            "default_source_type": "form",
            "description": "공식 학사서식 및 서식 첨부파일 텍스트 추출본",
            "priority": 3,
        },
        {
            "name": "missing_notices_refreshed",
            "file": data_dir / "missing_notices_refreshed.json",
            "default_source_type": "notice",
            "description": "회귀 평가 기준 공지 99건 (OCR 및 포스터 전수 보강 완료)",
            "priority": 4,
        },
        {
            "name": "notice_archive",
            "file": data_dir / "notice_archive.json",
            "default_source_type": "notice",
            "description": "과거 공지사항 아카이브 (우선순위 게시판 960건)",
            "priority": 5,
        },
    ]

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "CampusRAG 보강 공지·상시 안내·FAQ·서식 통합 데이터 매니페스트",
        "input_sources": {},
        "deduplication_summary": {},
        "output_summary": {},
    }

    # 1. 원본 파일 존재 및 해시 검증
    raw_datasets = []
    for spec in sources_spec:
        fpath = spec["file"]
        if not fpath.exists():
            raise FileNotFoundError(f"필수 입력 파일을 찾을 수 없습니다: {fpath}")

        sha256 = compute_file_sha256(fpath)
        with open(fpath, "r", encoding="utf-8") as f:
            items = json.load(f)

        manifest["input_sources"][spec["name"]] = {
            "file_path": str(fpath.relative_to(ROOT)),
            "sha256": sha256,
            "raw_count": len(items),
            "description": spec["description"],
            "default_source_type": spec["default_source_type"],
            "priority": spec["priority"],
        }
        raw_datasets.append((spec, items))
        logger.info(
            "입력 소스 로드: %s (건수: %d, SHA: %s...)",
            spec["name"],
            len(items),
            sha256[:12],
        )

    # 2. 통합 및 정밀 중복 제거
    unified_docs = {}
    resolution_log = []
    dedup_audit = {
        "new_added": {},
        "overwritten_higher_quality": {},
        "skipped_duplicate_or_lower_quality": {},
    }

    def get_canonical_key(item: dict, spec: dict) -> tuple[str, str]:
        # FAQ는 같은 목록 URL에 여러 질문이 있으므로 반드시 item["id"]를 유일 키로 사용
        if spec["default_source_type"] == "faq" or item.get("source_type") == "faq":
            return ("faq", str(item["id"]))

        # 상시안내, 서식, 공지는 canonical URL 우선, 없으면 고유 id
        url = normalize_url(item.get("url"))
        if url:
            return ("url", url)
        return ("id", str(item["id"]))

    for spec, items in raw_datasets:
        sname = spec["name"]
        default_stype = spec["default_source_type"]
        new_cnt = 0
        overwritten_cnt = 0
        skipped_cnt = 0

        for raw_item in items:
            key = get_canonical_key(raw_item, spec)

            # 정규화된 도큐먼트 메타데이터 구성
            doc = dict(raw_item)

            # source_type 확정 (기존 값이 유효하면 보존, 없으면 default)
            doc_stype = doc.get("source_type") or default_stype
            if sname == "official_forms_enriched":
                doc_stype = "form"  # 서식 구분 명시
            doc["source_type"] = doc_stype

            # 날짜 정합성 보존: 수집 시각(last_checked_at)을 등록일(date)로 오용하지 않음
            # date가 없거나 유효하지 않으면 ""로 두고, 수집 시각은 last_checked_at으로 보존
            if "date" not in doc or doc["date"] is None:
                doc["date"] = ""
            doc["date"] = str(doc["date"]).strip()

            # 본문 해시 보존 또는 생성
            content = str(doc.get("content", "")).strip()
            title = str(doc.get("title", "")).strip()
            doc["content_hash"] = doc.get("content_hash") or compute_text_sha256(f"{title}\n{content}")[:16]

            # content_status 정규화
            content_status = doc.get("content_status")
            if not content_status:
                if not content or content == title:
                    content_status = "title_only"
                else:
                    content_status = "text"
            doc["content_status"] = content_status

            if key not in unified_docs:
                unified_docs[key] = doc
                unified_docs[key]["_source_name"] = sname
                new_cnt += 1
            else:
                existing = unified_docs[key]
                existing_source = existing.get("_source_name", "unknown")
                chosen_doc, chosen_source, reason = resolve_document_conflict(
                    existing, doc, existing_source, sname
                )
                if chosen_source == sname and chosen_doc is doc:
                    unified_docs[key] = doc
                    unified_docs[key]["_source_name"] = sname
                    overwritten_cnt += 1
                    resolution_log.append({
                        "id": str(key),
                        "decision": "overwritten",
                        "old_source": existing_source,
                        "new_source": sname,
                        "reason": reason,
                    })
                else:
                    skipped_cnt += 1
                    resolution_log.append({
                        "id": str(key),
                        "decision": "skipped",
                        "old_source": existing_source,
                        "attempted_source": sname,
                        "reason": reason,
                    })

        dedup_audit["new_added"][sname] = new_cnt
        dedup_audit["overwritten_higher_quality"][sname] = overwritten_cnt
        dedup_audit["skipped_duplicate_or_lower_quality"][sname] = skipped_cnt


    # 3. 통합 결과 리스트 생성 및 내부 임시 태그 제거
    final_docs = []
    status_counts = {}
    source_type_counts = {}

    for doc in unified_docs.values():
        doc_clean = dict(doc)
        doc_clean.pop("_source_name", None)

        cs = doc_clean.get("content_status", "unknown")
        st = doc_clean.get("source_type", "unknown")
        status_counts[cs] = status_counts.get(cs, 0) + 1
        source_type_counts[st] = source_type_counts.get(st, 0) + 1

        final_docs.append(doc_clean)

    # 4. JSON 파일 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_docs, f, ensure_ascii=False, indent=2)

    output_sha256 = compute_file_sha256(output_path)

    # 5. 매니페스트 완성 및 저장
    dedup_audit["total_conflicts_evaluated"] = len(resolution_log)
    dedup_audit["resolution_log_sample"] = resolution_log[:50]
    manifest["deduplication_summary"] = dedup_audit
    manifest["output_summary"] = {
        "output_file": str(output_path.relative_to(ROOT)),
        "output_sha256": output_sha256,
        "total_documents": len(final_docs),
        "content_status_counts": status_counts,
        "source_type_counts": source_type_counts,
        "title_only_residual": status_counts.get("title_only", 0),
        "text_or_enriched_count": len(final_docs) - status_counts.get("title_only", 0),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(
        "통합 데이터셋 생성 완료: 총 %d건 (text/enriched: %d, title_only: %d)",
        len(final_docs),
        manifest["output_summary"]["text_or_enriched_count"],
        manifest["output_summary"]["title_only_residual"],
    )
    logger.info("매니페스트 저장: %s", manifest_path)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CampusRAG Unified Dataset Builder")
    parser.add_argument("--output", type=Path, default=ROOT / "data/unified_campus_knowledge.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/unified_manifest.json")
    args = parser.parse_args()

    build_unified_dataset(output_path=args.output, manifest_path=args.manifest)
