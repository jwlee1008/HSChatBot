"""
한성대학교 공지사항 Playwright 크롤러

JavaScript 렌더링이 필요한 한성대 웹사이트를 Playwright로 크롤링한다.

사용법:
    python -m crawler.hansung_pw
    python -m crawler.hansung_pw --pages 3 --output data/crawled_notices.json
    python -m crawler.hansung_pw --pages 3 --with-content  # 상세 본문도 크롤링
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class Notice:
    """공지사항 데이터 클래스."""
    id: str
    title: str
    content: str
    source: str
    category: str
    date: str
    url: str
    content_status: str = "title_only"


# ── 크롤링 대상 정의 ──────────────────────────
# 한성대 게시판 URL 구조: /bbs/hansung/{boardId}/artclList.do
TARGETS = [
    {
        "name": "학교본부",
        "category": "공지",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/artclList.do",
    },
    {
        "name": "학교본부",
        "category": "장학",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/artclList.do?findType=sj&findWord=국가장학금",
    },
]


class HansungPlaywrightCrawler:
    """Playwright 기반 한성대학교 공지사항 크롤러."""

    BASE = "https://www.hansung.ac.kr"

    def __init__(self, headless: bool = True, with_content: bool = True):
        self.headless = headless
        self.with_content = with_content
        self.notices: list[Notice] = []

    def crawl_board(self, target: dict, max_pages: int = 3) -> list[Notice]:
        """게시판 한 개를 크롤링한다."""
        from playwright.sync_api import sync_playwright

        notices = []
        seen_urls = set()
        name = target["name"]
        category = target["category"]
        base_url = target["url"]

        logger.info("크롤링 시작: %s (%s)", name, base_url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()

            try:
                # 1단계: 목록 페이지에서 메타데이터 수집
                for page_num in range(1, max_pages + 1):
                    parts = urlparse(base_url)
                    params = dict(parse_qsl(parts.query))
                    params["page"] = str(page_num)
                    url = urlunparse(parts._replace(query=urlencode(params)))
                    logger.info("  페이지 %d 로딩", page_num)

                    response = page.goto(url, wait_until="networkidle", timeout=15000)
                    if response is None or not response.ok:
                        raise RuntimeError(f"목록 HTTP 오류: {url}")
                    page.wait_for_timeout(1000)

                    rows = page.query_selector_all("table tbody tr")
                    logger.info("  발견된 행: %d개", len(rows))

                    for i, row in enumerate(rows):
                        notice = self._parse_row(row, name, category, page_num, i, base_url)
                        if notice and notice.url not in seen_urls:
                            seen_urls.add(notice.url)
                            notices.append(notice)

                    time.sleep(0.5)

                # 2단계: 상세 페이지에서 본문 크롤링 (옵션)
                if self.with_content:
                    logger.info("  상세 본문 크롤링 시작 (%d건)", len(notices))
                    for j, notice in enumerate(notices):
                        if notice.url:
                            body = self._fetch_detail(page, notice.url)
                            if body is None:
                                notice.content_status = "fetch_failed"
                            elif body:
                                notice.content = body
                                notice.content_status = "text"
                            if (j + 1) % 10 == 0:
                                logger.info("    %d/%d 완료", j + 1, len(notices))
                            time.sleep(0.3)

            except Exception as e:
                logger.error("크롤링 오류 (%s): %s", name, e)
            finally:
                browser.close()

        notices = [n for n in notices if n.content_status != "fetch_failed"]
        logger.info("크롤링 완료: %s — %d건", name, len(notices))
        return notices

    def _parse_row(
        self, row, source: str, category: str, page_num: int, idx: int, base_url: str | None = None
    ) -> Notice | None:
        """게시판 행 하나를 파싱한다."""
        cells = row.query_selector_all("td")
        if len(cells) < 5:
            return None

        # td[0]: 번호, td[1]: 제목(링크), td[2]: 작성자, td[3]: 파일, td[4]: 날짜, td[5]: 조회수
        title_cell = cells[1]
        link_el = title_cell.query_selector("a")
        if not link_el:
            return None

        title = link_el.inner_text().strip()
        if not title:
            return None

        href = link_el.get_attribute("href") or ""
        href = urljoin(base_url or self.BASE, href)
        if urlparse(href).scheme not in {"http", "https"} or "artclView.do" not in urlparse(href).path:
            return None

        # 날짜: td.td-date (형식: 2026.09.07)
        date_str = cells[4].inner_text().strip() if len(cells) > 4 else ""
        date_normalized = self._normalize_date(date_str)

        # 작성자
        writer = cells[2].inner_text().strip() if len(cells) > 2 else ""

        # 본문: 기본값은 제목 (상세 본문은 2단계에서 크롤링)
        content = title

        notice_id = hashlib.sha256(href.encode()).hexdigest()

        return Notice(
            id=notice_id,
            title=title,
            content=content,
            source=f"{source} ({writer})" if writer else source,
            category=category,
            date=date_normalized,
            url=href,
        )

    def _fetch_detail(self, page, url: str) -> str | None:
        """상세 페이지에서 본문 텍스트를 가져온다."""
        try:
            response = page.goto(url, wait_until="networkidle", timeout=10000)
            if response is None or not response.ok:
                logger.warning("상세 페이지 HTTP 오류: %s", url)
                return None
            # 제목/조회수/첨부파일명을 본문으로 잘못 수집하지 않는다.
            content_el = page.query_selector(".view.viewCont .txt")
            if content_el:
                return content_el.inner_text().strip()
        except Exception as e:
            logger.warning("상세 페이지 실패 (%s): %s", url, e)
            return None
        return None

    def _normalize_date(self, date_str: str) -> str:
        """날짜 형식을 YYYY-MM-DD로 정규화한다."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")

        for fmt in ["%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(date_str.strip()[:10], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return date_str.strip()[:10]

    def crawl_all(self, max_pages: int = 3) -> list[Notice]:
        """모든 대상 게시판을 크롤링한다."""
        all_notices = []
        for target in TARGETS:
            notices = self.crawl_board(target, max_pages=max_pages)
            all_notices.extend(notices)

        self.notices = list({n.url: n for n in all_notices}.values())
        logger.info("전체 크롤링 완료: 총 %d건", len(all_notices))
        return self.notices

    def save_to_json(self, output_path: str) -> None:
        """크롤링 결과를 JSON 파일로 저장한다."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [asdict(n) for n in self.notices]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("JSON 저장 완료: %s (%d건)", output_path, len(data))


def main():
    parser = argparse.ArgumentParser(description="한성대학교 공지사항 Playwright 크롤러")
    parser.add_argument("--pages", type=int, default=3, help="크롤링할 페이지 수")
    parser.add_argument("--output", type=str, default="data/crawled_notices.json", help="출력 경로")
    parser.add_argument("--headed", action="store_true", help="브라우저 UI 표시 (디버깅용)")
    parser.add_argument("--with-content", action=argparse.BooleanOptionalAction, default=True, help="상세 페이지 본문 수집 (기본: 활성화)")
    args = parser.parse_args()

    crawler = HansungPlaywrightCrawler(
        headless=not args.headed,
        with_content=args.with_content,
    )
    crawler.crawl_all(max_pages=args.pages)

    if crawler.notices:
        crawler.save_to_json(args.output)
        print(f"\n✅ 크롤링 완료: {len(crawler.notices)}건 → {args.output}")
    else:
        raise SystemExit("크롤링 결과가 없습니다. 기존 JSON을 유지합니다.")


if __name__ == "__main__":
    main()
