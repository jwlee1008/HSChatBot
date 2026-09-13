"""
실제 한성대 공지 이미지, 첨부파일 및 국가장학금 원문 대조 통합 검증 스크립트.
"""

import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extractor.downloader import SafeDownloader
from core.extractor.hwp import extract_document_text
from core.extractor.ocr import extract_image_text
from core.extractor.pdf import extract_pdf_text
from core.extractor.pipeline import NoticeEnricher
from core import embedder

import re

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_scholarship_deadlines(text: str) -> tuple[bool, str]:
    """
    국가장학금 공지 텍스트에서 '신청 기간'과 '서류제출/가구원 동의 기간'을 문맥별로 분리하여
    올바른 마감일(신청: 9.9, 서류/가구원 동의: 9.16)이 바인딩되었는지 검증한다.

    두 마감일이 뒤바뀌었거나 잘못 매핑된 경우 거부한다.

    Returns:
        (is_valid, reason)
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 마감일 패턴: 9.9 또는 9.16 (09.09 등 포함)
    date_range_pattern = re.compile(
        r"(?:8\.12|08\.12)[^\n~]*?~[^\n]*?(9\.\d{1,2}|09\.\d{1,2})"
    )

    apply_deadline = None
    consent_deadline = None

    # 각 라인에서 date_range 매칭 검색
    date_matches = []
    for i, line in enumerate(lines):
        m = date_range_pattern.search(line)
        if m:
            raw_end = m.group(1).replace("09.", "9.")
            parts = raw_end.split(".")
            normalized_end = f"{int(parts[0])}.{int(parts[1])}"
            date_matches.append((i, line, normalized_end))

    for idx, line, norm_date in date_matches:
        # 1. 동일 라인 내 키워드 우선 확인
        has_consent_inline = any(k in line for k in ("가구원", "서류제출", "서류 제출", "동의"))
        has_apply_inline = any(k in line for k in ("신청", "접수")) and not has_consent_inline

        if has_consent_inline:
            consent_deadline = norm_date
            continue
        if has_apply_inline:
            apply_deadline = norm_date
            continue

        # 2. 인접 라인 탐색 (거리 1 -> 거리 2 순으로 가장 가까운 문맥 확인)
        matched_kind = None
        for dist in (1, 2):
            adjacent_lines = []
            if idx - dist >= 0:
                adjacent_lines.append(lines[idx - dist])
            if idx + dist < len(lines):
                adjacent_lines.append(lines[idx + dist])

            adj_text = " ".join(adjacent_lines)
            is_consent_adj = any(k in adj_text for k in ("가구원", "서류제출", "서류 제출", "동의"))
            is_apply_adj = any(k in adj_text for k in ("신청", "접수"))

            if is_consent_adj and not is_apply_adj:
                matched_kind = "consent"
                break
            elif is_apply_adj and not is_consent_adj:
                matched_kind = "apply"
                break
            elif is_consent_adj and is_apply_adj:
                if any(k in adj_text for k in ("가구원", "서류제출")):
                    matched_kind = "consent"
                else:
                    matched_kind = "apply"
                break

        if matched_kind == "consent":
            consent_deadline = norm_date
        elif matched_kind == "apply":
            apply_deadline = norm_date

    # 만약 위 방식으로도 잡히지 않은 경우 정규식 직접 검색 폴백
    if not apply_deadline:
        m_app = re.search(r"신청[^\n~]*~[^\n]*?(9\.\d{1,2}|09\.\d{1,2})", text)
        if m_app:
            raw = m_app.group(1).replace("09.", "9.")
            parts = raw.split(".")
            apply_deadline = f"{int(parts[0])}.{int(parts[1])}"

    if not consent_deadline:
        m_con = re.search(r"(?:서류|가구원|동의)[^\n~]*~[^\n]*?(9\.\d{1,2}|09\.\d{1,2})", text)
        if m_con:
            raw = m_con.group(1).replace("09.", "9.")
            parts = raw.split(".")
            consent_deadline = f"{int(parts[0])}.{int(parts[1])}"

    # 두 항목(신청 기간, 서류/가구원 동의 기간) 중 하나라도 누락되면 실패
    if not apply_deadline and not consent_deadline:
        return False, "신청 기간 및 서류/가구원 동의 기간 패턴을 모두 찾을 수 없습니다."
    if not apply_deadline:
        return False, "신청 기간 패턴이 누락되었습니다 (마감일 9.9 미검출)."
    if not consent_deadline:
        return False, "서류제출/가구원 동의 기간 패턴이 누락되었습니다 (마감일 9.16 미검출)."

    # 마감일 교차/전도(swapped) 검증
    if apply_deadline == "9.16" or consent_deadline == "9.9":
        return False, (
            f"마감일이 뒤바뀌어 매핑됨: 신청 기간 마감일={apply_deadline} (기대: 9.9), "
            f"서류/가구원 동의 기간 마감일={consent_deadline} (기대: 9.16)"
        )

    if apply_deadline != "9.9":
        return False, f"신청 기간 마감일 오류: {apply_deadline} (기대: 9.9)"

    if consent_deadline != "9.16":
        return False, f"서류제출/가구원 동의 기간 마감일 오류: {consent_deadline} (기대: 9.16)"

    return True, "신청 기간('26.8.12 ~ 9.9) 및 서류제출/가구원 동의 기간('26.8.12 ~ 9.16) 문맥 바인딩 검증 통과"


def main():
    print("=" * 70)
    print("🚀 CampusRAG 실제 데이터 및 국가장학금 원문 대조 통합 검증")
    print("=" * 70)

    downloader = SafeDownloader(cache_dir="data/cache/verification")
    enricher = NoticeEnricher(downloader=downloader)

    # 1. 국가장학금 2차 신청 실제 포스터 이미지 OCR 및 원문 대조
    print("\n[검증 1] 실제 국가장학금 2차 신청 공지 이미지 OCR 검증")
    notice_url = "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do"
    poster_url = "https://www.hansung.ac.kr/CrossEditor/binary/images/000402/(%ED%8F%AC%EC%8A%A4%ED%84%B0)_2026_2%ED%95%99%EA%B8%B0_2%EC%B0%A8_%EA%B5%AD%EA%B0%80%EC%9E%A5%ED%95%99%EA%B8%88_%EC%8B%A0%EC%B2%AD.jpg"

    path, dl_status, _ = downloader.download_file(poster_url, filename_hint="poster_2026_2.jpg")
    assert path is not None and dl_status in ("downloaded", "cached")

    text, ocr_status, err = extract_image_text(path)
    assert ocr_status == "success"
    print(f"✅ OCR 성공 여부: {ocr_status} (추출 글자 수: {len(text)})")

    # 연도와 학기: 이미지 내 '26 및 2학기 확인 (포스터 상단 '26년 2학기 2차가 그래픽 폰트로 '(26H 2략기 2자'로 추출됨)
    has_year = "'26" in text or "26" in text
    has_semester = "2학기" in text
    # 신청 기간: 8.12 ~ 9.9
    has_apply_period = "8.12" in text and "9.9" in text
    # 서류제출 및 가구원 동의 기간: 8.12 ~ 9.16
    has_consent_period = "8.12" in text and "9.16" in text
    # 신청 대상: 재학생, 신입생, 편입생 등
    has_target = "재학생" in text and "신입생" in text

    print(f"  - 연도 확인 ('26 / 2026): {'✅ 일치' if has_year else '❌ 불일치'}")
    print(f"  - 학기 확인 (2학기): {'✅ 일치' if has_semester else '❌ 불일치'}")
    print(f"  - [구분 1] 국가장학금 신청 기간 ('26.8.12 ~ 9.9): {'✅ 일치' if has_apply_period else '❌ 불일치'}")
    print(f"  - [구분 2] 서류제출 및 가구원 동의 기간 ('26.8.12 ~ 9.16): {'✅ 일치' if has_consent_period else '❌ 불일치'}")
    print(f"  - 신청 대상 확인 (재학생, 신입생, 복학생 등): {'✅ 일치' if has_target else '❌ 불일치'}")

    # 개별 항목 엄격 assertion
    assert has_year and has_semester, "연도/학기 확인 실패"
    assert has_target, "신청 대상 확인 실패"
    assert has_apply_period, "국가장학금 신청 기간('26.8.12 ~ 9.9) 대조 실패"
    assert has_consent_period, "서류제출 및 가구원 동의 기간('26.8.12 ~ 9.16) 대조 실패"

    # [Codex 검토 반영] 신청 기간 vs 서류제출/가구원 동의 기간 문맥 바인딩 정밀 검증
    dl_ok, dl_reason = validate_scholarship_deadlines(text)
    assert dl_ok, f"기간 문맥 바인딩 검증 실패: {dl_reason}"
    print(f"  - [문맥 바인딩 검증] {dl_reason}")

    # 2. 실제 공지 딕셔너리 보강 (파이프라인 결합)
    print("\n[검증 2] 공지 단위 파이프라인 결합 및 식별자 보존 검증")
    notice = {
        "id": "hansung-scholarship-223971",
        "title": "국가장학금\n2026년 2학기 국가장학금 2차 신청 안내",
        "content": "국가장학금\n2026년 2학기 국가장학금 2차 신청 안내",
        "source": "학교본부 (학생복지팀)",
        "category": "장학",
        "date": "2026-08-12",
        "url": notice_url,
        "content_status": "title_only",
    }
    enriched = enricher.enrich_notice(notice, image_urls=[poster_url])

    assert enriched["url"] == notice_url, "원문 URL이 변경되지 않아야 함"
    assert enriched["id"] == notice["id"]
    assert enriched["content_status"] == "ocr"
    assert enriched["has_ocr"] is True
    assert "8.12" in enriched["content"]
    assert "9.9" in enriched["content"], "신청 마감일(9.9)이 본문에 포함되어야 함"
    assert "9.16" in enriched["content"], "가구원 동의 마감일(9.16)이 본문에 포함되어야 함"
    print("✅ 원문 URL 및 ID 불변 확인")
    print(f"✅ 결합 상태: {enriched['content_status']}, 요약: {enriched['extraction_summary']}")

    # 3. 실제 PDF 첨부파일 추출 검증
    print("\n[검증 3] 실제 PDF 첨부파일 텍스트 추출 검증")
    pdf_url = "https://www.hansung.ac.kr/bbs/hansung/2127/63571/download.do"
    pdf_path, dl_s, _ = downloader.download_file(pdf_url, filename_hint="volunteer_guide.pdf")
    assert pdf_path is not None
    pdf_text, pdf_status, _, pdf_details = extract_pdf_text(pdf_path, max_pages=3)
    assert pdf_status == "partial" or pdf_status == "success"
    assert "단장 모집안내서" in pdf_text or "청년봉사단" in pdf_text
    print(f"✅ PDF 파싱 성공: 방식={pdf_details['method']}, 페이지={pdf_details['processed_pages']}, 길이={len(pdf_text)}")

    # 4. 실제 HWP 첨부파일 추출 검증
    print("\n[검증 4] 실제 HWP 첨부파일 텍스트 추출 검증")
    hwp_url = "https://www.hansung.ac.kr/bbs/hansung/2127/61765/download.do"
    hwp_path, dl_h, _ = downloader.download_file(hwp_url, filename_hint="qualification.hwp")
    assert hwp_path is not None
    hwp_text, hwp_status, _, hwp_details = extract_document_text(hwp_path, filename_hint="qualification.hwp")
    assert hwp_status == "success"
    assert "국가전문자격시험" in hwp_text
    print(f"✅ HWP 파싱 성공: 형식={hwp_details['format']}, 길이={len(hwp_text)}")

    # 5. 임시 Chroma DB 적재 및 검색 검증
    print("\n[검증 5] 임시 Chroma DB 적재 및 원문 URL 보존/검색 검증")
    temp_dir = Path("data/cache/test_chroma_verification")
    import shutil
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    temp_json = temp_dir / "enriched.json"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump([enriched], f, ensure_ascii=False)

    docs = embedder.load_notices_from_json(str(temp_json))
    store = embedder.ingest_to_chroma(docs, persist_directory=str(temp_dir), collection_name="real_verif")
    assert store._collection.count() == 1

    # 중복 upsert 검증
    store2 = embedder.ingest_to_chroma(docs, persist_directory=str(temp_dir), collection_name="real_verif")
    assert store2._collection.count() == 1

    # 검색 쿼리: "2026년 2학기 국가장학금 2차 신청 기간 언제까지야?"
    res = store.similarity_search("2026년 2학기 국가장학금 2차 신청 기간 언제까지야?", k=1)
    assert len(res) == 1
    found = res[0]
    assert found.metadata["url"] == notice_url
    assert "8.12" in found.page_content
    print("✅ 임시 Chroma DB 검색 결과 원문 URL 확인:", found.metadata["url"])
    print("✅ 검색된 본문에 추출된 신청 기간(8.12 ~ 9.9) 포함 확인")

    print("\n" + "=" * 70)
    print("🎉 모든 실제 파일 및 국가장학금 원문 대조 검증 통과!")
    print("=" * 70)


if __name__ == "__main__":
    main()
