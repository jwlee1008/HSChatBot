"""
scripts/build_unified_dataset.py의 parse_iso_datetime 결함 재현 및 회귀 테스트 슈트.

검증 항목:
1. 정상 ISO 날짜 (2026-09-23) -> UTC datetime 반환
2. 점 구분 날짜 (2026.09.23) -> NameError 없이 정상 UTC datetime 반환
3. 유효하지 않은 문자열 ('invalid') -> NameError 없이 None 반환
4. None, 빈 문자열, 공백 문자열 -> None 반환
5. 존재하지 않는 달력 날짜 (2026-02-30, 2026.02.29, 2026-13-01 등) -> None 반환
6. ISO 시간대 지원 (+09:00, Z) -> UTC 변환 일관성
7. 점 구분 날짜와 선택 시각 (2026.09.23 15:30, 2026.09.23 15:30:45, 2026.09.23T15:30:45)
8. 부분 일치 오인식 차단 (2026.09.23garbage, 2026-09-23garbage, prefix2026.09.23) -> None 반환
9. 문서 충돌 해결(resolve_document_conflict) 시 날짜 파싱 오류로 인한 통합 중단 방지
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_unified_dataset import parse_iso_datetime, resolve_document_conflict


def test_standard_iso_date_returns_utc():
    """정상 ISO 날짜('2026-09-23')가 UTC datetime으로 반환되는지 확인."""
    dt = parse_iso_datetime("2026-09-23")
    assert dt is not None
    assert dt == datetime(2026, 9, 23, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.tzinfo == timezone.utc


def test_dotted_date_parsing_no_name_error():
    """
    결함 재현: 점 구분 날짜('2026.09.23') 파싱 시
    NameError(name 're' is not defined)가 발생하지 않고 정상 UTC datetime으로 파싱되는지 검증.
    """
    dt = parse_iso_datetime("2026.09.23")
    assert dt is not None
    assert dt == datetime(2026, 9, 23, 0, 0, 0, tzinfo=timezone.utc)


def test_invalid_string_returns_none_without_exception():
    """
    결함 재현: 잘못된 문자열('invalid') 입력 시
    NameError 없이 예외 없이 None을 반환하는지 검증.
    """
    dt = parse_iso_datetime("invalid")
    assert dt is None


@pytest.mark.parametrize("empty_val", [None, "", "   ", "\t\n"])
def test_empty_or_none_returns_none(empty_val):
    """None, 빈 문자열, 공백 문자열 입력 시 None 반환 검증."""
    assert parse_iso_datetime(empty_val) is None


@pytest.mark.parametrize("invalid_date", [
    "2026-02-30",        # 2월 30일 (존재하지 않음)
    "2026.02.29",        # 2026년은 윤년이 아님 (2월 29일 없음)
    "2026-13-01",        # 13월
    "2026.00.10",        # 0월
    "2026-04-31",        # 4월은 30일까지
    "2026.04.31 12:00",  # 존재하지 않는 날짜에 시각 포함
])
def test_nonexistent_dates_return_none(invalid_date):
    """달력상 존재하지 않는 날짜 입력 시 ValueError 예외 없이 None을 반환하는지 검증."""
    assert parse_iso_datetime(invalid_date) is None


def test_iso_timezone_handling():
    """
    ISO 시간대(+09:00, Z)가 정상적으로 인식되어 UTC로 올바르게 변환되는지 검증:
    2026-09-23T15:00:00+09:00 -> 2026-09-23 06:00:00 UTC
    2026-09-23T15:00:00Z -> 2026-09-23 15:00:00 UTC
    """
    dt_kst = parse_iso_datetime("2026-09-23T15:00:00+09:00")
    assert dt_kst is not None
    assert dt_kst == datetime(2026, 9, 23, 6, 0, 0, tzinfo=timezone.utc)

    dt_utc = parse_iso_datetime("2026-09-23T15:00:00Z")
    assert dt_utc is not None
    assert dt_utc == datetime(2026, 9, 23, 15, 0, 0, tzinfo=timezone.utc)

    # 점 구분 날짜의 타임존 지원 검증
    dt_dot_kst = parse_iso_datetime("2026.09.23 15:00:00+09:00")
    assert dt_dot_kst is not None
    assert dt_dot_kst == datetime(2026, 9, 23, 6, 0, 0, tzinfo=timezone.utc)

    dt_dot_z = parse_iso_datetime("2026.09.23T15:00:00Z")
    assert dt_dot_z is not None
    assert dt_dot_z == datetime(2026, 9, 23, 15, 0, 0, tzinfo=timezone.utc)


def test_dotted_date_with_optional_time():
    """점 구분 날짜와 선택적 시각(HH:MM, HH:MM:SS) 파싱 검증."""
    # 시:분
    dt_hm = parse_iso_datetime("2026.09.23 14:30")
    assert dt_hm is not None
    assert dt_hm == datetime(2026, 9, 23, 14, 30, 0, tzinfo=timezone.utc)

    # 시:분:초
    dt_hms = parse_iso_datetime("2026.09.23 14:30:45")
    assert dt_hms is not None
    assert dt_hms == datetime(2026, 9, 23, 14, 30, 45, tzinfo=timezone.utc)

    # 'T' 구분자
    dt_t = parse_iso_datetime("2026.09.23T14:30:45")
    assert dt_t is not None
    assert dt_t == datetime(2026, 9, 23, 14, 30, 45, tzinfo=timezone.utc)


def test_basic_iso_format_accepted():
    """ISO 8601 기본 형식('20260923')이 UTC datetime으로 정상 파싱되는지 검증 (호환성 유지)."""
    dt = parse_iso_datetime("20260923")
    assert dt is not None
    assert dt == datetime(2026, 9, 23, 0, 0, 0, tzinfo=timezone.utc)


def test_iso_timezone_without_colon_accepted():
    """콜론 없는 시간대 오프셋(+0900)이 정상 인식되어 UTC로 변환되는지 검증 (호환성 유지)."""
    dt = parse_iso_datetime("2026-09-23T15:00:00+0900")
    assert dt is not None
    assert dt == datetime(2026, 9, 23, 6, 0, 0, tzinfo=timezone.utc)

    dt_dot = parse_iso_datetime("2026.09.23 15:00:00+0900")
    assert dt_dot is not None
    assert dt_dot == datetime(2026, 9, 23, 6, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("invalid_tz_input", [
    "2026-09-23T15:00:00+09:99",   # 분 오프셋 99 (>59)
    "2026-09-23T15:00:00-00:60",   # 분 오프셋 60
    "2026-09-23T15:00:00+24:00",   # 시 오프셋 24 (>23)
    "2026.09.23 15:00:00+09:99",   # 점 구분 날짜의 잘못된 분 오프셋
    "2026-09-23T15:00:00+2500",    # 콜론 없는 비정상 시 오프셋
])
def test_invalid_timezone_offsets_rejected(invalid_tz_input):
    """잘못된 시간대 오프셋 분/시를 가진 입력이 정상화되지 않고 반드시 None을 반환해야 함."""
    assert parse_iso_datetime(invalid_tz_input) is None


@pytest.mark.parametrize("mixed_input", [
    "2026-09.23",
    "2026.09-23",
    "2026-09.23 15:00:00",
    "2026.09-23T15:00:00",
])
def test_mixed_delimiters_rejected(mixed_input):
    """하이픈과 점이 섞인 혼합 구분자 입력은 지원 형식이 아니므로 거부(None)되어야 함."""
    assert parse_iso_datetime(mixed_input) is None


@pytest.mark.parametrize("garbage_input", [
    "2026.09.23garbage",
    "2026-09-23garbage",
    "2026.09.23 14:30extra",
    "prefix2026.09.23",
    "2026.09.23-text",
    "2026/09/23",
])
def test_partial_match_garbage_rejected(garbage_input):
    """
    정규식 부분 일치 취약점 방지:
    '2026.09.23garbage'처럼 유효 날짜 뒤에 부가 문자열이 붙은 잘못된 입력이
    정상 날짜로 오인식되지 않고 반드시 None을 반환해야 한다.
    """
    assert parse_iso_datetime(garbage_input) is None


def test_document_conflict_does_not_crash_on_dotted_or_invalid_date():
    """
    문서 통합 시 기존/신규 문서에 점 구분 날짜나 잘못된 날짜 문자열이 포함되어 있어도
    resolve_document_conflict가 NameError나 예외로 중단되지 않고
    결정적으로 해결되는지 검증.
    """
    doc_a = {
        "id": "notice-01",
        "title": "공지 A",
        "content": "공지 내용 A",
        "content_status": "text",
        "date": "2026.09.23",  # 점 구분 날짜
        "source_updated_at": "invalid_date_str",  # 유효하지 않은 날짜
        "last_checked_at": "2026-09-23T10:00:00+09:00",
    }
    doc_b = {
        "id": "notice-01",
        "title": "공지 A",
        "content": "공지 내용 A (수정)",
        "content_status": "text",
        "date": "2026-09-24",
        "source_updated_at": None,
        "last_checked_at": "2026-09-24T10:00:00+09:00",
    }

    # NameError 없이 정상적으로 비교 완료되어야 함
    chosen, chosen_source, reason = resolve_document_conflict(
        existing=doc_a,
        new_doc=doc_b,
        existing_source="source_a",
        new_source="source_b",
    )
    assert chosen is doc_b
    assert chosen_source == "source_b"
    assert "date" in reason


def test_schedule_extraction_fixture_integrity():
    """
    tests/fixtures/schedule_extraction_cases.json 유효성 및 정합성 검증:
    1. 유효한 JSON 구문 및 메타데이터(기준 시각, Asia/Seoul 시간대) 고정 확인
    2. 최소 20개 이상의 사례 확보
    3. 정책 검증: 모든 후보 일정은 캘린더 저장 전 사용자 확인 필수(requires_user_confirmation: true)
       (정보의 모호성 여부 is_ambiguous와 저장 전 사용자 확인은 명확히 분리)
    4. 후보가 0건인 안내문(sched-17)의 경우 requires_user_confirmation: false 허용
    5. 모호한 자정 시각(sched-20)은 임의의 23:59:59 타임스탬프를 부여하지 않고 end_date: null 유지 및 해석 선택지 제공
    6. 원문 발췌(source_quote)가 원본 본문(input_text)의 정확한 부분 문자열인지 전수 검증
    7. 취소 공지 사례(sched-23) 존재 및 자동 삭제 방지(사용자 확인 필수) 확인
    """
    import json

    fixture_path = ROOT / "tests" / "fixtures" / "schedule_extraction_cases.json"
    assert fixture_path.exists(), f"Fixture file not found at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 메타데이터 검증
    meta = data.get("metadata", {})
    assert meta.get("timezone") == "Asia/Seoul"
    assert meta.get("reference_time") == "2026-09-23T15:00:00+09:00"

    # 2. 최소 20사례 검증
    cases = data.get("cases", [])
    assert len(cases) >= 20, f"Expected at least 20 cases, found {len(cases)}"

    # 3. 개별 사례 정합성 검증
    case_ids = set()
    has_cancellation_case = False

    for c in cases:
        cid = c["id"]
        assert cid not in case_ids, f"Duplicate case ID: {cid}"
        case_ids.add(cid)

        assert "category" in c and c["category"]
        assert "input_text" in c and c["input_text"]
        input_text = c["input_text"]
        assert isinstance(c["expected_candidate_count"], int)
        assert c["expected_candidate_count"] >= 0

        candidates = c.get("candidates", [])
        assert len(candidates) == c["expected_candidate_count"], (
            f"Case {cid}: candidates count {len(candidates)} != expected {c['expected_candidate_count']}"
        )

        # 사용자 확인 정책 검증
        if c["expected_candidate_count"] > 0:
            assert c["requires_user_confirmation"] is True, (
                f"Case {cid}: 후보가 존재하는 모든 사례는 저장 전 사용자 확인(requires_user_confirmation)이 필수여야 합니다."
            )
        else:
            assert c["requires_user_confirmation"] is False, (
                f"Case {cid}: 후보가 0건인 안내문은 사용자 확인이 불필요해야 합니다."
            )

        for cand in candidates:
            assert "title" in cand and cand["title"]
            assert isinstance(cand["is_all_day"], bool)
            assert isinstance(cand["is_time_confirmed"], bool)
            assert isinstance(cand["unconfirmed_fields"], list)
            assert isinstance(cand["requires_user_confirmation"], bool)
            assert isinstance(cand["is_ambiguous"], bool)

            # 모든 추출 후보는 저장 전 사용자 확인 필수
            assert cand["requires_user_confirmation"] is True, (
                f"Case {cid} candidate {cand['title']}: 추출 후보는 반드시 requires_user_confirmation이 true여야 합니다."
            )

            # 시각 확정이면 is_all_day는 False여야 함
            if cand["is_time_confirmed"]:
                assert not cand["is_all_day"], f"Case {cid}: time confirmed cannot be all_day"

            # 모호한 경우 사유 명시 검증
            if cand["is_ambiguous"]:
                assert cand["ambiguity_reason"] is not None and len(cand["ambiguity_reason"]) > 0, (
                    f"Case {cid}: is_ambiguous is True but ambiguity_reason is missing"
                )

            # 정확한 원문 발췌(source_quote) 검증: input_text 내 실제 존재 여부
            sq = cand.get("source_quote")
            assert sq is not None, f"Case {cid}: source_quote is missing"
            assert sq in input_text, f"Case {cid}: source_quote {sq!r} is not an exact substring of input_text {input_text!r}"

            if "source_quotes" in cand:
                for q in cand["source_quotes"]:
                    assert q in input_text, f"Case {cid}: sub-quote {q!r} is not in input_text"

            if cand.get("is_cancellation"):
                has_cancellation_case = True

    # 4. 모호한 자정 시각(sched-20)의 임의 타임스탬프 비확정 검증
    sched_20 = next(c for c in cases if c["id"] == "sched-20")
    cand_20 = sched_20["candidates"][0]
    assert cand_20["end_date"] is None, "sched-20: 모호한 자정 마감은 확정 timestamp(end_date)를 null로 유지해야 합니다."
    assert cand_20["is_time_confirmed"] is False
    assert cand_20["is_ambiguous"] is True
    assert "interpretation_options" in cand_20 and len(cand_20["interpretation_options"]) >= 2

    # 5. 취소 공지 사례 존재 검증
    assert has_cancellation_case, "취소 공지 추출 검증 사례가 fixture에 포함되어 있어야 합니다."
