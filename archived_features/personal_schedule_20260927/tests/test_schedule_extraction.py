"""
tests/test_schedule_extraction.py

CampusMate R2 자연어/공지 -> 일정 후보 추출 및 Zero-Auto-Save 계약 검증 테스트 슈트.
1. 23개 픽스처 케이스(tests/fixtures/schedule_extraction_cases.json) 전수 검증
2. Zero-Auto-Save 및 사용자 확인 강제(requires_user_confirmation: True) 계약 검증
3. API 레벨 검증:
   - 비인증 요청 시 401 차단
   - 빈 문자열/공백 요청 시 422 거부
   - 잘못된 source_url/reference_time 시 422 거부
   - 추출 전후 DB 레코드 수 비교 (DB 불변성/Zero-Auto-Save 증명)
   - 동적 reference_time 계산 검증
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import config
from backend.db.database import get_db, get_db_connection
from backend.main import app
from backend.schemas import (
    ScheduleCandidate,
    ScheduleExtractionRequest,
    ScheduleExtractionResponse,
)
from backend.schedules.extraction import extract_schedule_candidates

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "schedule_extraction_cases.json"


def load_fixtures() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("metadata", {}), data.get("cases", [])


META, CASES = load_fixtures()


# ── 테스트 픽스처: 격리된 DB 환경 ─────────────────────────


@pytest.fixture
def isolated_env(tmp_path: Path) -> Generator[tuple[TestClient, Path], None, None]:
    """임시 SQLite DB로 lifespan과 get_db 의존성을 완전 격리하는 픽스처."""
    test_db = tmp_path / "test_extraction.db"
    orig_auth_db_path = config.AUTH_DB_PATH
    orig_prewarm = config.PREWARM_RAG_ON_STARTUP
    orig_env_db = os.environ.get("AUTH_DB_PATH")
    orig_env_prewarm = os.environ.get("PREWARM_RAG_ON_STARTUP")

    config.AUTH_DB_PATH = str(test_db)
    config.PREWARM_RAG_ON_STARTUP = False
    os.environ["AUTH_DB_PATH"] = str(test_db)
    os.environ["PREWARM_RAG_ON_STARTUP"] = "false"

    orig_overrides = dict(app.dependency_overrides)

    def override_get_db() -> Generator[sqlite3.Connection, None, None]:
        conn = get_db_connection(test_db)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client, test_db
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)
        config.AUTH_DB_PATH = orig_auth_db_path
        config.PREWARM_RAG_ON_STARTUP = orig_prewarm

        if orig_env_db is None:
            os.environ.pop("AUTH_DB_PATH", None)
        else:
            os.environ["AUTH_DB_PATH"] = orig_env_db

        if orig_env_prewarm is None:
            os.environ.pop("PREWARM_RAG_ON_STARTUP", None)
        else:
            os.environ["PREWARM_RAG_ON_STARTUP"] = orig_env_prewarm


@pytest.fixture
def client(isolated_env: tuple[TestClient, Path]) -> TestClient:
    c, _ = isolated_env
    return c


@pytest.fixture
def db_path(isolated_env: tuple[TestClient, Path]) -> Path:
    _, p = isolated_env
    return p


def register_and_login(client: TestClient, username: str = "testuser", password: str = "Password123!") -> str:
    """테스트용 계정 등록 및 로그인 후 Bearer 토큰을 반환한다."""
    reg = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return login.json()["access_token"]


# ── 1. 23개 픽스처 케이스 전수 검증 ─────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_fixture_case_extraction(case: dict[str, Any]):
    """23개 픽스처 케이스 각각의 추출 결과가 기대 명세와 100% 일치하는지 검증한다."""
    ref_time = META.get("reference_time", "2026-09-23T15:00:00+09:00")
    input_text = case["input_text"]
    expected_count = case["expected_candidate_count"]
    expected_confirm = case["requires_user_confirmation"]
    expected_cands = case.get("candidates", [])

    response: ScheduleExtractionResponse = extract_schedule_candidates(
        text=input_text,
        reference_time=ref_time,
    )

    # 1. 후보 개수 및 응답 레벨 사용자 확인 검증
    assert response.total_candidates == expected_count, (
        f"[{case['id']}] 후보 개수 불일치: 기대={expected_count}, 실제={response.total_candidates}"
    )
    assert response.requires_user_confirmation == expected_confirm, (
        f"[{case['id']}] 사용자 확인 필요 여부 불일치: 기대={expected_confirm}, 실제={response.requires_user_confirmation}"
    )

    # 2. 각 후보별 필드 전수 정밀 검증
    for idx, (actual, expected) in enumerate(zip(response.candidates, expected_cands)):
        prefix = f"[{case['id']} - 후보 {idx + 1}]"

        # 제목
        assert actual.title == expected["title"], f"{prefix} 제목 불일치"

        # 종일 및 시각 확정 여부
        assert actual.is_all_day == expected["is_all_day"], f"{prefix} is_all_day 불일치"
        assert actual.is_time_confirmed == expected["is_time_confirmed"], f"{prefix} is_time_confirmed 불일치"

        # 시작/종료 일시
        assert actual.start_date == expected.get("start_date"), f"{prefix} start_date 불일치"
        assert actual.end_date == expected.get("end_date"), f"{prefix} end_date 불일치"

        # 미확정 필드
        assert actual.unconfirmed_fields == expected.get("unconfirmed_fields", []), (
            f"{prefix} unconfirmed_fields 불일치"
        )

        # 모호성 및 사유
        assert actual.is_ambiguous == expected["is_ambiguous"], f"{prefix} is_ambiguous 불일치"
        assert actual.ambiguity_reason == expected.get("ambiguity_reason"), f"{prefix} ambiguity_reason 불일치"

        # 사용자 확인 강제 (Zero-Auto-Save)
        assert actual.requires_user_confirmation is True, f"{prefix} requires_user_confirmation은 반드시 True여야 함"

        # 원문 발췌문 정확성 (input_text의 부분문자열이어야 함)
        assert actual.source_quote == expected["source_quote"], f"{prefix} source_quote 불일치"
        assert actual.source_quote in input_text, f"{prefix} source_quote가 입력 원문에 포함되지 않음"

        # 복수 발췌문 검증 (있는 경우)
        if "source_quotes" in expected:
            assert actual.source_quotes == expected["source_quotes"], f"{prefix} source_quotes 불일치"
            for sq in actual.source_quotes:
                assert sq in input_text, f"{prefix} source_quotes 항목이 입력 원문에 포함되지 않음: {sq}"

        # 경계 모호 해석 옵션 검증 (sched-20 등)
        if "interpretation_options" in expected:
            assert actual.interpretation_options == expected["interpretation_options"], (
                f"{prefix} interpretation_options 불일치"
            )
        if "extracted_date" in expected:
            assert actual.extracted_date == expected["extracted_date"], f"{prefix} extracted_date 불일치"

        # 취소 공지 검증 (sched-23 등)
        if expected.get("is_cancellation"):
            assert actual.is_cancellation is True, f"{prefix} is_cancellation은 True여야 함"
            assert actual.action == "cancel", f"{prefix} action은 'cancel'이어야 함"

        # 5개 유형 중 하나인지 검증
        assert actual.schedule_kind in [
            "TIME_CONFIRMED_EVENT",
            "ALL_DAY_EVENT",
            "DEADLINE_WITH_TIME",
            "DATE_ONLY_DEADLINE",
            "PERIOD_SCHEDULE",
        ], f"{prefix} 유효하지 않은 schedule_kind: {actual.schedule_kind}"


# ── 2. Zero-Auto-Save 계약 및 스키마 검증 ───────────────────


def test_schedule_candidate_requires_user_confirmation_enforced():
    """모든 ScheduleCandidate는 requires_user_confirmation: True가 강제되며 False 설정 시 오류가 발생한다."""
    # 정상 생성 (기본값 True)
    cand = ScheduleCandidate(
        title="시험 마감",
        schedule_kind="DEADLINE_WITH_TIME",
        source_quote="시험 마감",
    )
    assert cand.requires_user_confirmation is True

    # 명시적 False 주입 시 ValidationError 발생 검증
    with pytest.raises(ValidationError) as exc_info:
        ScheduleCandidate(
            title="시험 마감",
            schedule_kind="DEADLINE_WITH_TIME",
            requires_user_confirmation=False,
            source_quote="시험 마감",
        )
    assert "requires_user_confirmation" in str(exc_info.value)


# ── 3. API 엔드포인트: 비인증 요청 시 401 차단 ─────────────


def test_api_extract_unauthorized_blocked(client: TestClient):
    """비인증(토큰 없음 또는 잘못된 토큰) 요청 시 401 Unauthorized로 차단된다."""
    # 토큰 없음
    resp_no_auth = client.post(
        "/api/v1/schedules/extract",
        json={"text": "9월 30일 18:00까지 과제 제출"},
    )
    assert resp_no_auth.status_code == 401
    assert "detail" in resp_no_auth.json()

    # 잘못된 토큰
    resp_bad_token = client.post(
        "/api/v1/schedules/extract",
        headers={"Authorization": "Bearer invalid_opaque_token_value"},
        json={"text": "9월 30일 18:00까지 과제 제출"},
    )
    assert resp_bad_token.status_code == 401


# ── 4. API 엔드포인트: 입력값 검증 (422 거부) ─────────────────


def test_api_extract_validation_failures(client: TestClient):
    """빈 문자열, 공백 문자열, 잘못된 형식 등 유효하지 않은 요청은 422로 거부된다."""
    token = register_and_login(client, username="valuser")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. 빈 문자열
    resp_empty = client.post("/api/v1/schedules/extract", headers=headers, json={"text": ""})
    assert resp_empty.status_code == 422

    # 2. 공백 문자열
    resp_ws = client.post("/api/v1/schedules/extract", headers=headers, json={"text": "   \n\t  "})
    assert resp_ws.status_code == 422

    # 3. 필수 필드 text 누락
    resp_missing = client.post("/api/v1/schedules/extract", headers=headers, json={})
    assert resp_missing.status_code == 422

    # 4. 잘못된 reference_time 형식
    resp_bad_ref = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": "오늘 마감", "reference_time": "invalid-datetime-string"},
    )
    assert resp_bad_ref.status_code == 422

    # 5. 잘못된 source_url (공백, 비허용 프로토콜 등)
    resp_bad_url = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": "오늘 마감", "source_url": "javascript:alert(1)"},
    )
    assert resp_bad_url.status_code == 422

    resp_url_space = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": "오늘 마감", "source_url": "https://example.com/ bad url"},
    )
    assert resp_url_space.status_code == 422


# ── 5. Zero-Auto-Save 증명: DB 불변성 검증 ───────────────────


def test_api_extract_db_immutability(client: TestClient, db_path: Path):
    """추출 엔드포인트 호출 전후 DB 레코드 수가 절대 변하지 않음을 증명한다 (Zero-Auto-Save)."""
    token = register_and_login(client, username="immutableuser")
    headers = {"Authorization": f"Bearer {token}"}

    # 추출 전 DB 레코드 개수 확인
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM personal_schedules")
    schedules_count_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users")
    users_count_before = cur.fetchone()[0]
    conn.close()

    # 후보가 여러 개 존재하는 복합 공지 텍스트로 추출 요청
    sample_text = (
        "제26회 TOPCIT 정기평가 단체접수: 구글 설문 접수 마감은 9월 9일 23:59까지이며, "
        "보증금 납부는 9월 11일 13:00까지입니다."
    )
    resp = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={
            "text": sample_text,
            "reference_time": "2026-09-23T15:00:00+09:00",
            "source_url": "https://www.hansung.ac.kr/notice/1234",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_candidates"] == 2
    assert data["requires_user_confirmation"] is True

    # 반환된 모든 후보에 requires_user_confirmation: true 확인
    for cand in data["candidates"]:
        assert cand["requires_user_confirmation"] is True

    # 추출 후 DB 레코드 개수 재확인 (단 1건도 INSERT/UPDATE되지 않아야 함)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM personal_schedules")
    schedules_count_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users")
    users_count_after = cur.fetchone()[0]
    conn.close()

    assert schedules_count_before == schedules_count_after == 0, (
        f"DB personal_schedules 테이블에 레코드가 생성되었습니다! (전: {schedules_count_before}, 후: {schedules_count_after})"
    )
    assert users_count_before == users_count_after, "users 테이블에 예기치 않은 변경이 발생했습니다."


# ── 6. 동적 reference_time 계산 검증 ─────────────────────────


def test_api_extract_dynamic_reference_time(client: TestClient):
    """클라이언트가 제공한 reference_time에 따라 상대 날짜('오늘', '내일')가 동적으로 올바르게 계산된다."""
    token = register_and_login(client, username="timeuser")
    headers = {"Authorization": f"Bearer {token}"}

    custom_ref = "2027-05-10T10:00:00+09:00"  # 2027년 5월 10일 (월요일)

    # "오늘 18시까지"
    resp_today = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": "오늘 18시까지 과제 제출", "reference_time": custom_ref},
    )
    assert resp_today.status_code == 200
    cand_today = resp_today.json()["candidates"][0]
    assert cand_today["end_date"] == "2027-05-10T18:00:00+09:00"

    # "내일 오후 2시에"
    resp_tomorrow = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={
            "text": "내일 오후 2시에 상상관 301호에서 AI 특강이 진행됩니다.",
            "reference_time": custom_ref,
        },
    )
    assert resp_tomorrow.status_code == 200
    cand_tomorrow = resp_tomorrow.json()["candidates"][0]
    assert cand_tomorrow["start_date"] == "2027-05-11T14:00:00+09:00"


# ── 7. Codex 결함 보고서 4대 반례 및 변형 검증 ─────────────────────────


def test_codex_review_counterexamples(client: TestClient):
    """Codex 마일스톤 재검수 보고서(F2)의 4대 반례 및 일반화 추출을 전수 검증한다."""
    token = register_and_login(client, username="ceuser")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-23T15:00:00+09:00"

    # 반례 1: TOPCIT 날짜 변형 및 2단계 마감 분리
    ce1_text = "TOPCIT 구글 설문 접수 마감은 11월 20일 17:00까지이며 보증금 납부는 11월 22일 12:00까지입니다."
    res1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": ce1_text, "reference_time": ref_time})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["total_candidates"] == 2
    assert d1["candidates"][0]["end_date"] == "2026-11-20T17:00:00+09:00"
    assert d1["candidates"][1]["end_date"] == "2026-11-22T12:00:00+09:00"
    assert d1["candidates"][0]["source_quote"] in ce1_text
    assert d1["candidates"][1]["source_quote"] in ce1_text

    # 반례 2: 연도/날짜 변형 (2027년 11월 5일)
    ce2_text = "2027년 11월 5일은 개교기념일로 전체 휴업일입니다."
    res2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": ce2_text, "reference_time": ref_time})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["total_candidates"] == 1
    assert d2["candidates"][0]["start_date"] == "2027-11-05"
    assert d2["candidates"][0]["end_date"] == "2027-11-05"
    assert d2["candidates"][0]["source_quote"] in ce2_text

    # 반례 3: 날짜 정보 없는 선착순 조기 마감 안내문 -> 0건 반환 (허위 일정 생성 금지)
    ce3_text = "동아리 신청은 선착순이며 조기 마감될 수 있습니다."
    res3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": ce3_text, "reference_time": ref_time})
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["total_candidates"] == 0
    assert d3["candidates"] == []
    assert d3["requires_user_confirmation"] is False

    # 반례 4: 존재하지 않는 달력 날짜(2월 30일) 및 시각(25:90)
    ce4_text = "과제는 2026년 2월 30일 25:90까지 제출하세요."
    res4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": ce4_text, "reference_time": ref_time})
    assert res4.status_code == 200
    d4 = res4.json()
    assert d4["total_candidates"] == 1
    cand4 = d4["candidates"][0]
    assert cand4["start_date"] is None
    assert cand4["end_date"] is None
    assert cand4["is_ambiguous"] is True
    assert cand4["is_time_confirmed"] is False
    assert "exact_date" in cand4["unconfirmed_fields"]
    assert "time" in cand4["unconfirmed_fields"]
    assert "존재하지 않는 달력 날짜" in cand4["ambiguity_reason"]
    assert cand4["source_quote"] in ce4_text


def test_codex_round2_r2_five_counterexamples(client: TestClient):
    """Codex 재검수 보고서(2026-09-24) R2의 5대 반례 입력 및 일반화 동작을 전수 검증한다."""
    token = register_and_login(client, username="ce2user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-24T12:00:00+09:00"

    # 반례 1: 원문 기반 동적 제목 ("장학금 신청서 제출", 하드코딩 지도교수 면담 아님)
    text1 = "오늘 18시까지 장학금 신청서를 제출하세요."
    res1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text1, "reference_time": ref_time})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["total_candidates"] == 1
    c1 = d1["candidates"][0]
    assert "장학금" in c1["title"]
    assert "지도교수" not in c1["title"]
    assert c1["is_time_confirmed"] is True
    assert c1["end_date"] == "2026-09-24T18:00:00+09:00"
    assert c1["is_ambiguous"] is False

    # 반례 2: 25시 비정상 시각 감지 및 검증 우회 방지
    text2 = "보고서는 오늘 25시까지 제출하세요."
    res2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text2, "reference_time": ref_time})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["total_candidates"] == 1
    c2 = d2["candidates"][0]
    assert "보고서" in c2["title"]
    assert c2["is_time_confirmed"] is False
    assert c2["is_ambiguous"] is True
    assert "time" in c2["unconfirmed_fields"]
    assert c2["end_datetime"] is None
    assert c2["end_date"] is None
    assert "25:00" in (c2["ambiguity_reason"] or "")

    # 반례 3: 날짜 없는 자정 ("과제는 자정까지 제출하세요.") -> 2026-10-09 날조 금지
    text3 = "과제는 자정까지 제출하세요."
    res3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text3, "reference_time": ref_time})
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["total_candidates"] == 1
    c3 = d3["candidates"][0]
    assert "과제" in c3["title"]
    assert "중간 보고서" not in c3["title"]
    assert c3["extracted_date"] is None
    assert c3["interpretation_options"] is None
    assert c3["is_ambiguous"] is True
    assert c3["is_time_confirmed"] is False
    assert "date" in c3["unconfirmed_fields"]

    # 반례 4: 다단계 순차 마감 중 1단계만 달력/시각 오류 (2월 30일 25:90) -> 후보 1 오류 처리, 후보 2 정상 확정
    text4 = "TOPCIT 구글 설문 접수 마감은 2월 30일 25:90까지이며 보증금 납부는 11월 22일 12:00까지입니다."
    res4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text4, "reference_time": ref_time})
    assert res4.status_code == 200
    d4 = res4.json()
    assert d4["total_candidates"] == 2
    cand4_1 = d4["candidates"][0]
    cand4_2 = d4["candidates"][1]

    # 1단계: 2월 30일 25:90 오류 감지
    assert cand4_1["is_time_confirmed"] is False
    assert cand4_1["is_ambiguous"] is True
    assert "exact_date" in cand4_1["unconfirmed_fields"]
    assert "time" in cand4_1["unconfirmed_fields"]
    assert cand4_1["end_datetime"] is None
    assert cand4_1["end_date"] is None

    # 2단계: 11월 22일 12:00 정상 확정
    assert cand4_2["is_time_confirmed"] is True
    assert cand4_2["is_ambiguous"] is False
    assert cand4_2["end_datetime"] == "2026-11-22T12:00:00+09:00"
    assert cand4_2["end_date"] == "2026-11-22T12:00:00+09:00"

    # 반례 5: 다회차 설명회 명시 연도 2027 보존, 분 단위 보존(14:30), 자정 넘김 처리(23:30 -> 익일 00:30, 24:00 방지)
    text5 = "설명회 일정: 1차 2027년 11월 20일 13:30, 2차 2027년 11월 22일 23:30, 각 1시간 진행합니다."
    res5 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text5, "reference_time": ref_time})
    assert res5.status_code == 200
    d5 = res5.json()
    assert d5["total_candidates"] == 2
    cand5_1 = d5["candidates"][0]
    cand5_2 = d5["candidates"][1]

    # 1차: 2027년, 13:30 ~ 14:30 (분 유실 없음)
    assert cand5_1["title"] == "설명회 1차"
    assert cand5_1["start_datetime"] == "2027-11-20T13:30:00+09:00"
    assert cand5_1["end_datetime"] == "2027-11-20T14:30:00+09:00"
    assert cand5_1["is_time_confirmed"] is True

    # 2차: 2027년, 23:30 ~ 익일 00:30 (24:00 방지 및 날짜 넘김)
    assert cand5_2["title"] == "설명회 2차"
    assert cand5_2["start_datetime"] == "2027-11-22T23:30:00+09:00"
    assert cand5_2["end_datetime"] == "2027-11-23T00:30:00+09:00"
    assert cand5_2["is_time_confirmed"] is True


def test_codex_round3_unified_validation_and_grounding_counterexamples(client: TestClient):
    """Codex 재검수 보고서(2026-09-25)의 결함 A(모든 분기 공통 검증/정규화) 및 결함 B(근거 없는 기본값/하드코딩 제거) 반례를 전수 검증한다."""
    token = register_and_login(client, username="ce3user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-23T15:00:00+09:00"

    # 반례 A-1: 취소 공지 분기에서 2월 30일 25:90 무효값 유입 시 확정 일시 필드 클리어 및 모호 처리
    cancellation_invalid = "[취소공지] 2027년 2월 30일 25:90 세미나 행사가 취소되었습니다."
    res_a1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": cancellation_invalid, "reference_time": ref_time})
    assert res_a1.status_code == 200
    d_a1 = res_a1.json()
    assert d_a1["total_candidates"] == 1
    c_a1 = d_a1["candidates"][0]
    assert c_a1["is_cancellation"] is True
    assert c_a1["action"] == "cancel"
    assert c_a1["start_date"] is None
    assert c_a1["end_date"] is None
    assert c_a1["start_datetime"] is None
    assert c_a1["end_datetime"] is None
    assert c_a1["is_ambiguous"] is True
    assert c_a1["is_time_confirmed"] is False
    assert "exact_date" in c_a1["unconfirmed_fields"]
    assert "time" in c_a1["unconfirmed_fields"]

    # 반례 A-2: 취소 공지 분기에서 정상적인 2027년 연도 입력 시 2026년으로 오염되지 않고 2027년 보존
    cancellation_valid = "[취소공지] 2027년 11월 20일 세미나 행사가 취소되었습니다."
    res_a2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": cancellation_valid, "reference_time": ref_time})
    assert res_a2.status_code == 200
    d_a2 = res_a2.json()
    assert d_a2["total_candidates"] == 1
    c_a2 = d_a2["candidates"][0]
    assert c_a2["is_cancellation"] is True
    assert c_a2["start_date"] == "2027-11-20"
    assert c_a2["is_ambiguous"] is False

    # 반례 A-3: 기간 분기에서 시작 날짜 2월 30일 오류 시 클리어
    period_invalid = "신입생 오리엔테이션은 2026년 2월 30일 09:00부터 2026년 3월 5일 18:00까지 진행됩니다."
    res_a3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": period_invalid, "reference_time": ref_time})
    assert res_a3.status_code == 200
    d_a3 = res_a3.json()
    assert d_a3["total_candidates"] == 1
    c_a3 = d_a3["candidates"][0]
    assert c_a3["start_date"] is None
    assert c_a3["end_date"] is None
    assert c_a3["start_datetime"] is None
    assert c_a3["end_datetime"] is None
    assert c_a3["is_ambiguous"] is True
    assert "exact_date" in c_a3["unconfirmed_fields"]

    # 반례 A-4: 기간 순서 역전 오류 (시작일 > 종료일) 클리어
    period_order_invalid = "2026학년도 집중이수 기간은 2026년 11월 10일부터 2026년 11월 5일까지입니다."
    res_a4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": period_order_invalid, "reference_time": ref_time})
    assert res_a4.status_code == 200
    d_a4 = res_a4.json()
    assert d_a4["total_candidates"] == 1
    c_a4 = d_a4["candidates"][0]
    assert c_a4["start_date"] is None
    assert c_a4["end_date"] is None
    assert c_a4["start_datetime"] is None
    assert c_a4["end_datetime"] is None
    assert c_a4["is_ambiguous"] is True
    assert "period_order" in c_a4["unconfirmed_fields"]

    # 반례 A-5: 휴업일 분기에서 2월 30일 오류 시 클리어
    holiday_invalid = "2026년 2월 30일은 개교기념일로 전체 휴업일입니다."
    res_a5 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": holiday_invalid, "reference_time": ref_time})
    assert res_a5.status_code == 200
    d_a5 = res_a5.json()
    assert d_a5["total_candidates"] == 1
    c_a5 = d_a5["candidates"][0]
    assert c_a5["start_date"] is None
    assert c_a5["end_date"] is None
    assert c_a5["is_ambiguous"] is True
    assert "exact_date" in c_a5["unconfirmed_fields"]

    # 반례 B-1: 날짜/시각 분리 문장에서 원문에 시각이 없는 경우 17:30 날조 금지 및 동적 제목 추출
    no_time_period = "장학금 신청은 11월 1일부터 11월 5일까지이며 마감일에 전산 마감됩니다."
    res_b1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": no_time_period, "reference_time": ref_time})
    assert res_b1.status_code == 200
    d_b1 = res_b1.json()
    assert d_b1["total_candidates"] == 1
    c_b1 = d_b1["candidates"][0]
    assert "장학금" in c_b1["title"]
    assert "제3전공" not in c_b1["title"]
    assert c_b1["end_datetime"] is None
    assert c_b1["start_datetime"] is None
    assert c_b1["is_time_confirmed"] is False
    assert c_b1["start_date"] == "2026-11-01"
    assert c_b1["end_date"] == "2026-11-05"

    # 반례 B-2: 연장 마감에서 원문에 시각이 없는 경우 15:00 날조 금지 및 동적 제목 추출
    no_time_ext = "장학금 신청 마감일이 당초 11월 1일에서 11월 5일로 연장되었습니다."
    res_b2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": no_time_ext, "reference_time": ref_time})
    assert res_b2.status_code == 200
    d_b2 = res_b2.json()
    assert d_b2["total_candidates"] == 1
    c_b2 = d_b2["candidates"][0]
    assert "장학금" in c_b2["title"]
    assert "제3전공" not in c_b2["title"]
    assert c_b2["end_datetime"] is None
    assert c_b2["is_time_confirmed"] is False
    assert c_b2["end_date"] == "2026-11-05"


def test_codex_round4_year_handling_counterexamples(client: TestClient):
    """Codex 재검수 보고서(2026-09-25 repair3)의 연도 처리 4대 반례 및 양방향 연도 경계, 상대 날짜 무오염을 전수 검증한다."""
    token = register_and_login(client, username="ce4user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-25T12:00:00+09:00"

    # 반례 1: 2025 -> 2026 연도 경계 기간 일정 (시각 포함)
    text1 = "교육 기간은 2025년 12월 30일 09:00부터 2026년 1월 5일 18:00까지입니다."
    res1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text1, "reference_time": ref_time})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["total_candidates"] == 1
    c1 = d1["candidates"][0]
    assert c1["start_datetime"] == "2025-12-30T09:00:00+09:00"
    assert c1["end_datetime"] == "2026-01-05T18:00:00+09:00"
    assert c1["is_ambiguous"] is False
    assert c1["is_time_confirmed"] is True

    # 반례 2: 2025 -> 2026 연도 경계 기간 일정 (시각 없음)
    text2 = "교육 기간은 2025년 12월 30일부터 2026년 1월 5일까지입니다."
    res2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text2, "reference_time": ref_time})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["total_candidates"] == 1
    c2 = d2["candidates"][0]
    assert c2["start_date"] == "2025-12-30"
    assert c2["end_date"] == "2026-01-05"
    assert c2["start_datetime"] is None
    assert c2["end_datetime"] is None
    assert c2["is_time_confirmed"] is False

    # 반례 3: 무관한 과거 사업 연도(2025)와 오늘(2026-09-25) 마감
    text3 = "2025년 사업 안내입니다. 오늘 18시까지 장학금 신청서를 제출하세요."
    res3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text3, "reference_time": ref_time})
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["total_candidates"] == 1
    c3 = d3["candidates"][0]
    assert c3["end_datetime"] == "2026-09-25T18:00:00+09:00"
    assert c3["end_date"] == "2026-09-25T18:00:00+09:00"
    assert c3["is_time_confirmed"] is True
    assert "2025" not in str(c3["end_datetime"])

    # 반례 4: 무관한 과거 사업 연도(2025)와 내일(2026-09-26) 약속
    text4 = "2025년 사업 안내입니다. 내일 오후 2시에 장학금 설명회가 진행됩니다."
    res4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text4, "reference_time": ref_time})
    assert res4.status_code == 200
    d4 = res4.json()
    assert d4["total_candidates"] == 1
    c4 = d4["candidates"][0]
    assert c4["start_datetime"] == "2026-09-26T14:00:00+09:00"
    assert "2025" not in str(c4["start_datetime"])

    # 반례 5: 반대 방향 2026 -> 2027 연도 경계 기간 일정 (시각 포함)
    text5 = "교육 기간은 2026년 12월 30일 09:00부터 2027년 1월 5일 18:00까지입니다."
    res5 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text5, "reference_time": ref_time})
    assert res5.status_code == 200
    d5 = res5.json()
    assert d5["total_candidates"] == 1
    c5 = d5["candidates"][0]
    assert c5["start_datetime"] == "2026-12-30T09:00:00+09:00"
    assert c5["end_datetime"] == "2027-01-05T18:00:00+09:00"
    assert c5["is_ambiguous"] is False

    # 반례 6: 반대 방향 2026 -> 2027 연도 경계 기간 일정 (시각 없음)
    text6 = "교육 기간은 2026년 12월 30일부터 2027년 1월 5일까지입니다."
    res6 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text6, "reference_time": ref_time})
    assert res6.status_code == 200
    d6 = res6.json()
    assert d6["total_candidates"] == 1
    c6 = d6["candidates"][0]
    assert c6["start_date"] == "2026-12-30"
    assert c6["end_date"] == "2027-01-05"

    # 반례 7: 종료 연도 생략 시 연도 롤오버 추론 (2025년 12월 30일 -> 1월 5일)
    text7 = "교육 기간은 2025년 12월 30일 09:00부터 1월 5일 18:00까지입니다."
    res7 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text7, "reference_time": ref_time})
    assert res7.status_code == 200
    d7 = res7.json()
    assert d7["total_candidates"] == 1
    c7 = d7["candidates"][0]
    assert c7["start_datetime"] == "2025-12-30T09:00:00+09:00"
    assert c7["end_datetime"] == "2026-01-05T18:00:00+09:00"

    # 반례 8: 기존 취소 공지의 명시 연도(2027) 보존
    text8 = "행사 취소 안내: 2027년 11월 20일 14:00 예정되었던 음악회 행사는 취소되었습니다."
    res8 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text8, "reference_time": ref_time})
    assert res8.status_code == 200
    d8 = res8.json()
    assert d8["total_candidates"] == 1
    c8 = d8["candidates"][0]
    assert c8["is_cancellation"] is True
    assert c8["start_datetime"] == "2027-11-20T14:00:00+09:00"
    assert c8["is_ambiguous"] is False


def test_real_notice_and_variation_acceptance(client: TestClient, db_path: Path):
    """실제 공지 4종(편입생 학점인정, TOPCIT, 멘토링, 학사일정) 및 미학습 변형 공지 전수 검증."""
    root = Path(__file__).resolve().parents[1]
    token = register_and_login(client, username="realnoticeuser")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-25T12:00:00+09:00"

    fixture = json.loads((root / "tests/fixtures/real_notice_acceptance_cases.json").read_text())
    dataset = root / "data/unified_campus_knowledge.json"
    documents = {d["id"]: d for d in json.loads(dataset.read_text())}


    # 1. 실제 공지 5개 케이스 API 검증
    for case in fixture["cases"]:
        doc = documents[case["doc_id"]]
        body = doc["content"]
        text = case.get("input_excerpt", body)

        # 추출 전 DB 레코드 개수 확인 (Zero-Auto-Save)
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            count_before = cur.fetchone()[0]

        res = client.post(
            "/api/v1/schedules/extract",
            headers=headers,
            json={"text": text, "reference_time": ref_time},
        )
        assert res.status_code == 200
        data = res.json()
        candidates = data["candidates"]

        if "expected_count" in case:
            assert len(candidates) == case["expected_count"]
            assert data["requires_user_confirmation"] is False
        else:
            assert len(candidates) > 0
            assert data["requires_user_confirmation"] is True

            def matches(c):
                start = c.get("start_datetime") or c.get("start_date")
                end = c.get("end_datetime") or c.get("end_date")
                return (
                    end == case["expected_end"]
                    and ("expected_start" not in case or start == case["expected_start"])
                    and any(k in c["title"] for k in case["title_keywords"])
                )

            assert any(matches(c) for c in candidates), f"[{case['id']}] 목표 일정 매칭 실패"

        # 모든 후보의 source_quote가 원문의 실제 부분문자열인지 검증
        for c in candidates:
            assert c["source_quote"] in text, f"[{case['id']}] source_quote 미일치: {c['source_quote']}"
            assert c["requires_user_confirmation"] is True

        # 추출 후 DB 불변 검증 (단 1건도 자동 저장되지 않음)
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            count_after = cur.fetchone()[0]
        assert count_before == count_after, f"[{case['id']}] 추출 중 DB에 자동 저장되었습니다!"

    # 2. 미학습 변형 공지 검증 (Out-of-sample variations - 문서 ID/상수 없음)
    # 변형 1: 학사일정 목록형 (2027년 5월, 춘계 체육대회)
    var1_text = (
        "2027학년도 학사일정 안내\n"
        "2027.05.03(월)\n~\n2027.05.08(토)\n춘계 체육대회\n"
        "2027.05.10(월)\n개교기념일"
    )
    res_v1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var1_text, "reference_time": ref_time})
    assert res_v1.status_code == 200
    d_v1 = res_v1.json()
    assert d_v1["total_candidates"] == 2
    c_v1_0 = d_v1["candidates"][0]
    assert c_v1_0["title"] == "춘계 체육대회"
    assert c_v1_0["start_date"] == "2027-05-03"
    assert c_v1_0["end_date"] == "2027-05-08"
    assert c_v1_0["is_all_day"] is True
    assert c_v1_0["source_quote"] in var1_text

    # 변형 2: 슬래시 표기 날짜 및 시각 (8월 하계 프로그램)
    var2_text = (
        "2026학년도 하계 비교과 프로그램 참가자 모집\n"
        "신청 기간 : 2026/08/10(월) 09:00 ~ 2026/08/14(금) 18:00\n"
        "많은 참여 바랍니다."
    )
    res_v2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var2_text, "reference_time": ref_time})
    assert res_v2.status_code == 200
    d_v2 = res_v2.json()
    assert d_v2["total_candidates"] == 1
    c_v2 = d_v2["candidates"][0]
    assert "신청" in c_v2["title"]
    assert c_v2["start_datetime"] == "2026-08-10T09:00:00+09:00"
    assert c_v2["end_datetime"] == "2026-08-14T18:00:00+09:00"
    assert c_v2["is_time_confirmed"] is True
    assert c_v2["source_quote"] in var2_text

    # 변형 3: 원문 명시 연도 2028년 및 U+223C(∼) 틸데 기호
    var3_text = (
        "2028학년도 전과 신청 안내\n"
        "접수 기간 : 2028. 1. 5.(월) 10:00 ∼ 1. 9.(금) 17:00\n"
        "마감 후 접수 불가"
    )
    res_v3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var3_text, "reference_time": ref_time})
    assert res_v3.status_code == 200
    d_v3 = res_v3.json()
    assert d_v3["total_candidates"] == 1
    c_v3 = d_v3["candidates"][0]
    assert "전과" in c_v3["title"]
    assert c_v3["start_datetime"] == "2028-01-05T10:00:00+09:00"
    assert c_v3["end_datetime"] == "2028-01-09T17:00:00+09:00"
    assert c_v3["source_quote"] in var3_text

    # 변형 4: 24:00 경계 표현과 다음 단계 확정 시각 분리
    var4_text = (
        "2026년 하반기 채용 연계 인턴십 선발\n\n"
        "1단계\n2026. 11. 1.(일) ~ 11. 5.(목) 24:00까지\n[서류 접수]\n\n"
        "2단계\n2026. 11. 10.(화) 10:00 ~ 11. 12.(목) 16:00\n[면접 전형]"
    )
    res_v4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var4_text, "reference_time": ref_time})
    assert res_v4.status_code == 200
    d_v4 = res_v4.json()
    assert d_v4["total_candidates"] == 2
    step1 = d_v4["candidates"][0]
    assert step1["is_ambiguous"] is True
    assert "exact_boundary" in step1["unconfirmed_fields"]
    assert step1["end_datetime"] is None
    step2 = d_v4["candidates"][1]
    assert step2["is_ambiguous"] is False
    assert step2["end_datetime"] == "2026-11-12T16:00:00+09:00"
    assert "면접 전형" in step2["title"]
    assert step1["source_quote"] in var4_text
    assert step2["source_quote"] in var4_text

    # 변형 5: 제목과 본문 신청 날짜 충돌 감지
    var5_text = (
        "2026학년도 현장실습 신청 안내 (10.1~10.5)\n\n"
        "신청 기간: 2026. 10. 10.(토) ~ 2026. 10. 15.(목) 18:00까지"
    )
    res_v5 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var5_text, "reference_time": ref_time})
    assert res_v5.status_code == 200
    d_v5 = res_v5.json()
    assert d_v5["total_candidates"] == 1
    c_v5 = d_v5["candidates"][0]
    assert c_v5["end_datetime"] == "2026-10-15T18:00:00+09:00"
    assert c_v5["source_quote"] in var5_text

    # 변형 6: 점 표기 단일 마감 (2026. 11. 20.(금) 17:00까지)
    var6_text = "2026학년도 2학기 졸업논문 최종본 제출 마감은 2026. 11. 20.(금) 17:00까지입니다."
    res_v6 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": var6_text, "reference_time": ref_time})
    assert res_v6.status_code == 200
    d_v6 = res_v6.json()
    assert d_v6["total_candidates"] == 1
    c_v6 = d_v6["candidates"][0]
    assert c_v6["end_datetime"] == "2026-11-20T17:00:00+09:00"
    assert "졸업논문" in c_v6["title"]
    assert c_v6["source_quote"] in var6_text


def test_n1_symmetric_invalid_and_boundary_time_handling(client: TestClient):
    """N1 (P1): 시작 및 종료 시각의 25:90, 25:00, 23:90, 24:00 대칭적 검증 및 보류 처리 검증."""
    token = register_and_login(client, username="n1user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-25T12:00:00+09:00"

    # 1. 시작 시각 25:90 오류 (Codex 재현 입력)
    text_start_2590 = "행사 안내\n신청 기간: 2027.11.01 25:90 ~ 2027.11.05 18:00"
    res1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_start_2590, "reference_time": ref_time})
    assert res1.status_code == 200
    c1 = res1.json()["candidates"][0]
    assert c1["start_datetime"] is None
    assert c1["start_date"] is None
    assert c1["end_datetime"] == "2027-11-05T18:00:00+09:00"
    assert c1["is_time_confirmed"] is False
    assert c1["is_ambiguous"] is True
    assert "time" in c1["unconfirmed_fields"]
    assert "존재하지 않는 시각(25:90)" in c1["ambiguity_reason"]

    # 2. 시작 시각 25:00 오류
    text_start_2500 = "행사 안내\n신청 기간: 2027.11.01 25:00 ~ 2027.11.05 18:00"
    res2 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_start_2500, "reference_time": ref_time})
    assert res2.status_code == 200
    c2 = res2.json()["candidates"][0]
    assert c2["start_datetime"] is None
    assert c2["start_date"] is None
    assert c2["is_time_confirmed"] is False
    assert c2["is_ambiguous"] is True
    assert "time" in c2["unconfirmed_fields"]
    assert "존재하지 않는 시각(25:00)" in c2["ambiguity_reason"]

    # 3. 시작 시각 23:90 오류
    text_start_2390 = "행사 안내\n신청 기간: 2027.11.01 23:90 ~ 2027.11.05 18:00"
    res3 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_start_2390, "reference_time": ref_time})
    assert res3.status_code == 200
    c3 = res3.json()["candidates"][0]
    assert c3["start_datetime"] is None
    assert c3["start_date"] is None
    assert c3["is_time_confirmed"] is False
    assert c3["is_ambiguous"] is True
    assert "time" in c3["unconfirmed_fields"]
    assert "존재하지 않는 시각(23:90)" in c3["ambiguity_reason"]

    # 4. 시작 시각 24:00 경계 표현
    text_start_2400 = "행사 안내\n신청 기간: 2027.11.01 24:00 ~ 2027.11.05 18:00"
    res4 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_start_2400, "reference_time": ref_time})
    assert res4.status_code == 200
    c4 = res4.json()["candidates"][0]
    assert c4["start_datetime"] is None
    assert c4["is_time_confirmed"] is False
    assert c4["is_ambiguous"] is True
    assert "time" in c4["unconfirmed_fields"]
    assert "exact_boundary" in c4["unconfirmed_fields"]
    assert "24:00 경계 표현" in c4["ambiguity_reason"]

    # 5. 종료 시각 25:90 대칭 오류
    text_end_2590 = "행사 안내\n신청 기간: 2027.11.01 09:00 ~ 2027.11.05 25:90"
    res5 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_end_2590, "reference_time": ref_time})
    assert res5.status_code == 200
    c5 = res5.json()["candidates"][0]
    assert c5["start_datetime"] == "2027-11-01T09:00:00+09:00"
    assert c5["end_datetime"] is None
    assert c5["end_date"] is None
    assert c5["is_time_confirmed"] is False
    assert c5["is_ambiguous"] is True
    assert "time" in c5["unconfirmed_fields"]
    assert "존재하지 않는 시각(25:90)" in c5["ambiguity_reason"]

    # 6. 종료 시각 25:00 대칭 오류
    text_end_2500 = "행사 안내\n신청 기간: 2027.11.01 09:00 ~ 2027.11.05 25:00"
    res6 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_end_2500, "reference_time": ref_time})
    assert res6.status_code == 200
    c6 = res6.json()["candidates"][0]
    assert c6["end_datetime"] is None
    assert c6["end_date"] is None
    assert c6["is_time_confirmed"] is False
    assert c6["is_ambiguous"] is True
    assert "time" in c6["unconfirmed_fields"]
    assert "존재하지 않는 시각(25:00)" in c6["ambiguity_reason"]

    # 7. 종료 시각 23:90 대칭 오류
    text_end_2390 = "행사 안내\n신청 기간: 2027.11.01 09:00 ~ 2027.11.05 23:90"
    res7 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_end_2390, "reference_time": ref_time})
    assert res7.status_code == 200
    c7 = res7.json()["candidates"][0]
    assert c7["end_datetime"] is None
    assert c7["end_date"] is None
    assert c7["is_time_confirmed"] is False
    assert c7["is_ambiguous"] is True
    assert "time" in c7["unconfirmed_fields"]
    assert "존재하지 않는 시각(23:90)" in c7["ambiguity_reason"]

    # 8. 종료 시각 24:00 경계 표현 대칭 검증
    text_end_2400 = "행사 안내\n신청 기간: 2027.11.01 09:00 ~ 2027.11.05 24:00"
    res8 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_end_2400, "reference_time": ref_time})
    assert res8.status_code == 200
    c8 = res8.json()["candidates"][0]
    assert c8["end_datetime"] is None
    assert c8["is_time_confirmed"] is False
    assert c8["is_ambiguous"] is True
    assert "time" in c8["unconfirmed_fields"]
    assert "exact_boundary" in c8["unconfirmed_fields"]
    assert "24:00 경계 표현" in c8["ambiguity_reason"]


def test_n2_period_and_single_event_coexistence_and_topcit(client: TestClient):
    """N2 (P2): 기간 후보가 있어도 단일 일정 동시 추출 및 TOPCIT 4단계 시험 응시 회수 검증."""
    token = register_and_login(client, username="n2user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-25T12:00:00+09:00"

    # 1. 접수 기간 + 면접 일시 공존 검증
    text_coexist = (
        "신청 안내\n"
        "접수 기간: 2027. 11. 1.(월) 09:00 ~ 2027. 11. 5.(금) 18:00\n"
        "면접 일시: 2027. 11. 8.(월) 14:00"
    )
    res1 = client.post("/api/v1/schedules/extract", headers=headers, json={"text": text_coexist, "reference_time": ref_time})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["total_candidates"] == 2
    c_period = d1["candidates"][0]
    c_interview = d1["candidates"][1]

    # 기간 후보 검증
    assert "접수 기간" in c_period["title"]
    assert c_period["start_datetime"] == "2027-11-01T09:00:00+09:00"
    assert c_period["end_datetime"] == "2027-11-05T18:00:00+09:00"
    assert c_period["is_time_confirmed"] is True
    assert c_period["source_quote"] in text_coexist

    # 단일 면접 일정 검증: 종료 미명시 일정에 종료 시각을 만들지 않음
    assert "면접" in c_interview["title"]
    assert c_interview["schedule_kind"] == "TIME_CONFIRMED_EVENT"
    assert c_interview["start_datetime"] == "2027-11-08T14:00:00+09:00"
    assert c_interview["end_datetime"] is None
    assert c_interview["end_date"] is None
    assert c_interview["unconfirmed_fields"] == ["end_time"]
    assert c_interview["is_time_confirmed"] is True
    assert c_interview["is_ambiguous"] is True
    assert c_interview["source_quote"] in text_coexist

    # 2. 실제 TOPCIT 공지에서 4단계 시험 응시 (9:30 ~ 12:00) 회수 및 입실완료(9:10) 오혼동 방지 검증
    dataset_path = Path(__file__).resolve().parents[1] / "data/unified_campus_knowledge.json"
    documents = {d["id"]: d for d in json.loads(dataset_path.read_text())}
    topcit_doc = documents["7315051911dd61481bf87fa8f2347f5b01e7be395623a44d9e41bdd14fa5d308"]

    res_top = client.post("/api/v1/schedules/extract", headers=headers, json={"text": topcit_doc["content"], "reference_time": ref_time})
    assert res_top.status_code == 200
    d_top = res_top.json()
    assert d_top["total_candidates"] == 4  # 1단계~4단계

    step4 = [c for c in d_top["candidates"] if "4단계" in c["title"] or "시험 응시" in c["title"]]
    assert len(step4) == 1
    c4 = step4[0]
    assert c4["start_datetime"] == "2026-10-10T09:30:00+09:00"
    assert c4["end_datetime"] == "2026-10-10T12:00:00+09:00"
    assert "09:10" not in (c4["start_datetime"] or "")
    assert c4["is_time_confirmed"] is True
    assert c4["source_quote"] in topcit_doc["content"]


def test_n3_source_title_contract_and_conflict_check(client: TestClient):
    """N3 (P2): source_title 계약 연결, extra=forbid 유지, 동일 날짜 정상화, 멘토링 충돌 검출 검증."""
    token = register_and_login(client, username="n3user")
    headers = {"Authorization": f"Bearer {token}"}
    ref_time = "2026-09-25T12:00:00+09:00"

    # 1. extra=forbid 검증 (미승인 필드 주입 시 422 거부)
    res_forbid = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": "공지 내용", "reference_time": ref_time, "extra_unknown_field": "injected"},
    )
    assert res_forbid.status_code == 422

    # 2. 동일 날짜 제목/본문 정상 일치 시 오경고 배제 검증 (27.11 연도 오인 버그 해결)
    title_match = "프로그램 모집 안내 (2027.11.01 ~ 2027.11.05)"
    body_match = "신청 기간: 2027.11.01 09:00 ~ 2027.11.05 18:00"
    res_match = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": body_match, "source_title": title_match, "reference_time": ref_time},
    )
    assert res_match.status_code == 200
    d_m = res_match.json()
    assert d_m["total_candidates"] == 1
    c_m = d_m["candidates"][0]
    assert c_m["is_ambiguous"] is False
    assert c_m["ambiguity_reason"] is None

    # 3. 실제 멘토링 공지의 별도 출처 제목과 본문 기간 충돌 검출 검증
    dataset_path = Path(__file__).resolve().parents[1] / "data/unified_campus_knowledge.json"
    documents = {d["id"]: d for d in json.loads(dataset_path.read_text())}
    mentoring_doc = documents["1a676b27ed5c8142545bbfb02958d03031276fbb0f5491a7264b47471e598ae1"]

    res_ment = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={
            "text": mentoring_doc["content"],
            "source_title": mentoring_doc["title"],
            "reference_time": ref_time,
        },
    )
    assert res_ment.status_code == 200
    d_ment = res_ment.json()
    assert d_ment["total_candidates"] >= 1
    c_ment = d_ment["candidates"][0]
    assert c_ment["is_ambiguous"] is True
    assert "공지 제목의 기간과 본문 신청 기간이 상이하여 확인 필요" in c_ment["ambiguity_reason"]
    assert c_ment["source_quote"] in mentoring_doc["content"]





