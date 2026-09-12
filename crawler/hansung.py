"""
한성대학교 공지사항 크롤러

학교 본부, 단과대, 학과별 공지사항을 크롤링하여 JSON으로 저장한다.

주의: 실제 크롤링은 대학 웹사이트 구조에 따라 조정이 필요합니다.
      이 코드는 한성대학교 공지사항 페이지의 일반적인 구조를 기반으로 작성되었으며,
      실제 사이트 구조가 변경되면 셀렉터를 수정해야 합니다.

사용법:
    python -m crawler.hansung
    python -m crawler.hansung --pages 5 --output data/notices.json
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_DELAY = 1.0  # 요청 간 대기 시간 (초) — 서버 부하 방지


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


@dataclass
class CrawlTarget:
    """크롤링 대상 정의."""

    name: str  # 출처 이름 (예: "학교본부")
    category: str  # 분류 (예: "학사")
    base_url: str  # 공지사항 목록 페이지 URL
    list_selector: str  # 목록에서 각 공지 행을 선택하는 CSS 셀렉터
    title_selector: str  # 행 내 제목 링크 셀렉터
    date_selector: str  # 행 내 날짜 셀렉터
    content_selector: str  # 상세 페이지 본문 셀렉터
    page_param: str = "page"  # 페이지 파라미터 이름


# ── 크롤링 대상 목록 ──────────────────────────
# 실제 한성대학교 웹사이트 구조에 맞게 셀렉터를 수정해야 합니다.
CRAWL_TARGETS: list[CrawlTarget] = [
    CrawlTarget(
        name="학교본부",
        category="학사",
        base_url="https://www.hansung.ac.kr/bbs/hansung/143/rssList.do",
        list_selector="item",
        title_selector="title",
        date_selector="dc:date",
        content_selector="description",
        page_param="page",
    ),
]


class HansungCrawler:
    """한성대학교 공지사항 크롤러."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.notices: list[Notice] = []

    def crawl_rss(self, target: CrawlTarget, max_items: int = 50) -> list[Notice]:
        """
        RSS 피드 기반으로 공지사항을 크롤링한다.

        많은 대학 사이트가 RSS를 제공하므로 RSS 우선 시도.
        """
        notices = []
        try:
            logger.info("RSS 크롤링 시작: %s (%s)", target.name, target.base_url)
            resp = self.session.get(target.base_url, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")[:max_items]

            for i, item in enumerate(items):
                title_tag = item.find("title")
                link_tag = item.find("link")
                desc_tag = item.find("description")
                date_tag = item.find("dc:date") or item.find("pubDate")

                title = title_tag.get_text(strip=True) if title_tag else ""
                link = link_tag.get_text(strip=True) if link_tag else ""
                content = desc_tag.get_text(strip=True) if desc_tag else ""
                date_str = date_tag.get_text(strip=True) if date_tag else ""

                # 날짜 포맷 정규화
                date_normalized = self._normalize_date(date_str)

                if title:
                    notice = Notice(
                        id=f"{target.name}-{i+1:04d}",
                        title=title,
                        content=content if content else title,
                        source=target.name,
                        category=target.category,
                        date=date_normalized,
                        url=link,
                    )
                    notices.append(notice)

            logger.info("RSS 크롤링 완료: %s — %d건", target.name, len(notices))

        except requests.RequestException as e:
            logger.warning("RSS 크롤링 실패 (%s): %s", target.name, e)
        except Exception as e:
            logger.error("RSS 파싱 오류 (%s): %s", target.name, e)

        return notices

    def crawl_html(
        self, target: CrawlTarget, pages: int = 3
    ) -> list[Notice]:
        """
        HTML 페이지 기반으로 공지사항을 크롤링한다.

        RSS가 없거나 실패한 경우 HTML 직접 파싱.
        """
        notices = []
        for page_num in range(1, pages + 1):
            try:
                url = f"{target.base_url}?{target.page_param}={page_num}"
                logger.info("HTML 크롤링: %s (페이지 %d)", target.name, page_num)

                resp = self.session.get(url, timeout=10)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                rows = soup.select(target.list_selector)

                for i, row in enumerate(rows):
                    title_el = row.select_one(target.title_selector)
                    date_el = row.select_one(target.date_selector)

                    if not title_el:
                        continue

                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")
                    if link and not link.startswith("http"):
                        # 상대 경로 → 절대 경로
                        from urllib.parse import urljoin
                        link = urljoin(target.base_url, link)

                    date_str = date_el.get_text(strip=True) if date_el else ""
                    date_normalized = self._normalize_date(date_str)

                    # 상세 페이지에서 본문 크롤링
                    content = self._fetch_content(link, target.content_selector)

                    notice_id = f"{target.name}-p{page_num}-{i+1:04d}"
                    notice = Notice(
                        id=notice_id,
                        title=title,
                        content=content if content else title,
                        source=target.name,
                        category=target.category,
                        date=date_normalized,
                        url=link,
                    )
                    notices.append(notice)

                time.sleep(REQUEST_DELAY)

            except requests.RequestException as e:
                logger.warning("HTML 크롤링 실패 (%s, p%d): %s", target.name, page_num, e)
            except Exception as e:
                logger.error("HTML 파싱 오류 (%s, p%d): %s", target.name, page_num, e)

        logger.info("HTML 크롤링 완료: %s — %d건", target.name, len(notices))
        return notices

    def _fetch_content(self, url: str, selector: str) -> str:
        """상세 페이지에서 본문 텍스트를 가져온다."""
        if not url:
            return ""
        try:
            time.sleep(REQUEST_DELAY)
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            content_el = soup.select_one(selector)
            if content_el:
                return content_el.get_text(strip=True, separator="\n")
        except Exception as e:
            logger.debug("본문 크롤링 실패 (%s): %s", url, e)
        return ""

    def _normalize_date(self, date_str: str) -> str:
        """다양한 날짜 형식을 YYYY-MM-DD로 정규화한다."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")

        # 일반적인 날짜 형식들
        formats = [
            "%Y-%m-%d",
            "%Y.%m.%d",
            "%Y/%m/%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y.%m.%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip()[:19], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return date_str.strip()[:10]

    def crawl_all(self, pages: int = 3) -> list[Notice]:
        """모든 대상을 크롤링한다."""
        all_notices = []
        for target in CRAWL_TARGETS:
            # RSS 우선 시도
            notices = self.crawl_rss(target)
            if not notices:
                # RSS 실패 시 HTML 파싱
                notices = self.crawl_html(target, pages=pages)
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
        description="한성대학교 공지사항 크롤러"
    )
    parser.add_argument(
        "--pages", type=int, default=3,
        help="크롤링할 페이지 수 (기본값: 3)",
    )
    parser.add_argument(
        "--output", type=str, default="data/crawled_notices.json",
        help="출력 JSON 파일 경로",
    )
    args = parser.parse_args()

    crawler = HansungCrawler()
    crawler.crawl_all(pages=args.pages)

    if crawler.notices:
        crawler.save_to_json(args.output)
        print(f"\n✅ 크롤링 완료: {len(crawler.notices)}건 → {args.output}")
    else:
        print("\n⚠️ 크롤링 결과가 없습니다. 사이트 구조를 확인하세요.")


if __name__ == "__main__":
    main()
