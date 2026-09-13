"""
기존 공지사항 JSON 데이터에 이미지 OCR 및 첨부파일 텍스트를 일괄 추출/보강하는 스크립트.

사용법:
    # 안전하게 별도 파일로 추출 (권장)
    python scripts/enrich_notices.py --input data/crawled_notices.json --output data/crawled_notices_enriched.json

    # 특정 키워드(예: 국가장학금) 공지만 선택 보강
    python scripts/enrich_notices.py --filter-keyword "국가장학" --limit 10
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
import requests

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extractor.downloader import SafeDownloader
from core.extractor.pipeline import NoticeEnricher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def enrich_notices_file(
    input_path: str,
    output_path: str,
    filter_keyword: str | None = None,
    limit: int | None = None,
    delay_sec: float = 0.5,
) -> None:
    in_p = Path(input_path)
    if not in_p.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {input_path}")

    with open(in_p, "r", encoding="utf-8") as f:
        notices = json.load(f)

    logger.info("로드된 전체 공지사항: %d건", len(notices))

    downloader = SafeDownloader()
    enricher = NoticeEnricher(downloader=downloader)

    enriched_list = []
    processed_count = 0

    for i, notice in enumerate(notices):
        title = notice.get("title", "")
        url = notice.get("url", "")

        # 키워드 필터링
        if filter_keyword and filter_keyword not in title and filter_keyword not in notice.get("content", ""):
            enriched_list.append(notice)
            continue

        if limit and processed_count >= limit:
            enriched_list.append(notice)
            continue

        logger.info("[%d/%d] 보강 처리 중: %s", i + 1, len(notices), title)

        # 원문 상세 HTML 가져오기 (SafeDownloader 정책 적용: SSRF 방어, 타임아웃, 크기 제한, 캐시)
        detail_html = None
        if url and url.startswith("http"):
            cached_html_path, dl_status, meta = downloader.download_file(
                url, filename_hint="detail.html", validate_cache=True
            )
            if dl_status in ("downloaded", "cached") and cached_html_path and cached_html_path.exists():
                try:
                    detail_html = cached_html_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    logger.warning("상세 HTML 파일 읽기 실패 (%s): %s", url, e)
            else:
                logger.warning("상세 HTML 수신 차단/실패 (%s): 상태=%s, 사유=%s", url, dl_status, meta.get("error"))

        try:
            enriched = enricher.enrich_notice(notice, detail_html=detail_html)
            enriched_list.append(enriched)
            processed_count += 1
            logger.info("  결과: 상태=%s, 요약=%s", enriched.get("content_status"), enriched.get("extraction_summary"))
        except Exception as e:
            logger.error("보강 실패 (%s): %s", title, e)
            enriched_list.append(notice)

        time.sleep(delay_sec)

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(enriched_list, f, ensure_ascii=False, indent=2)

    logger.info("✅ 보강 완료: 총 %d건 (보강 처리: %d건) -> %s", len(enriched_list), processed_count, output_path)


def main():
    parser = argparse.ArgumentParser(description="공지사항 이미지 OCR 및 첨부파일 텍스트 보강 도구")
    parser.add_argument("--input", type=str, default="data/crawled_notices.json", help="입력 JSON 경로")
    parser.add_argument("--output", type=str, default="data/crawled_notices_enriched.json", help="출력 JSON 경로")
    parser.add_argument("--filter-keyword", type=str, default=None, help="처리할 제목/본문 키워드 필터 (예: 국가장학)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 공지 수")
    parser.add_argument("--delay", type=float, default=0.5, help="요청 간 지연 시간(초)")
    args = parser.parse_args()

    enrich_notices_file(
        input_path=args.input,
        output_path=args.output,
        filter_keyword=args.filter_keyword,
        limit=args.limit,
        delay_sec=args.delay,
    )


if __name__ == "__main__":
    main()
