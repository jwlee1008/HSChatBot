"""
tests/test_schedules.py

CampusMate R1-B 개인 일정 CRUD 및 사용자 격리 검증 테스트 슈트.
5개 일정 유형 계약, 서울 달력 날짜 일치, BOLA 격리, PATCH 원자성,
캘린더/목록 겹침 필터링, v1->v2 마이그레이션 데이터 보존 및 서브프로세스 영속성을 검증한다.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

import config
from backend.auth.security import hash_password, hash_session_token
from backend.db.database import get_db, get_db_connection
from backend.db.migrations import MIGRATIONS, init_db
from backend.main import app
from backend.schemas import Priority, ScheduleKind


@pytest.fixture
def isolated_schedule_env(tmp_path: Path) -> Generator[tuple[TestClient, Path], None, None]:
    """임시 SQLite DB로 lifespan과 get_db 의존성을 완전 격리하는 픽스처."""
    test_db = tmp_path / "test_schedules.db"
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
def client(isolated_schedule_env: tuple[TestClient, Path]) -> TestClient:
    c, _ = isolated_schedule_env
    return c


@pytest.fixture
def temp_db_path(isolated_schedule_env: tuple[TestClient, Path]) -> Path:
    _, db_path = isolated_schedule_env
    return db_path


def register_and_login(client: TestClient, username: str, password: str = "Password123!") -> str:
    """테스트용 계정 등록 및 로그인 후 Bearer 토큰을 반환한다."""
    reg = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return login.json()["access_token"]


# ── 1. 5대 일정 유형 각각 생성 -> 조회 -> 수정 -> 삭제 라이프사이클 ──────────


def test_5_schedule_kinds_crud_lifecycle(client: TestClient):
    """5개 일정 유형 각각의 생성, 조회, 수정, 삭제 및 메타데이터 보존 검증."""
    token = register_and_login(client, "user_crud")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. ALL_DAY_EVENT
    all_day_payload = {
        "title": "2학기 수강신청 기간",
        "description": "2026학년도 2학기 본 수강신청",
        "course_name": None,
        "schedule_kind": "ALL_DAY_EVENT",
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "timezone": "Asia/Seoul",
        "source_url": "https://www.hansung.ac.kr/notice/1",
        "source_title": "2학기 수강신청 안내",
        "extracted_quote": "수강신청 기간은 10월 1일부터 10월 3일까지입니다.",
        "is_completed": False,
        "priority": "HIGH",
        "confirmed": True,
    }
    r1 = client.post("/api/v1/schedules", json=all_day_payload, headers=headers)
    assert r1.status_code == 201, r1.text
    s1 = r1.json()
    assert s1["schedule_kind"] == "ALL_DAY_EVENT"
    assert s1["is_all_day"] is True
    assert s1["is_time_confirmed"] is False
    assert s1["start_date"] == "2026-10-01"
    assert s1["end_date"] == "2026-10-03"
    assert s1["start_datetime"] is None
    assert s1["end_datetime"] is None
    assert s1["priority"] == "HIGH"
    assert s1["extracted_quote"] == all_day_payload["extracted_quote"]

    # 2. DATE_ONLY_DEADLINE
    d_deadline_payload = {
        "title": "졸업유예 신청 마감",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-10-10",
        "confirmed": True,
    }
    r2 = client.post("/api/v1/schedules", json=d_deadline_payload, headers=headers)
    assert r2.status_code == 201, r2.text
    s2 = r2.json()
    assert s2["schedule_kind"] == "DATE_ONLY_DEADLINE"
    assert s2["is_all_day"] is False
    assert s2["is_time_confirmed"] is False
    assert s2["end_date"] == "2026-10-10"
    assert s2["start_date"] is None

    # 3. TIME_CONFIRMED_DEADLINE
    t_deadline_payload = {
        "title": "국가장학금 신청 마감",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-10-15",
        "end_datetime": "2026-10-15T18:00:00+09:00",
        "confirmed": True,
    }
    r3 = client.post("/api/v1/schedules", json=t_deadline_payload, headers=headers)
    assert r3.status_code == 201, r3.text
    s3 = r3.json()
    assert s3["schedule_kind"] == "TIME_CONFIRMED_DEADLINE"
    assert s3["is_all_day"] is False
    assert s3["is_time_confirmed"] is True
    assert s3["end_date"] == "2026-10-15"
    assert s3["end_datetime"] == "2026-10-15T09:00:00Z"

    # 4. TIME_CONFIRMED_EVENT
    t_event_payload = {
        "title": "AI 산학 프로젝트 멘토링",
        "course_name": "캡스톤디자인",
        "schedule_kind": "TIME_CONFIRMED_EVENT",
        "start_date": "2026-10-20",
        "end_date": "2026-10-20",
        "start_datetime": "2026-10-20T14:00:00+09:00",
        "end_datetime": "2026-10-20T16:00:00+09:00",
        "confirmed": True,
    }
    r4 = client.post("/api/v1/schedules", json=t_event_payload, headers=headers)
    assert r4.status_code == 201, r4.text
    s4 = r4.json()
    assert s4["schedule_kind"] == "TIME_CONFIRMED_EVENT"
    assert s4["is_all_day"] is False
    assert s4["is_time_confirmed"] is True
    assert s4["start_datetime"] == "2026-10-20T05:00:00Z"
    assert s4["end_datetime"] == "2026-10-20T07:00:00Z"

    # 5. SINGLE_POINT_APPOINTMENT
    appt_payload = {
        "title": "교수님 연구실 상담",
        "schedule_kind": "SINGLE_POINT_APPOINTMENT",
        "start_date": "2026-10-22",
        "start_datetime": "2026-10-22T11:00:00+09:00",
        "confirmed": True,
    }
    r5 = client.post("/api/v1/schedules", json=appt_payload, headers=headers)
    assert r5.status_code == 201, r5.text
    s5 = r5.json()
    assert s5["schedule_kind"] == "SINGLE_POINT_APPOINTMENT"
    assert s5["is_all_day"] is False
    assert s5["is_time_confirmed"] is True
    assert s5["start_date"] == "2026-10-22"
    assert s5["end_date"] is None
    assert s5["end_datetime"] is None

    # 상세 조회
    get_resp = client.get(f"/api/v1/schedules/{s1['id']}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == s1["id"]

    # 목록 조회
    list_resp = client.get("/api/v1/schedules", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 5
    assert len(list_resp.json()["items"]) == 5

    # 수정 (PATCH): title 변경 및 완료 처리
    patch_resp = client.patch(
        f"/api/v1/schedules/{s1['id']}",
        json={"title": "수정된 수강신청 일정", "is_completed": True, "confirmed": True},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["title"] == "수정된 수강신청 일정"
    assert patched["is_completed"] is True
    assert patched["updated_at"] >= s1["updated_at"]

    # 삭제 (DELETE)
    del_resp = client.delete(f"/api/v1/schedules/{s1['id']}", headers=headers)
    assert del_resp.status_code == 204

    # 삭제 후 조회 시 404
    assert client.get(f"/api/v1/schedules/{s1['id']}", headers=headers).status_code == 404
    assert client.get("/api/v1/schedules", headers=headers).json()["total"] == 4


# ── 2. 다중 사용자 격리 (BOLA / IDOR 방어) ──────────────────────────


def test_multi_user_bola_isolation(client: TestClient):
    """계정 A/B 간 완전한 데이터 격리 및 타인 UUID 조회/수정/삭제 404 차단 검증."""
    token_a = register_and_login(client, "user_alice")
    token_b = register_and_login(client, "user_bob")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice의 일정 생성
    payload_a = {
        "title": "Alice의 비공개 상담",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-11-01",
        "confirmed": True,
    }
    resp_a = client.post("/api/v1/schedules", json=payload_a, headers=headers_a)
    assert resp_a.status_code == 201
    sched_a = resp_a.json()

    # Bob의 일정 생성
    payload_b = {
        "title": "Bob의 개인 일정",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-11-02",
        "confirmed": True,
    }
    resp_b = client.post("/api/v1/schedules", json=payload_b, headers=headers_b)
    assert resp_b.status_code == 201
    sched_b = resp_b.json()

    # 1. Alice 목록에 Bob 일정 미포함 확인
    list_a = client.get("/api/v1/schedules", headers=headers_a).json()
    assert list_a["total"] == 1
    assert list_a["items"][0]["id"] == sched_a["id"]
    assert sched_b["id"] not in [it["id"] for it in list_a["items"]]

    # 2. Bob 목록에 Alice 일정 미포함 확인
    list_b = client.get("/api/v1/schedules", headers=headers_b).json()
    assert list_b["total"] == 1
    assert list_b["items"][0]["id"] == sched_b["id"]

    # 3. Alice가 Bob의 UUID로 GET 요청 시 안전한 404 반환
    get_other = client.get(f"/api/v1/schedules/{sched_b['id']}", headers=headers_a)
    assert get_other.status_code == 404
    assert get_other.json()["detail"] == "일정을 찾을 수 없습니다."

    # 존재하지 않는 UUID 조회도 동일한 404 반환
    non_existent = "00000000-0000-0000-0000-000000000000"
    get_none = client.get(f"/api/v1/schedules/{non_existent}", headers=headers_a)
    assert get_none.status_code == 404
    assert get_none.json()["detail"] == get_other.json()["detail"]

    # 4. Alice가 Bob의 UUID로 PATCH 요청 시 404 및 Bob 데이터 불변 검증
    patch_other = client.patch(
        f"/api/v1/schedules/{sched_b['id']}",
        json={"title": "해킹 시도된 제목", "confirmed": True},
        headers=headers_a,
    )
    assert patch_other.status_code == 404

    # Bob의 데이터 및 updated_at이 불변인지 확인
    bob_check = client.get(f"/api/v1/schedules/{sched_b['id']}", headers=headers_b).json()
    assert bob_check["title"] == "Bob의 개인 일정"
    assert bob_check["updated_at"] == sched_b["updated_at"]

    # 5. Alice가 Bob의 UUID로 DELETE 요청 시 404 및 Bob 데이터 삭제 방지 검증
    del_other = client.delete(f"/api/v1/schedules/{sched_b['id']}", headers=headers_a)
    assert del_other.status_code == 404

    # Bob의 일정은 여전히 존재
    assert client.get(f"/api/v1/schedules/{sched_b['id']}", headers=headers_b).status_code == 200


# ── 3. 서버 관리 필드 주입 차단, confirmed 검증, 인증 게이트 ─────────


def test_server_managed_fields_confirmed_and_auth_gate(client: TestClient):
    """서버 관리 필드 주입 차단, confirmed strict 불리언 검증, 미인증 요청 401 검증."""
    token = register_and_login(client, "user_security")
    headers = {"Authorization": f"Bearer {token}"}

    valid_base = {
        "title": "정상 일정",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-10-10",
        "confirmed": True,
    }

    # 1. 서버 관리 필드 주입 시도 -> 422 extra_forbidden
    for injected_field in ["id", "user_id", "created_at", "updated_at", "user_confirmed_at", "is_all_day", "is_time_confirmed"]:
        bad_payload = dict(valid_base)
        bad_payload[injected_field] = "injected_value"
        resp = client.post("/api/v1/schedules", json=bad_payload, headers=headers)
        assert resp.status_code == 422, f"Failed on {injected_field}"
        assert any(err["type"] == "extra_forbidden" for err in resp.json()["detail"])

    # 2. confirmed 누락 -> 422
    no_confirmed = dict(valid_base)
    del no_confirmed["confirmed"]
    r_no_conf = client.post("/api/v1/schedules", json=no_confirmed, headers=headers)
    assert r_no_conf.status_code == 422

    # 3. confirmed: false -> 422
    false_conf = dict(valid_base)
    false_conf["confirmed"] = False
    r_false_conf = client.post("/api/v1/schedules", json=false_conf, headers=headers)
    assert r_false_conf.status_code == 422

    # 4. confirmed: "true" (문자열) -> 422
    str_conf = dict(valid_base)
    str_conf["confirmed"] = "true"
    r_str_conf = client.post("/api/v1/schedules", json=str_conf, headers=headers)
    assert r_str_conf.status_code == 422

    # 5. confirmed: 1 (정수) -> 422
    int_conf = dict(valid_base)
    int_conf["confirmed"] = 1
    r_int_conf = client.post("/api/v1/schedules", json=int_conf, headers=headers)
    assert r_int_conf.status_code == 422

    # 6. 토큰 없는 모든 엔드포인트 401 차단
    assert client.post("/api/v1/schedules", json=valid_base).status_code == 401
    assert client.get("/api/v1/schedules").status_code == 401
    assert client.get("/api/v1/schedules/some-id").status_code == 401
    assert client.patch("/api/v1/schedules/some-id", json={"confirmed": True}).status_code == 401
    assert client.delete("/api/v1/schedules/some-id").status_code == 401


# ── 4. 날짜·시각 엄격한 검증 및 서울 달력 날짜 일치 계약 ─────────────


def test_date_and_time_strict_contract(client: TestClient):
    """naive datetime, epoch 숫자, 서울 자정 변환 불일치, 윤년 오류, 역전 기간 422 거부 검증."""
    token = register_and_login(client, "user_datetime")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. naive datetime 거부
    naive_payload = {
        "title": "Naive 일정",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-10-10",
        "end_datetime": "2026-10-10T18:00:00",  # 타임존 오프셋 누락
        "confirmed": True,
    }
    r_naive = client.post("/api/v1/schedules", json=naive_payload, headers=headers)
    assert r_naive.status_code == 422
    assert "naive" in r_naive.text

    # 2. 날짜 전용 문자열을 datetime에 입력 시 거부
    date_as_dt_payload = {
        "title": "날짜를 일시에 입력",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-10-10",
        "end_datetime": "2026-10-10",
        "confirmed": True,
    }
    r_date_dt = client.post("/api/v1/schedules", json=date_as_dt_payload, headers=headers)
    assert r_date_dt.status_code == 422

    # 3. epoch 숫자 타임스탬프 거부
    epoch_payload = {
        "title": "Epoch 일정",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-10-10",
        "end_datetime": "1728550800",
        "confirmed": True,
    }
    r_epoch = client.post("/api/v1/schedules", json=epoch_payload, headers=headers)
    assert r_epoch.status_code == 422

    # 4. 서울 자정 전후 UTC 변환 및 달력 날짜 불일치 검증
    # 2026-10-01T00:30:00+09:00은 UTC로 2026-09-30T15:30:00Z이지만, 서울 날짜는 2026-10-01임
    # end_date를 UTC 날짜인 2026-09-30으로 적으면 서울 날짜와 불일치하므로 422 반환해야 함!
    mismatch_payload = {
        "title": "서울 날짜 불일치 일정",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-09-30",  # 서울 날짜(2026-10-01)와 불일치!
        "end_datetime": "2026-10-01T00:30:00+09:00",
        "confirmed": True,
    }
    r_mismatch = client.post("/api/v1/schedules", json=mismatch_payload, headers=headers)
    assert r_mismatch.status_code == 422
    assert "서울 기준 날짜" in r_mismatch.text or "일치하지 않습니다" in r_mismatch.text

    # 올바른 서울 날짜(2026-10-01)로 입력하면 성공
    match_payload = {
        "title": "서울 날짜 일치 일정",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-10-01",
        "end_datetime": "2026-10-01T00:30:00+09:00",
        "confirmed": True,
    }
    r_match = client.post("/api/v1/schedules", json=match_payload, headers=headers)
    assert r_match.status_code == 201
    assert r_match.json()["end_datetime"] == "2026-09-30T15:30:00Z"
    assert r_match.json()["end_date"] == "2026-10-01"

    # 5. 윤년 검증 (2026년은 평년 -> 2월 29일 존재하지 않음 -> 422)
    leap_fail_payload = {
        "title": "평년 윤일 오류",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-02-29",
        "confirmed": True,
    }
    r_leap_fail = client.post("/api/v1/schedules", json=leap_fail_payload, headers=headers)
    assert r_leap_fail.status_code == 422

    # 2024년은 윤년 -> 2월 29일 성공
    leap_ok_payload = {
        "title": "윤년 정상 일정",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2024-02-29",
        "confirmed": True,
    }
    r_leap_ok = client.post("/api/v1/schedules", json=leap_ok_payload, headers=headers)
    assert r_leap_ok.status_code == 201

    # 6. 역전 기간 거부
    rev_date_payload = {
        "title": "역전 날짜",
        "schedule_kind": "ALL_DAY_EVENT",
        "start_date": "2026-10-05",
        "end_date": "2026-10-01",
        "confirmed": True,
    }
    r_rev_date = client.post("/api/v1/schedules", json=rev_date_payload, headers=headers)
    assert r_rev_date.status_code == 422

    rev_time_payload = {
        "title": "역전 일시",
        "schedule_kind": "TIME_CONFIRMED_EVENT",
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "start_datetime": "2026-10-01T15:00:00+09:00",
        "end_datetime": "2026-10-01T14:00:00+09:00",  # 시작이 종료보다 늦음
        "confirmed": True,
    }
    r_rev_time = client.post("/api/v1/schedules", json=rev_time_payload, headers=headers)
    assert r_rev_time.status_code == 422

    # 7. 금지된 필드 포함 거부 (예: DATE_ONLY_DEADLINE에 start_date 포함)
    bad_fields_payload = {
        "title": "금지 필드 포함",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
        "confirmed": True,
    }
    r_bad_fields = client.post("/api/v1/schedules", json=bad_fields_payload, headers=headers)
    assert r_bad_fields.status_code == 422


# ── 5. PATCH 상세 의미 (생략 보존, 명시적 null, 유형 전환, 원자성) ─────


def test_patch_semantics_and_atomicity(client: TestClient):
    """PATCH 생략 vs 명시적 null, non-nullable 보호, 유형 전환 잔여 필드 검증, 원자적 롤백."""
    token = register_and_login(client, "user_patch")
    headers = {"Authorization": f"Bearer {token}"}

    # 기본 TIME_CONFIRMED_EVENT 생성
    create_payload = {
        "title": "원래 행사",
        "description": "원래 상세 설명",
        "course_name": "원래 과목",
        "schedule_kind": "TIME_CONFIRMED_EVENT",
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "start_datetime": "2026-10-01T10:00:00+09:00",
        "end_datetime": "2026-10-01T12:00:00+09:00",
        "confirmed": True,
    }
    resp = client.post("/api/v1/schedules", json=create_payload, headers=headers)
    assert resp.status_code == 201
    item = resp.json()
    sched_id = item["id"]

    # 1. confirmed만 있고 변경 필드가 없는 경우 -> 422
    r_only_conf = client.patch(f"/api/v1/schedules/{sched_id}", json={"confirmed": True}, headers=headers)
    assert r_only_conf.status_code == 422

    # 2. 필수/non-nullable 필드에 명시적 null 전달 시 -> 422
    for non_null in ["title", "schedule_kind", "timezone", "priority", "is_completed"]:
        r_null_bad = client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={non_null: None, "confirmed": True},
            headers=headers,
        )
        assert r_null_bad.status_code == 422, f"Failed on {non_null}"

    # 3. nullable 필드(description, course_name) 명시적 null -> 정상 비우기
    r_null_ok = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"description": None, "course_name": None, "confirmed": True},
        headers=headers,
    )
    assert r_null_ok.status_code == 200
    patched1 = r_null_ok.json()
    assert patched1["description"] is None
    assert patched1["course_name"] is None
    assert patched1["title"] == "원래 행사"  # 미전송 필드 보존

    # 4. 유형 전환 시 잔여 금지 필드 미삭제 시 거부:
    # TIME_CONFIRMED_EVENT에서 ALL_DAY_EVENT로 변경할 때,
    # start_datetime과 end_datetime을 null로 비우지 않으면 422 거부!
    r_bad_switch = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"schedule_kind": "ALL_DAY_EVENT", "confirmed": True},
        headers=headers,
    )
    assert r_bad_switch.status_code == 422
    assert "start_datetime과 end_datetime이 null이어야 합니다" in r_bad_switch.text

    # 검증 실패 후 DB 상태 불변 확인 (원자적 롤백)
    check_unchanged = client.get(f"/api/v1/schedules/{sched_id}", headers=headers).json()
    assert check_unchanged["schedule_kind"] == "TIME_CONFIRMED_EVENT"
    assert check_unchanged["start_datetime"] == "2026-10-01T01:00:00Z"

    # 올바르게 이전 금지 필드를 null로 명시하고 유형 변경
    r_good_switch = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={
            "schedule_kind": "ALL_DAY_EVENT",
            "start_datetime": None,
            "end_datetime": None,
            "confirmed": True,
        },
        headers=headers,
    )
    assert r_good_switch.status_code == 200
    patched2 = r_good_switch.json()
    assert patched2["schedule_kind"] == "ALL_DAY_EVENT"
    assert patched2["is_all_day"] is True
    assert patched2["is_time_confirmed"] is False
    assert patched2["start_datetime"] is None
    assert patched2["end_datetime"] is None


# ── 6. 목록 및 캘린더 조회 필터링, 정렬, 페이지네이션 ────────────────


def test_calendar_and_list_filtering(client: TestClient):
    """월 경계 기간 일정 겹침, 단일일 마감/약속 필터링, 정렬 및 total 검증."""
    token = register_and_login(client, "user_calendar")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. 9월 말 ~ 10월 초에 걸친 기간 행사 (2026-09-28 ~ 2026-10-03)
    client.post(
        "/api/v1/schedules",
        json={
            "title": "9-10월 축제 기간",
            "schedule_kind": "ALL_DAY_EVENT",
            "start_date": "2026-09-28",
            "end_date": "2026-10-03",
            "confirmed": True,
        },
        headers=headers,
    )

    # 2. 10월 중순 단일일 마감 (2026-10-15)
    client.post(
        "/api/v1/schedules",
        json={
            "title": "10월 과제 마감",
            "schedule_kind": "DATE_ONLY_DEADLINE",
            "end_date": "2026-10-15",
            "priority": "HIGH",
            "confirmed": True,
        },
        headers=headers,
    )

    # 3. 10월 하순 단일 약속 (2026-10-25)
    client.post(
        "/api/v1/schedules",
        json={
            "title": "10월 특강 약속",
            "schedule_kind": "SINGLE_POINT_APPOINTMENT",
            "start_date": "2026-10-25",
            "start_datetime": "2026-10-25T14:00:00+09:00",
            "priority": "LOW",
            "is_completed": True,
            "confirmed": True,
        },
        headers=headers,
    )

    # 4. 11월 일정 (2026-11-05)
    client.post(
        "/api/v1/schedules",
        json={
            "title": "11월 수능 휴교",
            "schedule_kind": "DATE_ONLY_DEADLINE",
            "end_date": "2026-11-05",
            "confirmed": True,
        },
        headers=headers,
    )

    # A. date_from만 단독 제공 시 422
    assert client.get("/api/v1/schedules?date_from=2026-10-01", headers=headers).status_code == 422
    # B. date_from > date_to 시 422
    assert client.get("/api/v1/schedules?date_from=2026-10-31&date_to=2026-10-01", headers=headers).status_code == 422

    # C. 10월 한 달 조회 (2026-10-01 ~ 2026-10-31)
    # - 9-10월 축제(9.28~10.3)는 10월과 겹치므로 포함!
    # - 10월 과제(10.15) 포함!
    # - 10월 특강(10.25) 포함!
    # - 11월 일정(11.05) 제외!
    oct_resp = client.get("/api/v1/schedules?date_from=2026-10-01&date_to=2026-10-31", headers=headers)
    assert oct_resp.status_code == 200
    oct_data = oct_resp.json()
    assert oct_data["total"] == 3
    titles = [it["title"] for it in oct_data["items"]]
    assert titles == ["9-10월 축제 기간", "10월 과제 마감", "10월 특강 약속"]

    # D. 완료 여부 필터
    comp_resp = client.get("/api/v1/schedules?is_completed=true", headers=headers)
    assert comp_resp.status_code == 200
    assert comp_resp.json()["total"] == 1
    assert comp_resp.json()["items"][0]["title"] == "10월 특강 약속"

    # E. 중요도 필터
    high_resp = client.get("/api/v1/schedules?priority=HIGH", headers=headers)
    assert high_resp.status_code == 200
    assert high_resp.json()["total"] == 1
    assert high_resp.json()["items"][0]["title"] == "10월 과제 마감"

    # F. 페이지네이션 (limit=2, offset=1)
    page_resp = client.get("/api/v1/schedules?limit=2&offset=1", headers=headers)
    assert page_resp.status_code == 200
    page_data = page_resp.json()
    assert page_data["total"] == 4
    assert len(page_data["items"]) == 2
    assert page_data["items"][0]["title"] == "10월 과제 마감"
    assert page_data["items"][1]["title"] == "10월 특강 약속"


# ── 7. SQLite v1 -> v2 마이그레이션 데이터 보존 검증 ────────────────


def test_v1_to_v2_migration_preserves_users_and_sessions(tmp_path: Path):
    """v1 상태 DB에 사용자와 세션을 생성한 후 v2 업그레이드 시 데이터 100% 보존 검증."""
    mig_db = tmp_path / "migration_preserve.db"
    conn = get_db_connection(mig_db)

    # 1. v1 마이그레이션만 수동 적용
    for sql in MIGRATIONS[1]:
        conn.execute(sql)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?);", (datetime.now(timezone.utc).isoformat(),))

    # v1 사용자 및 세션 등록
    user_id = "v1-user-id-12345"
    session_id = "v1-session-id-67890"
    token = "v1-test-opaque-session-token-valid-abc"
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = "2099-01-01T00:00:00+00:00"

    real_password = "RealPassword123!"
    real_pw_hash = hash_password(real_password)

    conn.execute(
        "INSERT INTO users (id, username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
        (user_id, "v1_student", real_pw_hash, now_iso, now_iso),
    )
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, user_id, token_hash, now_iso, future_iso),
    )
    conn.close()

    # 2. v2 마이그레이션 실행 (init_db 호출)
    applied_count = init_db(mig_db)
    assert applied_count == 1  # v2 1개 버전 적용

    # 3. v1 데이터 온전성 및 v2 테이블 존재 확인
    conn2 = get_db_connection(mig_db)
    versions = {r["version"] for r in conn2.execute("SELECT version FROM schema_migrations;").fetchall()}
    assert versions == {1, 2}

    user_row = conn2.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone()
    assert user_row is not None
    assert user_row["username"] == "v1_student"
    assert user_row["password_hash"] == real_pw_hash

    session_row = conn2.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    assert session_row is not None
    assert session_row["token_hash"] == token_hash

    # personal_schedules 테이블 생성 확인
    sched_tables = [r["name"] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personal_schedules';").fetchall()]
    assert len(sched_tables) == 1
    conn2.close()

    # 4. FastAPI TestClient로 이전 세션 토큰 검증 및 기존 비밀번호로 재로그인 검증
    orig_path = config.AUTH_DB_PATH
    orig_prewarm = config.PREWARM_RAG_ON_STARTUP
    config.AUTH_DB_PATH = str(mig_db)
    config.PREWARM_RAG_ON_STARTUP = False

    orig_overrides = dict(app.dependency_overrides)

    def override_mig_db() -> Generator[sqlite3.Connection, None, None]:
        c = get_db_connection(mig_db)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_mig_db

    try:
        with TestClient(app) as test_client:
            # v1 세션 토큰으로 본인 정보 조회 성공
            me_resp = test_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me_resp.status_code == 200
            assert me_resp.json()["username"] == "v1_student"

            # 기존 평문 비밀번호로 재로그인 성공 (실제 bcrypt 해시 검증 통과)
            relogin_resp = test_client.post(
                "/api/v1/auth/login",
                json={"username": "v1_student", "password": real_password},
            )
            assert relogin_resp.status_code == 200
            new_token = relogin_resp.json()["access_token"]
            assert len(new_token) > 20

            # 새로 발급된 토큰으로 신규 개인 일정 생성 성공
            create_resp = test_client.post(
                "/api/v1/schedules",
                json={
                    "title": "v1 사용자가 생성한 첫 일정",
                    "schedule_kind": "DATE_ONLY_DEADLINE",
                    "end_date": "2026-10-30",
                    "confirmed": True,
                },
                headers={"Authorization": f"Bearer {new_token}"},
            )
            assert create_resp.status_code == 201
            assert create_resp.json()["user_id"] == user_id

        # 5. init_db 재실행 시 멱등성 (적용 0건, 데이터 불변)
        assert init_db(mig_db) == 0
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)
        config.AUTH_DB_PATH = orig_path
        config.PREWARM_RAG_ON_STARTUP = orig_prewarm


def test_v2_migration_synthetic_failure_rollbacks_cleanly(tmp_path: Path):
    """v2 마이그레이션 도중 예외 발생 시 전체 롤백 및 v1 사용자/세션 데이터 보존 검증."""
    mig_db = tmp_path / "migration_fail.db"
    conn = get_db_connection(mig_db)

    # v1 적용 및 데이터(사용자 및 유효 세션) 삽입
    for sql in MIGRATIONS[1]:
        conn.execute(sql)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?);", (now_iso,))
    user_id = "v1-fail-test-user"
    raw_password = "Pass123!"
    pw_hash = hash_password(raw_password)
    session_id = "v1-fail-test-session"
    raw_token = "v1-opaque-token-for-synthetic-failure-rollback"
    token_hash = hash_session_token(raw_token)
    future_iso = "2099-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO users (id, username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
        (user_id, "v1_survivor", pw_hash, now_iso, now_iso),
    )
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?);",
        (session_id, user_id, token_hash, now_iso, future_iso, None),
    )
    conn.commit()

    # 실패 전 원본 사용자 및 세션 레코드 스냅샷
    user_before = dict(conn.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone())
    session_before = dict(conn.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone())
    conn.close()

    # v2 SQL 목록에 의도적 문법 오류 주입
    orig_v2 = list(MIGRATIONS[2])
    bad_v2 = list(MIGRATIONS[2])
    bad_v2.append("CREATE TABLE SYNTAX_ERROR_FAIL (;")
    MIGRATIONS[2] = bad_v2

    try:
        # init_db 실행 시 실패해야 함
        with pytest.raises(sqlite3.OperationalError):
            init_db(mig_db)

        # 검증: 트랜잭션 롤백으로 schema_migrations에 2가 없고, v2 테이블/인덱스도 롤백되어 없어야 함
        conn_check = get_db_connection(mig_db)
        versions = {r["version"] for r in conn_check.execute("SELECT version FROM schema_migrations;").fetchall()}
        assert versions == {1}

        tables = [r["name"] for r in conn_check.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "personal_schedules" not in tables
        assert "SYNTAX_ERROR_FAIL" not in tables
        assert "users" in tables
        assert "sessions" in tables

        indices = [r["name"] for r in conn_check.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()]
        assert not any("schedules" in idx for idx in indices)

        # 사용자 및 세션 레코드 불변 확인 (컬럼 값 100% 일치)
        user_after_fail = dict(conn_check.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone())
        session_after_fail = dict(conn_check.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone())
        assert user_after_fail == user_before
        assert session_after_fail == session_before
        conn_check.close()
    finally:
        MIGRATIONS[2] = orig_v2

    # 정상 v2로 복구 후 재실행 시 성공해야 함
    assert init_db(mig_db) == 1
    conn_ok = get_db_connection(mig_db)
    versions_ok = {r["version"] for r in conn_ok.execute("SELECT version FROM schema_migrations;").fetchall()}
    assert versions_ok == {1, 2}
    tables_ok = [r["name"] for r in conn_ok.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "personal_schedules" in tables_ok

    # 사용자 및 세션 데이터가 온전히 유지되었는지 재확인
    user_after_ok = dict(conn_ok.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone())
    session_after_ok = dict(conn_ok.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone())
    assert user_after_ok == user_before
    assert session_after_ok == session_before
    conn_ok.close()

    # 정상 재적용 후 기존 v1 세션 토큰으로 인증 성공 및 새 일정 생성 검증
    orig_path = config.AUTH_DB_PATH
    orig_prewarm = config.PREWARM_RAG_ON_STARTUP
    config.AUTH_DB_PATH = str(mig_db)
    config.PREWARM_RAG_ON_STARTUP = False
    orig_overrides = dict(app.dependency_overrides)

    def override_mig_db() -> Generator[sqlite3.Connection, None, None]:
        c = get_db_connection(mig_db)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_mig_db

    try:
        with TestClient(app) as test_client:
            # 1. 기존 v1 세션 토큰으로 인증 확인 (/api/v1/auth/me)
            me_resp = test_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
            assert me_resp.status_code == 200
            assert me_resp.json()["username"] == "v1_survivor"
            assert me_resp.json()["id"] == user_id

            # 2. 기존 비밀번호로 재로그인 성공
            login_resp = test_client.post(
                "/api/v1/auth/login",
                json={"username": "v1_survivor", "password": raw_password},
            )
            assert login_resp.status_code == 200
            assert "access_token" in login_resp.json()

            # 3. 기존 세션 토큰으로 v2 신규 개인 일정 등록 성공
            sched_resp = test_client.post(
                "/api/v1/schedules",
                json={
                    "title": "롤백 복구 후 생성된 일정",
                    "schedule_kind": "DATE_ONLY_DEADLINE",
                    "end_date": "2026-12-31",
                    "confirmed": True,
                },
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert sched_resp.status_code == 201
            assert sched_resp.json()["user_id"] == user_id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)
        config.AUTH_DB_PATH = orig_path
        config.PREWARM_RAG_ON_STARTUP = orig_prewarm


# ── 8. 별도 서브프로세스 종료/재시작 영속성 검증 ──────────────────────


def test_subprocess_schedule_persistence(tmp_path: Path):
    """별도 OS 프로세스 1에서 일정 생성 후 프로세스 2에서 조회 및 수정 성공 증명."""
    db_file = tmp_path / "proc_sched.db"

    # 프로세스 1: 사용자 등록, 로그인, 일정 생성 후 토큰과 일정 ID 출력
    script_p1 = f"""
import os, sys
os.environ["AUTH_DB_PATH"] = {repr(str(db_file))}
os.environ["PREWARM_RAG_ON_STARTUP"] = "false"
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    r1 = client.post("/api/v1/auth/register", json={{"username": "proc_user", "password": "Password123!"}})
    assert r1.status_code == 201
    r2 = client.post("/api/v1/auth/login", json={{"username": "proc_user", "password": "Password123!"}})
    assert r2.status_code == 200
    token = r2.json()["access_token"]

    r3 = client.post(
        "/api/v1/schedules",
        json={{
            "title": "프로세스 1에서 생성한 일정",
            "schedule_kind": "DATE_ONLY_DEADLINE",
            "end_date": "2026-11-20",
            "confirmed": True,
        }},
        headers={{"Authorization": f"Bearer {{token}}"}},
    )
    assert r3.status_code == 201
    sched_id = r3.json()["id"]
    print(f"OUTPUT:{{token}}:{{sched_id}}")
"""
    res1 = subprocess.run([sys.executable, "-c", script_p1], capture_output=True, text=True, check=True)
    out_line = [l for l in res1.stdout.splitlines() if l.startswith("OUTPUT:")][0]
    _, token, sched_id = out_line.split(":")

    # 프로세스 2: 별도 신규 프로세스로 기동하여 이전 프로세스의 세션 토큰으로 일정 조회 및 수정
    script_p2 = f"""
import os, sys
os.environ["AUTH_DB_PATH"] = {repr(str(db_file))}
os.environ["PREWARM_RAG_ON_STARTUP"] = "false"
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    headers = {{"Authorization": "Bearer {token}"}}
    # 조회
    r1 = client.get("/api/v1/schedules/{sched_id}", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["title"] == "프로세스 1에서 생성한 일정"

    # 수정
    r2 = client.patch(
        "/api/v1/schedules/{sched_id}",
        json={{"title": "프로세스 2에서 수정한 일정", "confirmed": True}},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "프로세스 2에서 수정한 일정"
    print("SUBPROCESS_SCHEDULE_PERSISTENCE_SUCCESS")
"""
    res2 = subprocess.run([sys.executable, "-c", script_p2], capture_output=True, text=True, check=True)
    assert "SUBPROCESS_SCHEDULE_PERSISTENCE_SUCCESS" in res2.stdout


# ── 9. 동시 PATCH 데이터 유실 방지 및 수정/삭제 경합 검증 ─────────────


def test_concurrent_patch_lost_update_prevention(client: TestClient):
    """동일 일정에 대해 title과 description을 동시에 PATCH할 때 데이터 유실 없이 둘 다 반영됨을 검증."""
    import concurrent.futures
    import threading

    token = register_and_login(client, "user_concurrent")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/v1/schedules",
        json={
            "title": "original title",
            "description": None,
            "schedule_kind": "DATE_ONLY_DEADLINE",
            "end_date": "2026-11-15",
            "confirmed": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    sched_id = create_res.json()["id"]

    start_barrier = threading.Barrier(2)

    def patch_title():
        start_barrier.wait()
        return client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"title": "concurrently updated title", "confirmed": True},
            headers=headers,
        )

    def patch_description():
        start_barrier.wait()
        return client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"description": "concurrently updated description", "confirmed": True},
            headers=headers,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(patch_title)
        f2 = executor.submit(patch_description)
        r1 = f1.result(timeout=10)
        r2 = f2.result(timeout=10)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    # 최종 상태 조회: title과 description 둘 다 보존되어 있어야 함!
    final_resp = client.get(f"/api/v1/schedules/{sched_id}", headers=headers)
    assert final_resp.status_code == 200
    final_data = final_resp.json()
    assert final_data["title"] == "concurrently updated title"
    assert final_data["description"] == "concurrently updated description"


def test_concurrent_patch_and_delete_race(client: TestClient):
    """PATCH와 DELETE 동시 경합 시 500 오류 없이 안전하게 200/204 또는 404로 처리됨을 검증."""
    import concurrent.futures
    import threading

    token = register_and_login(client, "user_race")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/v1/schedules",
        json={
            "title": "race schedule",
            "schedule_kind": "DATE_ONLY_DEADLINE",
            "end_date": "2026-11-15",
            "confirmed": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    sched_id = create_res.json()["id"]

    barrier = threading.Barrier(2)

    def do_patch():
        barrier.wait()
        return client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"title": "race patched", "confirmed": True},
            headers=headers,
        )

    def do_delete():
        barrier.wait()
        return client.delete(f"/api/v1/schedules/{sched_id}", headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_patch = executor.submit(do_patch)
        f_del = executor.submit(do_delete)
        r_patch = f_patch.result(timeout=10)
        r_del = f_del.result(timeout=10)

    assert r_patch.status_code in (200, 404)
    assert r_del.status_code in (204, 404)


# ── 10. 소수점 초 보존, 재검증 불변식 유지 및 변환 오버플로우 안전 처리 ──


def test_datetime_fractional_precision_and_overflow(client: TestClient):
    """소수점 초 보존 및 재검증 불변식 유지, 변환 범위 초과 422 안전 처리 검증."""
    token = register_and_login(client, "user_frac")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Codex 재현 입력: 마이크로초 포함 일정 등록
    frac_payload = {
        "title": "fractional",
        "schedule_kind": "TIME_CONFIRMED_EVENT",
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "start_datetime": "2026-10-01T10:00:00.100000+09:00",
        "end_datetime": "2026-10-01T10:00:00.900000+09:00",
        "confirmed": True,
    }
    post_res = client.post("/api/v1/schedules", json=frac_payload, headers=headers)
    assert post_res.status_code == 201, post_res.text
    data = post_res.json()
    assert data["start_datetime"] == "2026-10-01T01:00:00.100000Z"
    assert data["end_datetime"] == "2026-10-01T01:00:00.900000Z"
    sched_id = data["id"]

    # 2. 제목만 PATCH -> 시간 불변식이 깨지지 않고 정상 200 반환!
    patch_res = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"title": "fractional title updated", "confirmed": True},
        headers=headers,
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["title"] == "fractional title updated"
    assert patch_res.json()["start_datetime"] == "2026-10-01T01:00:00.100000Z"
    assert patch_res.json()["end_datetime"] == "2026-10-01T01:00:00.900000Z"

    # 3. 소수점 초까지 동일하여 start == end가 되는 경우 422 거부
    equal_subsec = {
        "title": "equal subsecond",
        "schedule_kind": "TIME_CONFIRMED_EVENT",
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "start_datetime": "2026-10-01T10:00:00.500000+09:00",
        "end_datetime": "2026-10-01T10:00:00.500000+09:00",
        "confirmed": True,
    }
    r_eq = client.post("/api/v1/schedules", json=equal_subsec, headers=headers)
    assert r_eq.status_code == 422

    # 4. 연도 범위 초과 및 타임존 변환 오버플로우 422 거부 (500 방지)
    overflow_payload = {
        "title": "overflow year",
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "0001-01-01",
        "end_datetime": "0001-01-01T00:00:00+09:00",
        "confirmed": True,
    }
    r_of = client.post("/api/v1/schedules", json=overflow_payload, headers=headers)
    assert r_of.status_code == 422


# ── 11. source_url 엄격한 호스트, 포트, 제어문자 및 스키마 검증 ──────

INVALID_SOURCE_URL_CASES = [
    ("https://example.com:abc", "비숫자 포트"),
    ("https://example.com:99999", "65535 초과 포트"),
    ("http://localhost:abc", "localhost 비숫자 포트"),
    ("https://exa\tmple.com", "탭(\\t) 제어문자 포함"),
    ("https://example.com/line\nbreak", "줄바꿈(\\n) 제어문자 포함"),
    ("https://example.com/cr\rbreak", "캐리지리턴(\\r) 제어문자 포함"),
    ("https://example.com:0", "포트 0 (1~65535 범위 미충족)"),
    ("https://example.com:", "포트 번호 누락"),
    ("https://", "호스트 누락"),
    ("https://not a host", "호스트 내 공백"),
    ("http://?query", "호스트 없는 쿼리"),
    ("ftp://example.com", "비 http/https 스키마"),
    ("javascript:alert(1)", "javascript 스키마"),
    ("http://", "호스트 누락"),
    ("https://hansung.ac.kr/path with space", "경로 내 공백"),
]

VALID_SOURCE_URL_CASES = [
    ("https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do", "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do", "표준 https URL"),
    ("http://localhost:8000/docs", "http://localhost:8000/docs", "localhost 유효 포트"),
    ("http://127.0.0.1:8080/api", "http://127.0.0.1:8080/api", "IPv4 유효 포트"),
    ("https://example.com:443/test?a=1&b=2#frag", "https://example.com:443/test?a=1&b=2#frag", "표준 포트 쿼리/프래그먼트"),
    ("https://example.com:65535", "https://example.com:65535", "최대 포트(65535) 경계값"),
    (None, None, "null 정책"),
    ("", None, "빈 문자열 정책"),
]


@pytest.mark.parametrize("bad_url, desc", INVALID_SOURCE_URL_CASES)
def test_source_url_invalid_create_and_patch_rejected(client: TestClient, bad_url: str, desc: str):
    """비정상 URL(잘못된 포트, 제어문자 등)의 CREATE/PATCH 422 거부 및 실패 시 레코드 불변 검증."""
    token = register_and_login(client, f"u_bad_{hash(bad_url) & 0xffffff}")
    headers = {"Authorization": f"Bearer {token}"}

    base = {
        "title": f"유효하지 않은 URL 테스트 ({desc})",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-11-20",
        "confirmed": True,
    }

    # 1. CREATE 시 비정상 URL 전송 -> 422 Unprocessable Entity (500 오류 금지)
    r_post = client.post("/api/v1/schedules", json=dict(base, source_url=bad_url), headers=headers)
    assert r_post.status_code == 422, f"Expected 422 for POST ({desc}): '{bad_url}', got {r_post.status_code}"

    # 2. 유효한 일정 정상 생성 후 원본 스냅샷 기록
    r_ok = client.post(
        "/api/v1/schedules",
        json=dict(base, source_url="https://www.hansung.ac.kr/bbs/1"),
        headers=headers,
    )
    assert r_ok.status_code == 201
    initial_sched = r_ok.json()
    sched_id = initial_sched["id"]

    # 3. PATCH 시 비정상 URL 전송 -> 422 Unprocessable Entity (500 오류 금지)
    r_patch = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"source_url": bad_url, "confirmed": True},
        headers=headers,
    )
    assert r_patch.status_code == 422, f"Expected 422 for PATCH ({desc}): '{bad_url}', got {r_patch.status_code}"

    # 4. 검증: 잘못된 PATCH 실패 후 기존 레코드(source_url, updated_at 등)의 완전 불변 검증
    r_get = client.get(f"/api/v1/schedules/{sched_id}", headers=headers)
    assert r_get.status_code == 200
    current_sched = r_get.json()
    assert current_sched["source_url"] == initial_sched["source_url"] == "https://www.hansung.ac.kr/bbs/1"
    assert current_sched["updated_at"] == initial_sched["updated_at"]
    assert current_sched == initial_sched


@pytest.mark.parametrize("good_url, expected_url, desc", VALID_SOURCE_URL_CASES)
def test_source_url_valid_and_empty_policy(client: TestClient, good_url: str | None, expected_url: str | None, desc: str):
    """정상 URL(포트 포함, localhost, IPv4) 및 null/빈 값 처리 정책 검증."""
    token = register_and_login(client, f"u_good_{hash(str(good_url)) & 0xffffff}")
    headers = {"Authorization": f"Bearer {token}"}

    base = {
        "title": f"유효한 URL 테스트 ({desc})",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-11-20",
        "confirmed": True,
    }

    # CREATE 시 정상 생성 및 source_url 값 확인
    r_post = client.post("/api/v1/schedules", json=dict(base, source_url=good_url), headers=headers)
    assert r_post.status_code == 201
    assert r_post.json()["source_url"] == expected_url
    sched_id = r_post.json()["id"]

    # PATCH 시 수정 및 source_url 값 확인
    r_patch = client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"source_url": good_url, "confirmed": True},
        headers=headers,
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["source_url"] == expected_url


def test_source_url_strict_validation(client: TestClient):
    """source_url의 종합 유효성 검증 (순차 엔드투엔드 시나리오 보존)."""
    token = register_and_login(client, "user_url_test")
    headers = {"Authorization": f"Bearer {token}"}

    base = {
        "title": "URL 검증 일정",
        "schedule_kind": "DATE_ONLY_DEADLINE",
        "end_date": "2026-11-20",
        "confirmed": True,
    }

    bad_urls = [case[0] for case in INVALID_SOURCE_URL_CASES]
    for bad in bad_urls:
        p = dict(base, source_url=bad)
        r_post = client.post("/api/v1/schedules", json=p, headers=headers)
        assert r_post.status_code == 422, f"Expected 422 for POST with URL '{bad}', got {r_post.status_code}"

    # 정상 URL로 생성
    good_p = dict(base, source_url="https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do")
    r_ok = client.post("/api/v1/schedules", json=good_p, headers=headers)
    assert r_ok.status_code == 201
    sched_id = r_ok.json()["id"]

    # PATCH 시 비정상 URL 거부
    for bad in bad_urls:
        r_patch = client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"source_url": bad, "confirmed": True},
            headers=headers,
        )
        assert r_patch.status_code == 422, f"Expected 422 for PATCH with URL '{bad}'"

    # PATCH 시 정상 URL 및 localhost, null 허용
    for good_url, expected_url, _ in VALID_SOURCE_URL_CASES:
        r_good = client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"source_url": good_url, "confirmed": True},
            headers=headers,
        )
        assert r_good.status_code == 200
        assert r_good.json()["source_url"] == expected_url

