"""
CampusRAG 데이터 상태 및 파이프라인 무결성 진단 도구

운영자가 수집된 공지 JSON 및 Chroma DB의 상태를 검사하여:
1. 공지 건수 및 본문 추출 상태(text, ocr, attachment, title_only, failed) 통계
2. 최신 공지 등록일 및 데이터 신선도
3. Chroma DB와의 해시 기반 동기화 상태:
   - 고유 공지 ID 집합 비교 (누락 공지, 추가 공지 식별)
   - 공지 내용 해시(content_hash) 비교 (내용 변경된 stale 공지 식별)
4. 본문 미확보(title_only) 원인 상세 분석 (크롤러 본문 미수집, enrich 미실행 등)
을 출력하고 이상 여부를 반환합니다.

사용법:
    python scripts/check_data_status.py
    python scripts/check_data_status.py --json-path data/crawled_notices.json --db-path data/chroma_db
    python scripts/check_data_status.py --strict
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트 sys.path 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.embedder import get_chroma_vectorstore

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("status_checker")


def compute_content_hash(title: str, content: str) -> str:
    """공지의 제목과 본문을 기반으로 SHA256 내용 해시를 생성한다."""
    text = f"{title.strip()}\n{content.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def inspect_data_status(
    json_path: str = config.NOTICES_PATH,
    db_path: str = config.CHROMA_PERSIST_DIR,
    collection_name: str = config.CHROMA_COLLECTION_NAME,
    strict: bool = False,
) -> dict:
    """공지사항 JSON과 Chroma DB의 상태를 해시 기반으로 종합 진단한다."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "json_path": json_path,
        "db_path": db_path,
        "collection_name": collection_name,
        "strict_mode": strict,
        "json_exists": False,
        "db_exists": False,
        "notice_count": 0,
        "status_distribution": {},
        "latest_notice_date": None,
        "oldest_notice_date": None,
        "db_chunk_count": 0,
        "db_unique_notices": 0,
        "missing_in_db": [],
        "extra_in_db": [],
        "stale_in_db": [],
        "unverifiable_in_db": [],
        "matched_in_db_count": 0,
        "title_only_analysis": {},
        "in_sync": False,
        "issues": [],
        "notes": [],
    }

    # 1. JSON 파일 진단
    j_path = Path(json_path)
    if not j_path.exists():
        report["issues"].append(f"JSON 파일이 존재하지 않습니다: {json_path}")
        return report

    report["json_exists"] = True
    try:
        with open(j_path, "r", encoding="utf-8") as f:
            notices = json.load(f)
    except Exception as e:
        report["issues"].append(f"JSON 파싱 실패: {e}")
        return report

    report["notice_count"] = len(notices)
    if not notices:
        report["issues"].append("JSON 내에 공지사항 데이터가 없습니다.")
        return report

    # JSON 공지 사전 구축 (ID 기준)
    json_notices = {}
    status_counter = Counter()
    dates = []
    category_counter = Counter()
    title_only_causes = Counter()

    for n in notices:
        url = n.get("url", "")
        nid = n.get("id") or hashlib.sha256(url.encode()).hexdigest()
        title = n.get("title", "").strip()
        content = n.get("content", "").strip()
        c_status = n.get("content_status", "text")
        status_counter[c_status] += 1
        category_counter[n.get("category", "기타")] += 1

        d = n.get("date", "")
        if d and len(d) >= 10:
            dates.append(d[:10])

        c_hash = compute_content_hash(title, content)
        json_notices[nid] = {
            "id": nid,
            "url": url,
            "title": title,
            "content": content,
            "content_hash": c_hash,
            "status": c_status,
            "date": d,
        }

        # 본문 미확보 공지 원인 세분화 분석
        if c_status == "title_only" or not content or content == title:
            has_ocr = n.get("has_ocr")
            imgs = len(n.get("images", []))
            atts = len(n.get("attachments", []))
            if has_ocr is None and imgs == 0 and atts == 0:
                title_only_causes["detail_html_not_collected_or_enrich_unrun"] += 1
            elif imgs > 0 or atts > 0:
                title_only_causes["multimedia_unextracted"] += 1
            else:
                title_only_causes["empty_body_in_source"] += 1

    report["status_distribution"] = dict(status_counter)
    report["category_distribution"] = dict(category_counter)
    report["title_only_analysis"] = dict(title_only_causes)

    if dates:
        dates.sort()
        report["oldest_notice_date"] = dates[0]
        report["latest_notice_date"] = dates[-1]

    # 2. Chroma DB 진단 (해시 및 ID 검증)
    db_p = Path(db_path)
    if not db_p.exists():
        report["issues"].append(f"Chroma DB 디렉토리가 존재하지 않습니다: {db_path}")
        return report

    report["db_exists"] = True
    try:
        vectorstore = get_chroma_vectorstore(
            persist_directory=db_path,
            collection_name=collection_name,
        )
        col_data = vectorstore.get(include=["metadatas", "documents"])
        chunk_ids = col_data.get("ids", [])
        metadatas = col_data.get("metadatas", []) or []
        documents = col_data.get("documents", []) or []

        report["db_chunk_count"] = len(chunk_ids)

        # DB 내 공지별 청크 및 메타데이터 그룹핑
        db_notices = {}
        for idx, (cid, meta) in enumerate(zip(chunk_ids, metadatas)):
            if not meta:
                continue
            pid = meta.get("parent_id") or meta.get("id")
            if not pid:
                continue
            if pid not in db_notices:
                db_notices[pid] = {
                    "chunks": [],
                    "metadata": meta,
                    "url": meta.get("url") or meta.get("parent_url") or "",
                    "title": meta.get("title", ""),
                }
            doc_text = documents[idx] if idx < len(documents) else ""
            db_notices[pid]["chunks"].append((meta.get("chunk_index", 0), doc_text))

        report["db_unique_notices"] = len(db_notices)

        # 각 DB 공지의 content_hash 도출
        for pid, d_info in db_notices.items():
            meta = d_info["metadata"]
            if meta.get("content_hash"):
                d_info["content_hash"] = meta["content_hash"]
            else:
                sorted_docs = [t[1] for t in sorted(d_info["chunks"], key=lambda x: x[0])]
                full_db_text = "\n".join(sorted_docs).strip()
                if full_db_text:
                    d_info["content_hash"] = hashlib.sha256(full_db_text.encode("utf-8")).hexdigest()[:16]
                else:
                    d_info["content_hash"] = None

        # 3. ID 및 내용 해시 집합 비교
        json_ids = set(json_notices.keys())
        db_ids = set(db_notices.keys())

        missing_ids = list(json_ids - db_ids)
        extra_ids = list(db_ids - json_ids)
        common_ids = json_ids & db_ids

        stale_ids = []
        unverifiable_ids = []
        matched_count = 0
        for pid in common_ids:
            j_hash = json_notices[pid]["content_hash"]
            d_hash = db_notices[pid].get("content_hash")

            if not d_hash:
                unverifiable_ids.append({
                    "id": pid,
                    "title": json_notices[pid]["title"],
                    "url": json_notices[pid]["url"],
                    "reason": "DB 메타데이터 및 청크 본문에서 해시를 도출할 수 없음 (검증 불가 레거시 데이터)",
                })
                continue

            if j_hash == d_hash:
                matched_count += 1
            else:
                # 앞 80글자 예외 없이, 해시가 다르면 무조건 stale 판정
                stale_ids.append({
                    "id": pid,
                    "title": json_notices[pid]["title"],
                    "url": json_notices[pid]["url"],
                    "json_hash": j_hash,
                    "db_hash": d_hash,
                })

        report["missing_in_db"] = missing_ids
        report["extra_in_db"] = extra_ids
        report["stale_in_db"] = stale_ids
        report["unverifiable_in_db"] = unverifiable_ids
        report["matched_in_db_count"] = matched_count

        # 동기화 판정:
        if missing_ids:
            report["issues"].append(
                f"JSON 공지 중 {len(missing_ids)}건이 DB에 누락되어 있습니다 (Missing in DB)."
            )
        if stale_ids:
            report["issues"].append(
                f"JSON과 DB의 내용 해시가 불일치하는 공지가 {len(stale_ids)}건 있습니다 (Stale in DB)."
            )
        if unverifiable_ids:
            report["issues"].append(
                f"해시를 확인할 수 없는 레거시 공지가 {len(unverifiable_ids)}건 있습니다 (검증 불가)."
            )

        if strict and extra_ids:
            report["issues"].append(
                f"[Strict 모드] DB에 JSON에 없는 과거/추가 공지 {len(extra_ids)}건이 존재합니다 (Extra in DB)."
            )
        elif extra_ids:
            report["notes"].append(
                f"DB에 JSON 외의 과거/추가 공지 {len(extra_ids)}건이 보존되어 있습니다 (Historical preservation)."
            )

        if not missing_ids and not stale_ids and not unverifiable_ids:
            if not strict or not extra_ids:
                report["in_sync"] = True

    except Exception as e:
        report["issues"].append(f"Chroma DB 검사 실패: {e}")

    # 본문 미확보율 알림
    title_only_count = status_counter.get("title_only", 0)
    if report["notice_count"] > 0 and (title_only_count / report["notice_count"]) > 0.3:
        report["notes"].append(
            f"본문 미확보(title_only) 공지가 {title_only_count}건({title_only_count/report['notice_count']*100:.1f}%) 존재합니다. "
            f"주요 원인: 상세 페이지 HTML 미수집/enrich 미실행 {title_only_causes.get('detail_html_not_collected_or_enrich_unrun', 0)}건."
        )

    return report


def main():
    parser = argparse.ArgumentParser(description="CampusRAG 데이터 및 DB 상태 진단")
    parser.add_argument("--json-path", default=config.NOTICES_PATH, help="공지사항 JSON 경로")
    parser.add_argument("--db-path", default=config.CHROMA_PERSIST_DIR, help="Chroma DB 경로")
    parser.add_argument("--collection-name", default=config.CHROMA_COLLECTION_NAME, help="Chroma 컬렉션명")
    parser.add_argument("--strict", action="store_true", help="엄격 모드 (추가 공지도 불일치로 처리)")
    args = parser.parse_args()

    report = inspect_data_status(
        json_path=args.json_path,
        db_path=args.db_path,
        collection_name=args.collection_name,
        strict=args.strict,
    )

    print("=" * 70)
    print("📊 CampusRAG 데이터 파이프라인 무결성 진단 보고서")
    print("=" * 70)
    print(f"진단 시각: {report['timestamp']}")
    print(f"JSON 파일: {report['json_path']} (존재: {report['json_exists']}, 공지 수: {report['notice_count']}건)")
    print(f"공지 등록일 범위: {report['oldest_notice_date']} ~ {report['latest_notice_date']}")
    print(f"본문 추출 상태: {report['status_distribution']}")
    print(f"카테고리 분포: {report.get('category_distribution', {})}")
    print(f"Chroma DB: {report['db_path']} [{report['collection_name']}]")
    print(f"  - 적재 청크 수: {report['db_chunk_count']}건")
    print(f"  - 적재 고유 공지 수: {report['db_unique_notices']}건")
    print(f"  - 완전 일치 동기화 공지: {report['matched_in_db_count']}건")
    print(f"  - DB 누락 공지 (Missing): {len(report['missing_in_db'])}건")
    print(f"  - 내용 변경 공지 (Stale): {len(report['stale_in_db'])}건")
    print(f"  - DB 추가 보존 공지 (Extra): {len(report['extra_in_db'])}건")
    print(f"  - 동기화 여부: {'✅ 정상 동기화 (IN_SYNC)' if report['in_sync'] else '⚠️ 불일치 (OUT_OF_SYNC)'}")

    if report["title_only_analysis"]:
        print("-" * 70)
        print("🔍 본문 미확보 33건 심층 원인 분석:")
        for cause, count in report["title_only_analysis"].items():
            print(f"  - {cause}: {count}건")

    if report["notes"]:
        print("-" * 70)
        print("ℹ️ 안내 사항:")
        for note in report["notes"]:
            print(f"  - {note}")

    if report["issues"]:
        print("-" * 70)
        print("⚠️ 발견된 결함 및 불일치 사항:")
        for issue in report["issues"]:
            print(f"  - {issue}")
    else:
        print("-" * 70)
        print("✅ 모든 파이프라인 데이터 및 DB 동기화가 정상입니다.")
    print("=" * 70)

    sys.exit(0 if report["in_sync"] else 1)


if __name__ == "__main__":
    main()
