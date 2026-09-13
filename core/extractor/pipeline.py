"""
공지 단위 텍스트 추출, 결합 및 메타데이터 정규화 파이프라인 모듈.

HTML 본문, 이미지 OCR, 첨부파일(PDF/HWP/HWPX) 텍스트를 공지 단위로 안전하게 결합하고
원문 식별자 보존 및 Chroma DB 메타데이터 호환 변환을 보장한다.
"""

import json
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core.extractor.downloader import SafeDownloader
from core.extractor.hwp import extract_document_text
from core.extractor.ocr import extract_image_text
from core.extractor.pdf import extract_pdf_text

logger = logging.getLogger(__name__)


class NoticeEnricher:
    """공지사항의 이미지 및 첨부파일을 처리하여 본문과 메타데이터를 보강하는 파이프라인."""

    def __init__(
        self,
        downloader: SafeDownloader | None = None,
        max_pdf_pages: int = 10,
    ):
        self.downloader = downloader or SafeDownloader()
        self.max_pdf_pages = max_pdf_pages

    def extract_links_from_html(
        self, html_content: str, base_url: str
    ) -> tuple[str, list[str], list[dict]]:
        """
        상세 페이지 HTML에서 본문 텍스트, 이미지 URL 목록, 첨부파일 목록을 추출한다.

        Returns:
            (body_text, image_urls, attachments)
            attachments: [{"name": str, "url": str}]
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # 본문 텍스트
        body_el = soup.select_one(".view.viewCont .txt")
        body_text = body_el.get_text(strip=True) if body_el else ""

        # 이미지 URL 목록
        image_urls = []
        for img in soup.select(".view.viewCont img"):
            src = img.get("src")
            if src:
                abs_url = urljoin(base_url, src)
                if urlparse(abs_url).scheme in ("http", "https"):
                    image_urls.append(abs_url)

        # 첨부파일 링크 목록
        attachments = []
        # 한성대 첨부파일 링크 패턴
        file_links = soup.select('a[href*="download.do"]')
        for a in file_links:
            href = a.get("href")
            if not href:
                continue
            abs_url = urljoin(base_url, href)
            name = a.get_text(strip=True)
            # 바로보기 버튼 등 제외
            if name and name != "바로보기":
                # 내부 span 텍스트 등 정제
                clean_name = " ".join(name.split())
                attachments.append({"name": clean_name, "url": abs_url})

        return body_text, image_urls, attachments

    def enrich_notice(
        self,
        notice: dict,
        detail_html: str | None = None,
        image_urls: list[str] | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        """
        단일 공지사항에 대해 이미지 OCR 및 첨부파일 텍스트 추출을 수행하고 결합한다.

        원문 식별자(id, title, source, category, date, url)는 불변으로 유지된다.
        """
        enriched = dict(notice)
        base_url = notice.get("url", "https://www.hansung.ac.kr")

        # HTML이 제공된 경우 링크 파싱
        html_body = ""
        found_imgs = list(image_urls or [])
        found_atts = list(attachments or [])

        if detail_html:
            h_body, h_imgs, h_atts = self.extract_links_from_html(detail_html, base_url)
            if h_body:
                html_body = h_body
            if not found_imgs:
                found_imgs = h_imgs
            if not found_atts:
                found_atts = h_atts

        # 기존 content가 title과 동일하거나 비어있는지 확인
        existing_content = enriched.get("content", "").strip()
        title = enriched.get("title", "").strip()
        has_real_content = bool(existing_content and existing_content != title)

        final_body = html_body if html_body else (existing_content if has_real_content else "")

        images_result = []
        attachments_result = []

        # 1. 이미지 처리
        for img_url in found_imgs:
            cached_path, dl_status, dl_meta = self.downloader.download_file(img_url, validate_cache=True)
            if dl_status in ("downloaded", "cached") and cached_path:
                text, ocr_status, err = extract_image_text(cached_path)
                images_result.append({
                    "url": img_url,
                    "status": ocr_status,
                    "method": "ocr_tesseract",
                    "text": text,
                    "error": err,
                })
            else:
                images_result.append({
                    "url": img_url,
                    "status": dl_status,
                    "method": "ocr_tesseract",
                    "text": "",
                    "error": dl_meta.get("error", "다운로드 실패"),
                })

        # 2. 첨부파일 처리
        for att in found_atts:
            name = att.get("name", "")
            url = att.get("url", "")
            cached_path, dl_status, dl_meta = self.downloader.download_file(url, filename_hint=name, validate_cache=True)

            if dl_status in ("downloaded", "cached") and cached_path:
                lower_name = name.lower()
                if lower_name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    text, ocr_status, err = extract_image_text(cached_path)
                    attachments_result.append({
                        "name": name,
                        "url": url,
                        "status": ocr_status,
                        "method": "ocr_tesseract",
                        "text": text,
                        "error": err,
                    })
                elif lower_name.endswith(".pdf"):
                    text, pdf_status, err, details = extract_pdf_text(
                        cached_path, max_pages=self.max_pdf_pages
                    )
                    attachments_result.append({
                        "name": name,
                        "url": url,
                        "status": pdf_status,
                        "method": details.get("method", "pdf_text"),
                        "text": text,
                        "error": err,
                        "pages": details.get("processed_pages", 0),
                    })
                elif lower_name.endswith((".hwp", ".hwpx")):
                    text, doc_status, err, details = extract_document_text(
                        cached_path, filename_hint=name
                    )
                    attachments_result.append({
                        "name": name,
                        "url": url,
                        "status": doc_status,
                        "method": details.get("format", "hwp"),
                        "text": text,
                        "error": err,
                    })
                else:
                    attachments_result.append({
                        "name": name,
                        "url": url,
                        "status": "unsupported_format",
                        "method": "unsupported",
                        "text": "",
                        "error": f"미지원 파일 포맷: {name}",
                    })
            else:
                attachments_result.append({
                    "name": name,
                    "url": url,
                    "status": dl_status,
                    "method": "download",
                    "text": "",
                    "error": dl_meta.get("error", "다운로드 실패"),
                })

        # 3. 텍스트 결합 및 중복 제거
        combined_text, content_status = self._combine_and_deduplicate(
            title=title,
            base_body=final_body,
            images_result=images_result,
            attachments_result=attachments_result,
            prior_status=enriched.get("content_status", "title_only"),
        )

        enriched["content"] = combined_text
        enriched["content_status"] = content_status
        enriched["images"] = images_result
        enriched["attachments"] = attachments_result

        # 요약 메타데이터 생성
        successful_ocr = sum(1 for img in images_result if img.get("status") == "success" and img.get("text"))
        successful_att = sum(1 for att in attachments_result if att.get("status") in ("success", "partial") and att.get("text"))

        enriched["has_ocr"] = successful_ocr > 0
        enriched["has_attachment"] = successful_att > 0
        enriched["extraction_summary"] = (
            f"images: {successful_ocr}/{len(images_result)} ok, "
            f"attachments: {successful_att}/{len(attachments_result)} ok"
        )

        return enriched

    def _combine_and_deduplicate(
        self,
        title: str,
        base_body: str,
        images_result: list[dict],
        attachments_result: list[dict],
        prior_status: str,
    ) -> tuple[str, str]:
        """
        본문, 이미지 OCR, 첨부파일 텍스트를 결합하고 중복 텍스트를 정리한다.
        추출 불가를 정상 본문으로 취급하지 않으며, 날짜를 추측하지 않는다.
        """
        sections = []
        seen_paragraphs = set()

        def add_paragraph(text: str, label: str | None = None) -> None:
            clean = text.strip()
            if not clean:
                return

            # 공백 정규화된 전체 텍스트 키 (앞부분만 자르지 않고 전체 내용 비교)
            norm_full = "".join(clean.split())
            if not norm_full:
                return

            if norm_full in seen_paragraphs:
                return

            # 짧은 단순 반복 문구이고 이미 긴 문단에 포함된 경우만 스킵
            for seen in seen_paragraphs:
                if len(norm_full) < 40 and norm_full in seen:
                    return

            seen_paragraphs.add(norm_full)

            if label:
                sections.append(f"[{label}]\n{clean}")
            else:
                sections.append(clean)

        # 1. HTML 본문 추가
        if base_body:
            add_paragraph(base_body)

        has_ocr_text = False
        has_att_text = False

        # 2. 이미지 OCR 텍스트 추가
        for idx, img in enumerate(images_result):
            text = img.get("text", "").strip()
            if text and img.get("status") == "success":
                has_ocr_text = True
                img_name = img.get("url", "").split("/")[-1]
                add_paragraph(text, f"이미지 OCR 추출 #{idx+1}: {img_name}")

        # 3. 첨부파일 텍스트 추가
        for att in attachments_result:
            text = att.get("text", "").strip()
            if text and att.get("status") in ("success", "partial"):
                has_att_text = True
                att_name = att.get("name", "첨부파일")
                add_paragraph(text, f"첨부파일 추출: {att_name}")

        if not sections:
            # 추출된 텍스트가 전혀 없으면 기존 title_only 유지
            return title, "title_only"

        final_content = "\n\n".join(sections)

        # 상태 결정
        if has_ocr_text and (has_att_text or base_body):
            content_status = "mixed"
        elif has_ocr_text:
            content_status = "ocr"
        elif has_att_text and base_body:
            content_status = "mixed"
        elif has_att_text:
            content_status = "attachment"
        elif base_body:
            content_status = "text"
        else:
            content_status = prior_status if prior_status != "title_only" else "text"

        return final_content, content_status
