"""
CampusRAG 이미지 OCR 및 첨부파일(PDF, HWP, HWPX) 텍스트 추출기 단위 테스트.

작은 fixture와 mock을 사용하여 외부 사이트나 대형 모델 의존 없이 신속하고 격리된 검증을 수행한다.
"""

import io
import json
import struct
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from PIL import Image

from core.extractor.downloader import SafeDownloader, is_ip_private_or_restricted, is_safe_url
from core.extractor.hwp import extract_document_text, extract_hwp_text, extract_hwpx_text
from core.extractor.ocr import extract_image_text
from core.extractor.pdf import extract_pdf_text
from core.extractor.pipeline import NoticeEnricher


# ── 1. SSRF 방어 및 다운로더 테스트 ──────────────


def test_ssrf_blocks_private_and_loopback_ips():
    """사설망 IP, 루프백, 링크로컬 등이 안전하지 않은 것으로 판별되는지 확인."""
    assert is_ip_private_or_restricted("127.0.0.1") is True
    assert is_ip_private_or_restricted("10.0.0.1") is True
    assert is_ip_private_or_restricted("172.16.0.1") is True
    assert is_ip_private_or_restricted("192.168.1.1") is True
    assert is_ip_private_or_restricted("169.254.169.254") is True
    assert is_ip_private_or_restricted("::1") is True
    assert is_ip_private_or_restricted("8.8.8.8") is False

    safe, _ = is_safe_url("http://localhost:8000/api")
    assert safe is False

    safe, _ = is_safe_url("http://127.0.0.1/admin")
    assert safe is False

    safe, _ = is_safe_url("ftp://example.com/file")
    assert safe is False


def test_safe_downloader_cache_and_size_limit(tmp_path):
    """SafeDownloader가 파일 크기 상한을 초과하면 차단하고, 정상 다운로드는 캐싱하는지 검증."""
    downloader = SafeDownloader(cache_dir=tmp_path, max_file_size=100)

    # 1. 크기 초과 차단 (헤더)
    with patch("core.extractor.downloader.is_safe_url", return_value=(True, "ok")):
        with patch("requests.get") as mock_get:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Length": "500"}
            mock_resp.raise_for_status = Mock()
            mock_get.return_value = mock_resp

            path, status, meta = downloader.download_file("http://safe.example.com/big.pdf")
            assert status == "size_exceeded"
            assert path is None

    # 2. 정상 다운로드 및 캐싱
    with patch("core.extractor.downloader.is_safe_url", return_value=(True, "ok")):
        with patch("requests.get") as mock_get:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Length": "50"}
            mock_resp.iter_content.return_value = [b"sample content"]
            mock_resp.raise_for_status = Mock()
            mock_get.return_value = mock_resp

            target_url = "http://safe.example.com/file.txt"
            path1, status1, meta1 = downloader.download_file(target_url)
            assert status1 == "downloaded"
            assert path1 is not None and path1.exists()

            # 두 번째 호출 시 캐시된 파일 반환 (requests 호출 없이)
            mock_get.reset_mock()
            path2, status2, meta2 = downloader.download_file(target_url)
            assert status2 == "cached"
            assert path1 == path2
            mock_get.assert_not_called()


# ── 2. 이미지 OCR 단위 테스트 ───────────────────


def test_image_ocr_handles_missing_file_and_empty():
    """존재하지 않는 파일 또는 빈 파일 처리."""
    text, status, err = extract_image_text("non_existent.jpg")
    assert status == "failed"
    assert "존재하지 않거나" in err


def test_image_ocr_with_mocked_subprocess(tmp_path):
    """Tesseract 서브프로세스 실행 및 성공/실패 결과 파싱 검증."""
    # 작은 유효한 이미지 생성
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    img.save(img_path)

    with patch("core.extractor.ocr.get_tesseract_binary", return_value="/usr/bin/tesseract"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="2026년 2학기 국가장학금 신청 안내\n신청기간: 8.12~9.9\n",
                stderr="",
            )
            text, status, err = extract_image_text(img_path, cache_dir=tmp_path / "cache")
            assert status == "success"
            assert "국가장학금" in text
            assert err is None


# ── 3. PDF 텍스트 추출 테스트 ────────────────────


def test_text_pdf_extraction(tmp_path):
    """pypdf를 통해 생성된 텍스트 PDF fixture에서 텍스트가 정상 추출되는지 검증."""
    from pypdf import PdfWriter

    pdf_path = tmp_path / "sample_text.pdf"
    writer = PdfWriter()
    # pypdf로 빈 페이지 추가 후 텍스트 어노테이션/페이지 생성
    writer.add_blank_page(width=200, height=200)

    # 텍스트 레이어를 흉내내기 위해 mock Reader 또는 실제 파일 작성
    with open(pdf_path, "wb") as f:
        writer.write(f)

    # 텍스트가 충분한 페이지 mock
    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        mock_page = Mock()
        mock_page.extract_text.return_value = "제51기 해외봉사단 모집 공고문 내용입니다. 신청 기간은 9월 4일부터입니다."
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        text, status, err, details = extract_pdf_text(pdf_path, max_pages=5)
        assert status == "success"
        assert details["method"] == "pdf_text"
        assert "해외봉사단" in text
        assert err is None


def test_scanned_pdf_rendering_and_ocr_fallback(tmp_path):
    """텍스트가 없는 스캔 PDF인 경우 OCR로 전환되는지 검증."""
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy scanned pdf content")

    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        mock_page = Mock()
        mock_page.extract_text.return_value = ""  # 텍스트 없음 -> 스캔 판단
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        with patch("pypdfium2.PdfDocument") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.__len__.return_value = 1
            mock_render_page = Mock()
            mock_pil = Mock()
            mock_render_page.render.return_value.to_pil.return_value = mock_pil
            mock_doc.__getitem__.return_value = mock_render_page
            mock_doc_cls.return_value = mock_doc

            with patch("core.extractor.pdf.extract_image_text") as mock_ocr:
                mock_ocr.return_value = ("스캔된 문서의 OCR 텍스트입니다.", "success", None)

                text, status, err, details = extract_pdf_text(pdf_path, max_pages=5)
                assert status == "success"
                assert details["method"] == "pdf_ocr"
                assert "OCR 텍스트" in text


# ── 4. HWP / HWPX 추출 테스트 ────────────────────


def test_hwpx_extraction(tmp_path):
    """표준 XML 구조를 가진 가상 HWPX(zip) 파일에서 단락 텍스트 추출 검증."""
    hwpx_path = tmp_path / "sample.hwpx"

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
    <hp:p>
        <hp:run>
            <hp:t>국가장학금 신청 서식 안내문</hp:t>
        </hp:run>
    </hp:p>
    <hp:p>
        <hp:run>
            <hp:t>제출 기한은 2026년 9월 16일까지입니다.</hp:t>
        </hp:run>
    </hp:p>
</hs:sec>
"""
    with zipfile.ZipFile(hwpx_path, "w") as z:
        z.writestr("Contents/section0.xml", xml_content.encode("utf-8"))

    text, status, err, details = extract_hwpx_text(hwpx_path)
    assert status == "success"
    assert "국가장학금 신청 서식 안내문" in text
    assert "2026년 9월 16일" in text
    assert err is None


def test_hwp_encrypted_document_detected(tmp_path):
    """암호화 플래그가 설정된 HWP 파일에 대해 unsupported_encrypted 반환 검증."""
    hwp_path = tmp_path / "encrypted.hwp"
    hwp_path.write_bytes(b"dummy")

    with patch("olefile.isOleFile", return_value=True):
        with patch("olefile.OleFileIO") as mock_ole_cls:
            mock_ole = MagicMock()
            mock_ole.exists.return_value = True
            # FileHeader: 40바이트 이상, flags at offset 36: bit 1 (0x02) = encrypted
            header = bytearray(40)
            struct.pack_into("<I", header, 36, 0x02)
            mock_ole.openstream.return_value.read.return_value = bytes(header)
            mock_ole_cls.return_value = mock_ole

            text, status, err, details = extract_hwp_text(hwp_path)
            assert status == "unsupported_encrypted"
            assert "암호화" in err
            assert text == ""


def test_corrupted_file_handling(tmp_path):
    """손상된 파일에 대해 예외 없이 실패 상태와 에러를 반환하는지 검증."""
    bad_file = tmp_path / "corrupt.pdf"
    bad_file.write_bytes(b"not a valid pdf header")

    text, status, err, _ = extract_pdf_text(bad_file)
    assert status == "failed"
    assert err is not None

    bad_hwp = tmp_path / "corrupt.hwp"
    bad_hwp.write_bytes(b"not an ole file")
    text2, status2, err2, _ = extract_hwp_text(bad_hwp)
    assert status2 == "unsupported_format"


# ── 5. 파이프라인 결합 및 중복 정리 테스트 ─────────


def test_pipeline_combine_and_deduplicate(tmp_path):
    """HTML 본문, 이미지 OCR, 첨부파일 결합 시 중복 제거 및 식별자 보존 검증."""
    notice = {
        "id": "notice-001",
        "title": "2026년 2학기 국가장학금 2차 신청 안내",
        "content": "2026년 2학기 국가장학금 2차 신청 안내",  # title_only 상태
        "source": "학생복지팀",
        "category": "장학",
        "date": "2026-08-12",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do",
        "content_status": "title_only",
    }

    enricher = NoticeEnricher()
    # Mock downloader
    downloader = Mock()
    cached_img = tmp_path / "poster.jpg"
    cached_img.write_bytes(b"dummy image")
    downloader.download_file.return_value = (cached_img, "downloaded", {})
    enricher.downloader = downloader

    with patch("core.extractor.pipeline.extract_image_text") as mock_ocr:
        mock_ocr.return_value = (
            "신청기간: 2026.08.12 ~ 09.09\n대상: 재학생 및 복학생",
            "success",
            None,
        )

        enriched = enricher.enrich_notice(
            notice,
            image_urls=["https://www.hansung.ac.kr/images/poster.jpg"],
            attachments=[],
        )

        # 원문 식별자 불변 검증
        assert enriched["id"] == "notice-001"
        assert enriched["title"] == notice["title"]
        assert enriched["url"] == notice["url"]
        assert enriched["source"] == notice["source"]

        # 본문 결합 및 상태 전이 검증
        assert "신청기간: 2026.08.12 ~ 09.09" in enriched["content"]
        assert enriched["content_status"] == "ocr"
        assert enriched["has_ocr"] is True
        assert enriched["has_attachment"] is False
        assert len(enriched["images"]) == 1
        assert enriched["images"][0]["status"] == "success"


def test_pipeline_failed_extraction_preserves_title_only():
    """이미지/첨부파일 다운로드 실패 시 title_only 상태를 보존하고 가짜 본문을 만들지 않음."""
    notice = {
        "id": "notice-002",
        "title": "단순 제목 공지",
        "content": "단순 제목 공지",
        "source": "학교본부",
        "category": "학사",
        "date": "2026-09-01",
        "url": "https://www.hansung.ac.kr/notice/2",
        "content_status": "title_only",
    }

    enricher = NoticeEnricher()
    enricher.downloader = Mock()
    enricher.downloader.download_file.return_value = (None, "download_failed", {"error": "HTTP 404"})

    enriched = enricher.enrich_notice(
        notice,
        image_urls=["https://www.hansung.ac.kr/broken.jpg"],
    )

    assert enriched["content_status"] == "title_only"
    assert enriched["content"] == "단순 제목 공지"
    assert enriched["has_ocr"] is False
    assert enriched["images"][0]["status"] == "download_failed"


# ── 6. Codex 검토 회귀 테스트 ─────────────────────────


def test_pdf_mixed_text_and_scanned_page_by_page(tmp_path):
    """문서 전체 평균이 아닌 각 페이지별로 OCR 여부를 결정하는지 검증."""
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy mixed")

    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        # 1페이지: 텍스트 풍부 -> pdf_text
        p1 = Mock()
        p1.extract_text.return_value = "1페이지는 텍스트 레이어가 온전히 존재하는 상세 공지 내용입니다. 신청 기간은 8월 12일부터입니다."
        # 2페이지: 텍스트 없음 -> 스캔 페이지로 pdf_ocr 대상
        p2 = Mock()
        p2.extract_text.return_value = ""
        mock_reader.pages = [p1, p2]
        mock_reader_cls.return_value = mock_reader

        with patch("pypdfium2.PdfDocument") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.__len__.return_value = 2
            mock_page_render = Mock()
            mock_page_render.render.return_value.to_pil.return_value = Mock()
            mock_doc.__getitem__.return_value = mock_page_render
            mock_doc_cls.return_value = mock_doc

            with patch("core.extractor.pdf.extract_image_text") as mock_ocr:
                mock_ocr.return_value = ("2페이지 스캔 포스터 OCR 추출 텍스트", "success", None)

                text, status, err, details = extract_pdf_text(pdf_path, max_pages=5)
                assert status == "success"
                assert len(details["pages"]) == 2
                assert details["pages"][0]["method"] == "pdf_text"
                assert details["pages"][1]["method"] == "pdf_ocr"
                assert "1페이지는 텍스트" in text
                assert "2페이지 스캔 포스터 OCR" in text


def test_deduplication_preserves_different_tail_or_dates():
    """앞 80글자가 같더라도 뒤의 날짜/조건이 다르면 중복으로 삭제되지 않고 보존되는지 검증."""
    enricher = NoticeEnricher()
    long_prefix = "본 공지사항은 2026학년도 한성대학교 학생 대상 국가장학금 신청 절차 및 가구원 동의 안내문입니다. " * 2
    # 앞 80글자 이상 완벽 일치
    assert len(long_prefix) > 80

    body1 = long_prefix + "신청 기간: 2026.08.12 ~ 2026.09.09"
    img_ocr = long_prefix + "서류 제출 및 가구원 동의 기한: 2026.08.12 ~ 2026.09.16"

    combined, status = enricher._combine_and_deduplicate(
        title="국가장학금 안내",
        base_body=body1,
        images_result=[{"status": "success", "text": img_ocr, "url": "poster.jpg"}],
        attachments_result=[],
        prior_status="title_only",
    )

    # 두 정보가 모두 본문에 남아있어야 함
    assert "2026.09.09" in combined
    assert "2026.09.16" in combined


def test_pdf_page_exception_preserves_successful_pages_and_records_partial(tmp_path):
    """페이지별 추출/렌더링 중 예외 발생 시 성공한 페이지는 보존되고 상태가 partial로 기록되는지 검증."""
    pdf_path = tmp_path / "partial_fail.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy partial")

    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        p1 = Mock()
        p1.extract_text.return_value = "1페이지 정상 텍스트 추출 성공 내용입니다."
        p2 = Mock()
        p2.extract_text.side_effect = RuntimeError("손상된 2페이지 압축 스트림")
        mock_reader.pages = [p1, p2]
        mock_reader_cls.return_value = mock_reader

        # 2페이지 텍스트 실패 후 pypdfium2 OCR 시도 시에도 렌더링 예외 시뮬레이션
        with patch("pypdfium2.PdfDocument") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.__len__.return_value = 2
            mock_doc.__getitem__.side_effect = RuntimeError("렌더링 실패")
            mock_doc_cls.return_value = mock_doc

            text, status, err, details = extract_pdf_text(pdf_path, max_pages=5)
            # 1페이지 성공 내용 보존
            assert "1페이지 정상" in text
            # 일부 실패이므로 partial 상태
            assert status == "partial"
            assert details["pages"][0]["status"] == "success"
            assert details["pages"][1]["status"] in ("failed", "empty")


def test_download_cache_revalidation_and_ocr_content_hash_reuse(tmp_path):
    """다운로드 캐시 ETag 재검증과 파일 내용 해시 기반 OCR 텍스트 재사용 검증."""
    downloader = SafeDownloader(cache_dir=tmp_path / "cache")
    target_url = "http://safe.example.com/poster.jpg"

    with patch("core.extractor.downloader.is_safe_url", return_value=(True, "ok")):
        with patch("requests.get") as mock_get:
            # 1. 첫 다운로드: ETag 부여
            mock_resp1 = Mock()
            mock_resp1.status_code = 200
            mock_resp1.headers = {"Content-Length": "12", "ETag": '"v1"'}
            mock_resp1.iter_content.return_value = [b"poster-bytes"]
            mock_resp1.raise_for_status = Mock()
            mock_get.return_value = mock_resp1

            path1, status1, meta1 = downloader.download_file(target_url, validate_cache=True)
            assert status1 == "downloaded"
            assert path1.read_bytes() == b"poster-bytes"

            # 2. 재검증 다운로드: 304 Not Modified 수신 -> 캐시 유지
            mock_resp2 = Mock()
            mock_resp2.status_code = 304
            mock_resp2.headers = {"ETag": '"v1"'}
            mock_get.return_value = mock_resp2

            path2, status2, meta2 = downloader.download_file(target_url, validate_cache=True)
            assert status2 in ("cached", "not_modified")
            assert path1 == path2

    # 3. 파일 내용 해시 + 추출 설정 기반 OCR 재사용 검증
    img_path1 = tmp_path / "img1.png"
    img_path2 = tmp_path / "img2.png"
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    img.save(img_path1, "PNG")
    # 동일한 바이트 복사
    img_path2.write_bytes(img_path1.read_bytes())

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="추출된 OCR 텍스트 결과", stderr="")
        with patch("core.extractor.ocr.get_tesseract_binary", return_value="/usr/bin/tesseract"):
            # 첫 번째 이미지 파일 OCR
            text1, st1, err1 = extract_image_text(img_path1, lang="kor+eng", cache_dir=tmp_path / "ocr_cache")
            assert st1 == "success"
            assert mock_run.call_count == 1

            # 경로/이름이 다른 두 번째 이미지 파일(동일 바이트 내용) OCR 호출 시 subprocess 없이 캐시 재사용
            text2, st2, err2 = extract_image_text(img_path2, lang="kor+eng", cache_dir=tmp_path / "ocr_cache")
            assert st2 == "success"
            assert text1 == text2
            assert mock_run.call_count == 1, "동일 내용 이미지에 대해 OCR이 재호출되지 않고 캐시되어야 함"


def test_enrich_notices_uses_safe_downloader_for_detail_html(tmp_path):
    """enrich_notices.py가 상세 HTML 요청 시 SafeDownloader(SSRF 차단 등)를 거치는지 검증."""
    from scripts.enrich_notices import enrich_notices_file

    in_json = tmp_path / "test_input.json"
    out_json = tmp_path / "test_output.json"
    # 사설망 URL 공지
    in_json.write_text(json.dumps([{
        "id": "test-private",
        "title": "내부망 접근 시도 공지",
        "content": "내부망 접근 시도 공지",
        "source": "보안팀",
        "category": "보안",
        "date": "2026-09-01",
        "url": "http://127.0.0.1/admin",
        "content_status": "title_only",
    }], ensure_ascii=False), encoding="utf-8")

    # enrich_notices_file 실행 시 SSRF 방어가 동작하여 크래시 없이 title_only 보존
    enrich_notices_file(str(in_json), str(out_json), delay_sec=0)

    assert out_json.exists()
    out_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert len(out_data) == 1
    assert out_data[0]["content_status"] == "title_only"


# ── 7. Codex 재검토 4대 회귀 테스트 ───────────────────


def test_pipeline_revalidation_updates_when_url_content_changes(tmp_path):
    """동일 URL의 원격 이미지 내용/ETag가 바뀐 경우 파이프라인 결과도 갱신되는지 통합 검증."""
    downloader = SafeDownloader(cache_dir=tmp_path / "cache")
    enricher = NoticeEnricher(downloader=downloader)
    img_url = "http://safe.example.com/poster.jpg"

    notice = {
        "id": "notice-update-test",
        "title": "국가장학금 공지",
        "content": "국가장학금 공지",
        "source": "학생복지팀",
        "category": "장학",
        "date": "2026-08-12",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/1/artclView.do",
        "content_status": "title_only",
    }

    # 1. 초기 다운로드: v1 (마감일: 9.9)
    img1 = Image.new("RGB", (100, 50), color=(10, 20, 30))
    img1_buf = io.BytesIO()
    img1.save(img1_buf, "PNG")
    img1_bytes = img1_buf.getvalue()

    with patch("core.extractor.downloader.is_safe_url", return_value=(True, "ok")):
        with patch("requests.get") as mock_get:
            resp1 = Mock()
            resp1.status_code = 200
            resp1.headers = {"Content-Length": str(len(img1_bytes)), "ETag": '"v1"'}
            resp1.iter_content.return_value = [img1_bytes]
            resp1.raise_for_status = Mock()
            mock_get.return_value = resp1

            with patch("core.extractor.ocr.get_tesseract_binary", return_value="/usr/bin/tesseract"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = Mock(returncode=0, stdout="신청 기간: 2026.08.12 ~ 2026.09.09", stderr="")
                    res1 = enricher.enrich_notice(notice, image_urls=[img_url])
                    assert "2026.09.09" in res1["content"]

            # 2. 서버에서 내용 변경: v2 (연장 공지: 마감일 9.20으로 변경)
            img2 = Image.new("RGB", (100, 50), color=(50, 60, 70))
            img2_buf = io.BytesIO()
            img2.save(img2_buf, "PNG")
            img2_bytes = img2_buf.getvalue()

            resp2 = Mock()
            resp2.status_code = 200
            resp2.headers = {"Content-Length": str(len(img2_bytes)), "ETag": '"v2"'}
            resp2.iter_content.return_value = [img2_bytes]
            resp2.raise_for_status = Mock()
            mock_get.return_value = resp2

            with patch("core.extractor.ocr.get_tesseract_binary", return_value="/usr/bin/tesseract"):
                with patch("subprocess.run") as mock_run2:
                    mock_run2.return_value = Mock(returncode=0, stdout="신청 기간 연장: 2026.08.12 ~ 2026.09.20", stderr="")
                    res2 = enricher.enrich_notice(notice, image_urls=[img_url])
                    # 캐시 재검증을 통해 새로운 9.20 내용으로 파이프라인 결과가 갱신되어야 함!
                    assert "2026.09.20" in res2["content"]


def test_ocr_transient_failure_not_cached_and_retries_after_fix(tmp_path):
    """OCR의 failed 등 일시적 실패 결과는 캐시하지 않고, 복구 후 정상 재시도되는지 검증."""
    ocr_cache = tmp_path / "ocr_cache"
    img_path = tmp_path / "fail_then_ok.png"
    Image.new("RGB", (100, 50), color=(111, 222, 123)).save(img_path)

    with patch("core.extractor.ocr.get_tesseract_binary", return_value="/usr/bin/tesseract"):
        with patch("subprocess.run") as mock_run:
            # 1. 언어팩 누락 또는 서브프로세스 일시 실패
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error: kor language pack not found")
            text1, st1, err1 = extract_image_text(img_path, cache_dir=ocr_cache)
            assert st1 == "failed"
            assert "kor language pack" in (err1 or "")

            # 실패 결과 파일이 디스크에 영구 캐시로 저장되지 않았거나, 있더라도 무시되어야 함
            # 2. 환경 복구 후 정상 재시도
            mock_run.reset_mock()
            mock_run.return_value = Mock(returncode=0, stdout="정상 복구된 국가장학금 OCR 텍스트", stderr="")
            text2, st2, err2 = extract_image_text(img_path, cache_dir=ocr_cache)

            # 이전 실패 캐시를 재사용하지 않고 실제로 서브프로세스를 다시 실행하여 성공해야 함!
            assert mock_run.call_count == 1
            assert st2 == "success"
            assert "정상 복구된" in text2


def test_pdf_status_aggregates_ocr_tool_missing_and_fallback_not_hidden(tmp_path):
    """PDF 상태 집계에서 ocr_tool_missing 및 폴백 발생 시 정보가 은폐되지 않고 partial로 보고되는지 검증."""
    pdf_path = tmp_path / "tool_missing.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        # 1페이지: 정상 텍스트
        p1 = Mock()
        p1.extract_text.return_value = "1페이지는 텍스트 레이어가 있는 정상 내용입니다."
        # 2페이지: 텍스트가 극히 적음 (5자) -> OCR 시도하지만 Tesseract 없음
        p2 = Mock()
        p2.extract_text.return_value = "제목만"
        mock_reader.pages = [p1, p2]
        mock_reader_cls.return_value = mock_reader

        with patch("pypdfium2.PdfDocument") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.__len__.return_value = 2
            mock_render = Mock()
            mock_render.render.return_value.to_pil.return_value = Mock()
            mock_doc.__getitem__.return_value = mock_render
            mock_doc_cls.return_value = mock_doc

            with patch("core.extractor.ocr.get_tesseract_binary", return_value=None):
                # Tesseract 바이너리가 없는 상황
                text, status, err, details = extract_pdf_text(pdf_path, max_pages=5)

                # 1페이지 텍스트는 보존되어야 함
                assert "1페이지는 텍스트" in text
                # 2페이지의 OCR 실패 정보가 success로 은폐되지 않아야 함
                assert details["pages"][1]["status"] in ("ocr_tool_missing", "partial", "fallback")
                # 전체 상태는 일부 성공이므로 partial이어야 함 (전체 성공 success로 보고되면 안 됨)
                assert status == "partial"


def test_scholarship_deadline_matching_rejects_swapped_dates():
    """신청 기간과 가구원 동의 기간을 문맥에 바인딩하여 검사하며, 누락 및 마감일 전도를 검증."""
    from scripts.verify_real_extraction import validate_scholarship_deadlines

    # 케이스 1: 신청 기간만 있음 -> 실패
    apply_only_text = (
        "2026년 2학기 국가장학금 2차 신청 안내\n"
        "신청 기간: '26.8.12.(수) 09시 ~ 9.9.(수) 18시\n"
        "대상: 재학생 및 신입생"
    )
    ok_apply_only, reason_apply_only = validate_scholarship_deadlines(apply_only_text)
    assert ok_apply_only is False, "동의 기간이 누락되었는데 통과하면 안 됨"
    assert "동의" in reason_apply_only or "누락" in reason_apply_only

    # 케이스 2: 동의 기간만 있음 -> 실패
    consent_only_text = (
        "2026년 2학기 국가장학금 2차 안내\n"
        "서류제출 및 가구원 동의: '26.8.12.(수) 09시 ~ 9.16.(수) 18시\n"
        "대상: 재학생 및 신입생"
    )
    ok_consent_only, reason_consent_only = validate_scholarship_deadlines(consent_only_text)
    assert ok_consent_only is False, "신청 기간이 누락되었는데 통과하면 안 됨"
    assert "신청" in reason_consent_only or "누락" in reason_consent_only

    # 케이스 3: 두 기간 모두 정상 -> 통과
    valid_text = (
        "2026년 2학기 국가장학금 2차 신청 안내\n"
        "신청 기간: '26.8.12.(수) 09시 ~ 9.9.(수) 18시\n"
        "서류제출 및 가구원 동의: '26.8.12.(수) 09시 ~ 9.16.(수) 18시\n"
        "대상: 재학생 및 신입생"
    )
    ok, reason = validate_scholarship_deadlines(valid_text)
    assert ok is True, f"정상 텍스트가 거부됨: {reason}"

    # 케이스 4: 두 마감일 뒤바뀜 -> 실패
    swapped_text = (
        "2026년 2학기 국가장학금 2차 신청 안내\n"
        "신청 기간: '26.8.12.(수) 09시 ~ 9.16.(수) 18시\n"
        "서류제출 및 가구원 동의: '26.8.12.(수) 09시 ~ 9.9.(수) 18시\n"
        "대상: 재학생 및 신입생"
    )
    ok_swapped, reason_swapped = validate_scholarship_deadlines(swapped_text)
    assert ok_swapped is False, "마감일이 뒤바뀐 텍스트가 통과되면 안 됨!"
    assert "신청" in reason_swapped or "동의" in reason_swapped or "마감일" in reason_swapped


