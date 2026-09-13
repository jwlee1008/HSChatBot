"""
PDF 텍스트 추출 및 스캔 PDF 페이지별 렌더링 OCR 모듈.

페이지별로 텍스트 레이어를 확인하여:
- 텍스트가 충분한 페이지: pypdf 직접 추출
- 텍스트가 없거나 부족한 페이지: pypdfium2 렌더링 후 Tesseract OCR 개별 적용
- 페이지별 예외 격리: 개별 페이지 실패 시에도 성공한 페이지 보존 및 partial 상태 기록
"""

import logging
from pathlib import Path
from core.extractor.ocr import extract_image_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 10
MIN_TEXT_PER_PAGE = 20  # 페이지당 이 글자 수 미만이면 스캔 페이지로 판단


def extract_pdf_text(
    pdf_path: Path | str,
    max_pages: int = DEFAULT_MAX_PAGES,
    force_ocr: bool = False,
) -> tuple[str, str, str | None, dict]:
    """
    PDF 파일에서 페이지별로 텍스트를 추출한다.

    Returns:
        (extracted_text, status, error, details)
        status: "success", "partial", "empty", "failed"
    """
    path = Path(pdf_path)
    if not path.exists() or path.stat().st_size == 0:
        return "", "failed", f"PDF 파일이 없거나 비어있습니다: {path}", {}

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
    except Exception as e:
        logger.warning("pypdf 로드 실패 (%s): %s", path, e)
        return "", "failed", f"PDF 로드 실패: {e}", {"total_pages": 0, "processed_pages": 0}

    if total_pages == 0:
        return "", "empty", "PDF에 페이지가 없습니다.", {"total_pages": 0, "processed_pages": 0}

    pages_to_process = min(total_pages, max_pages)
    formatted_chunks = []
    page_details = []

    # pypdfium2 문서는 필요 시 지연 오픈
    pdfium_doc = None

    def get_pdfium_doc():
        nonlocal pdfium_doc
        if pdfium_doc is None:
            import pypdfium2 as pdfium
            pdfium_doc = pdfium.PdfDocument(str(path))
        return pdfium_doc

    try:
        for idx in range(pages_to_process):
            page_num = idx + 1
            extracted_text = ""
            text_extract_error = None

            # 1. pypdf 텍스트 레이어 추출 시도 (force_ocr이 아닐 때)
            if not force_ocr:
                try:
                    page = reader.pages[idx]
                    extracted_text = (page.extract_text() or "").strip()
                except Exception as e:
                    logger.warning("PDF 페이지 %d 텍스트 레이어 추출 실패: %s", page_num, e)
                    text_extract_error = str(e)
                    extracted_text = ""

            # 2. 페이지별 판단: 텍스트가 충분한 경우 -> 텍스트 레이어 채택
            if len(extracted_text) >= MIN_TEXT_PER_PAGE and not force_ocr:
                formatted_chunks.append(f"[PDF 페이지 {page_num}]\n{extracted_text}")
                page_details.append({
                    "page": page_num,
                    "method": "pdf_text",
                    "status": "success",
                    "length": len(extracted_text),
                })
                continue

            # 3. 텍스트가 부족하거나 없는 경우 -> 해당 페이지만 개별 OCR 시도
            logger.info("PDF 페이지 %d 텍스트 부족 (%d자) -> 페이지별 OCR 시도: %s", page_num, len(extracted_text), path.name)
            ocr_text = ""
            page_img_path = path.parent / f"{path.stem}_p{page_num}.png"

            try:
                doc = get_pdfium_doc()
                page = doc[idx]
                pil_image = page.render(scale=2.0).to_pil()
                pil_image.save(page_img_path)

                res_text, ocr_st, ocr_err = extract_image_text(page_img_path)
                if ocr_st == "success" and res_text.strip():
                    ocr_text = res_text.strip()
                    formatted_chunks.append(f"[PDF 페이지 {page_num} (OCR)]\n{ocr_text}")
                    page_details.append({
                        "page": page_num,
                        "method": "pdf_ocr",
                        "status": "success",
                        "length": len(ocr_text),
                    })
                else:
                    # OCR 결과가 비었거나 실패
                    # 이전에 약간 추출된 텍스트라도 있으면 폴백 보존하되 실패 정보 은폐 방지 (status: partial)
                    if extracted_text:
                        formatted_chunks.append(f"[PDF 페이지 {page_num}]\n{extracted_text}")
                        page_details.append({
                            "page": page_num,
                            "method": "pdf_text",
                            "status": "partial",
                            "length": len(extracted_text),
                            "note": f"OCR 실패 후 텍스트 폴백 (OCR 사유: {ocr_err or ocr_st})",
                            "error": ocr_err or f"OCR 처리 불가 ({ocr_st})",
                        })
                    else:
                        page_details.append({
                            "page": page_num,
                            "method": "pdf_ocr",
                            "status": ocr_st if ocr_st != "success" else "empty",
                            "error": ocr_err,
                            "length": 0,
                        })
            except Exception as e:
                logger.warning("PDF 페이지 %d 렌더링/OCR 실패: %s", page_num, e)
                if extracted_text:
                    formatted_chunks.append(f"[PDF 페이지 {page_num}]\n{extracted_text}")
                    page_details.append({
                        "page": page_num,
                        "method": "pdf_text",
                        "status": "partial",
                        "length": len(extracted_text),
                        "note": f"렌더링 예외 후 텍스트 폴백 ({e})",
                        "error": str(e),
                    })
                else:
                    page_details.append({
                        "page": page_num,
                        "method": "pdf_ocr",
                        "status": "failed",
                        "error": str(e),
                        "length": 0,
                    })
            finally:
                if page_img_path.exists():
                    try:
                        page_img_path.unlink()
                    except Exception:
                        pass

    finally:
        if pdfium_doc is not None:
            try:
                pdfium_doc.close()
            except Exception:
                pass

    full_text = "\n\n".join(formatted_chunks).strip()
    # 상태 집계: ocr_tool_missing 등 모든 처리 불가 상태 및 partial 반영
    # 일부 내용만 확보되면 partial, 전체 처리 불가면 failed로 보고하고 성공한 텍스트는 보존
    non_success_pages = [p for p in page_details if p.get("status") not in ("success", "empty")]
    has_failed_or_missing = any(p.get("status") in ("failed", "ocr_tool_missing") for p in page_details)

    if not full_text:
        if has_failed_or_missing:
            first_err = (non_success_pages[0].get("error") if non_success_pages else None) or "전체 페이지 처리 불가"
            status = "failed"
            error_msg = f"페이지 처리 불가: {first_err}"
        else:
            status = "empty"
            error_msg = None
    elif non_success_pages or total_pages > max_pages:
        status = "partial"
        error_msg = None
    else:
        status = "success"
        error_msg = None

    methods = {p.get("method") for p in page_details if p.get("method")}
    if len(methods) == 1:
        overall_method = methods.pop()
    elif "pdf_ocr" in methods and "pdf_text" in methods:
        overall_method = "mixed"
    else:
        overall_method = "page_by_page"

    return full_text, status, error_msg, {
        "method": overall_method,
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "pages": page_details,
    }
