"""
한성대학교 공지사항 Playwright 크롤러

JavaScript 렌더링이 필요한 한성대 웹사이트를 Playwright로 크롤링한다.
BeautifulSoup 기반 크롤러의 한계를 극복하여 동적 페이지를 처리할 수 있다.

사용법:
    python -m crawler.hansung_pw
    python -m crawler.hansung_pw --pages 3 --output data/crawled_notices.json
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

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


# ── 크롤링 대상 정의 ──────────────────────────
TARGETS = [
    {
        "name": "학교본부",
        "category": "공지",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/artclList.do",
    },
    {
        "name": "대학뉴스",
        "category": "뉴스",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2183/artclList.do",
    },
]


class HansungPlaywrightCrawler:
    """Playwright 기반 한성대학교 공지사항 크롤러."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.notices: list[Notice] = []

    def crawl_board(
        self, target: dict, max_pages: int = 3
    ) -> list[Notice]:
        """게시판 한 개를 크롤링한다."""
        from playwright.sync_api import sync_playwright

        notices = []
        name = target["name"]
        category = target["category"]
        base_url = target["url"]

        logger.info("크롤링 시작: %s (%s)", name, base_url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()

            try:
                for page_num in range(1, max_pages + 1):
                    url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
                    logger.info("  페이지 %d 로딩: %s", page_num, url)

                    page.goto(url, wait_until="networkidle", timeout=15000)
                    page.wait_for_timeout(1000)  # JS 렌더링 대기

                    # 게시판 행 탐색 — 한성대 공지사항 게시판 구조에 맞게 셀렉터 시도
                    rows = page.query_selector_all(
                        "table tbody tr, "
                        ".board-list-content .board-list-item, "
                        "._artclTdTitle, "
                        ".artclList tr, "
                        "#board-list tbody tr"
                    )

                    if not rows:
                        # 대체 셀렉터: 제목 링크를 직접 탐색
                        rows = page.query_selector_all("a._artclTdTitle, .board-td-title a")

                    logger.info("  발견된 행: %d개", len(rows))

                    for i, row in enumerate(rows):
                        try:
                            notice = self._parse_row(page, row, name, category, page_num, i)
                            if notice:
                                notices.append(notice)
                        except Exception as e:
                            logger.debug("  행 파싱 실패: %s", e)
                            continue

                    time.sleep(0.5)  # 서버 부하 방지

            except Exception as e:
                logger.error("크롤링 오류 (%s): %s", name, e)
            finally:
                browser.close()

        logger.info("크롤링 완료: %s — %d건", name, len(notices))
        return notices

    def _parse_row(self, page, row, source: str, category: str, page_num: int, idx: int) -> Notice | None:
        """게시판 행 하나를 파싱하여 Notice로 반환한다."""
        # 제목 + 링크 추출
        title_el = row.query_selector("a") if row.query_selector("a") else row
        if not title_el:
            return None

        title = title_el.inner_text().strip()
        if not title or title in ("제목", "공지", "번호"):
            return None  # 헤더 행 건너뛰기

        href = title_el.get_attribute("href") or ""
        if href and not href.startswith("http"):
            href = f"https://www.hansung.ac.kr{href}"

        # 날짜 추출
        date_str = ""
        date_el = row.query_selector("td:nth-child(4), .board-td-date, .artcl-date")
        if date_el:
            date_str = date_el.inner_text().strip()
        date_normalized = self._normalize_date(date_str)

        # 본문은 목록에서 미리보기만 가져옴 (상세 크롤링은 선택)
        content = title  # 기본값: 제목을 내용으로 사용

        notice_id = f"{source}-p{page_num}-{idx+1:04d}"

        return Notice(
            id=notice_id,
            title=title,
            content=content,
            source=source,
            category=category,
            date=date_normalized,
            url=href,
        )

    def crawl_detail(self, page, url: str) -> str:
        """공지사항 상세 페이지에서 본문을 크롤링한다."""
        try:
            page.goto(url, wait_until="networkidle", timeout=10000)
            page.wait_for_timeout(500)

            content_el = page.query_selector(
                ".artclView, .board-view-content, "
                ".view-content, #bo_v_con, .bbs-view-body"
            )
            if content_el:
                return content_el.inner_text().strip()
        except Exception as e:
            logger.debug("상세 페이지 크롤링 실패 (%s): %s", url, e)
        return ""

    def _normalize_date(self, date_str: str) -> str:
        """날짜 형식을 YYYY-MM-DD로 정규화한다."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")

        for fmt in ["%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%y.%m.%d"]:
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

        self.notices = all_notices
        logger.info("전체 크롤링 완료: 총 %d건", len(all_notices))
        return all_notices

    def save_to_json(self, output_path: str) -> None:
        """크롤링 결과를 JSON 파일로 저장한다."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [asdict(n) for n in self.notices]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("JSON 저장 완료: %s (%d건)", output_path, len(data))


def main():
    parser = argparse.ArgumentParser(
        description="한성대학교 공지사항 Playwright 크롤러"
    )
    parser.add_argument("--pages", type=int, default=3, help="크롤링할 페이지 수")
    parser.add_argument("--output", type=str, default="data/crawled_notices.json", help="출력 경로")
    parser.add_argument("--headed", action="store_true", help="브라우저 UI 표시 (디버깅용)")
    args = parser.parse_args()

    crawler = HansungPlaywrightCrawler(headless=not args.headed)
    crawler.crawl_all(max_pages=args.pages)

    if crawler.notices:
        crawler.save_to_json(args.output)
        print(f"\n✅ 크롤링 완료: {len(crawler.notices)}건 → {args.output}")
    else:
        print("\n⚠️ 크롤링 결과가 없습니다. 사이트 구조를 확인하세요.")
        print("디버깅: --headed 옵션으로 브라우저를 표시하여 확인하세요.")


if __name__ == "__main__":
    main()
