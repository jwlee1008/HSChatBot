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
