"""
tests/test_ui_and_e2e_flow.py

CampusMate R3 & R5 통합 UI 정적 서빙 및 End-to-End 전체 흐름 검증 테스트 슈트.
1. 프론트엔드 정적 서빙 (GET / 및 에셋 200 OK)
2. E2E 전체 라이프사이클:
   - 계정 등록 및 로그인 -> 토큰 획득
   - 공지/자연어 텍스트로 /api/v1/schedules/extract 호출 (Zero-Auto-Save 증명)
   - 사용자 확인 모달을 통한 /api/v1/schedules 등록 (confirmed: true)
   - /api/v1/schedules 목록 및 캘린더 조회
   - PATCH /api/v1/schedules/{id} 완료 상태 토글
   - DELETE /api/v1/schedules/{id} 삭제 및 404 재확인
3. 다회차/다단계 일정 추출 시 사용자 선택적 확정 및 미승인 후보 미저장(Zero-Auto-Save) 검증
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

import config
from backend.db.database import get_db, get_db_connection
from backend.main import app


@pytest.fixture
def isolated_env(tmp_path: Path) -> Generator[tuple[TestClient, Path], None, None]:
    """임시 SQLite DB로 lifespan과 get_db 의존성을 격리하는 픽스처."""
    test_db = tmp_path / "test_e2e_ui.db"
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


# ── 1. 정적 서빙 검증 ─────────────────────────────────────────


def test_frontend_static_serving_root(client: TestClient):
    """GET / 호출 시 frontend-web/dist/index.html이 정상 200 OK로 서빙된다."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert '<div id="root">' in resp.text
    assert "CampusMate" in resp.text or "campusrag" in resp.text.lower() or "한성대" in resp.text


# ── 2. E2E 전체 라이프사이클 흐름 검증 ─────────────────────────


def test_e2e_extract_confirm_crud_flow(client: TestClient, db_path: Path):
    """
    R3 & R5 핵심 E2E 시나리오:
    1. 계정 등록 및 로그인
    2. 공지 본문에서 /api/v1/schedules/extract 호출 (Zero-Auto-Save 확인: DB 레코드 0건 유지)
    3. 추출된 후보를 사용자가 확인/수정하여 /api/v1/schedules로 확정 등록 (confirmed: true)
    4. /api/v1/schedules 목록에서 등록된 일정 조회 확인
    5. PATCH /api/v1/schedules/{id}로 완료 여부 토글 (is_completed: true)
    6. DELETE /api/v1/schedules/{id}로 일정 삭제
    7. GET 단건 조회 시 404 및 목록 0건 확인
    """
    # [Step 1] 사용자 등록 및 로그인
    username = "e2e_student"
    password = "Password123!"

    reg_resp = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert reg_resp.status_code == 201

    login_resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # [Step 2] 공지 텍스트로 일정 후보 추출 (Zero-Auto-Save 검증)
    notice_text = "2026학년도 2학기 졸업가운 대여 신청은 2026년 9월 30일(수) 18:00까지 종합정보시스템에서 접수받습니다."
    source_url = "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do"

    extract_resp = client.post(
        "/api/v1/schedules/extract",
        headers=headers,
        json={"text": notice_text, "source_url": source_url},
    )
    assert extract_resp.status_code == 200
    extract_data = extract_resp.json()

    assert extract_data["total_candidates"] == 1
    assert extract_data["requires_user_confirmation"] is True

    candidate = extract_data["candidates"][0]
    assert candidate["title"] == "졸업가운 대여 신청 마감"
    assert candidate["end_date"] == "2026-09-30T18:00:00+09:00"
    assert candidate["requires_user_confirmation"] is True

    # Zero-Auto-Save 검증: 추출 후 DB 레코드 개수는 여전히 0건이어야 함
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM personal_schedules")
    assert cur.fetchone()[0] == 0, "추출만 수행했을 때 DB에 데이터가 자동 저장되면 안 됩니다."
    conn.close()

    # [Step 3] 사용자 확인 모달을 거쳐 확정 등록 (confirmed: true)
    create_payload = {
        "title": candidate["title"],
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-09-30",
        "end_datetime": "2026-09-30T18:00:00+09:00",
        "timezone": "Asia/Seoul",
        "priority": "HIGH",
        "source_url": source_url,
        "source_title": "졸업가운 대여 신청 안내",
        "extracted_quote": candidate["source_quote"],
        "confirmed": True,  # Zero-Auto-Save 확인 플래그
    }

    create_resp = client.post("/api/v1/schedules", headers=headers, json=create_payload)
    assert create_resp.status_code == 201
    created_schedule = create_resp.json()
    schedule_id = created_schedule["id"]
    assert created_schedule["title"] == "졸업가운 대여 신청 마감"
    assert created_schedule["is_completed"] is False
    assert created_schedule["priority"] == "HIGH"

    # DB에 정확히 1건 저장되었음을 확인
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM personal_schedules")
    assert cur.fetchone()[0] == 1
    conn.close()

    # [Step 4] 목록 및 캘린더 조회
    list_resp = client.get("/api/v1/schedules", headers=headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] == 1
    assert list_data["items"][0]["id"] == schedule_id

    # [Step 5] 완료 상태 토글 (PATCH)
    patch_resp = client.patch(
        f"/api/v1/schedules/{schedule_id}",
        headers=headers,
        json={"is_completed": True, "confirmed": True},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_completed"] is True

    # [Step 6] 일정 삭제 (DELETE)
    del_resp = client.delete(f"/api/v1/schedules/{schedule_id}", headers=headers)
    assert del_resp.status_code == 204

    # [Step 7] 삭제 후 404 및 목록 비어있음 확인
    get_del = client.get(f"/api/v1/schedules/{schedule_id}", headers=headers)
    assert get_del.status_code == 404

    list_after = client.get("/api/v1/schedules", headers=headers)
    assert list_after.json()["total"] == 0


# ── 3. 복합 다단계 일정의 선택적 승인 (Zero-Auto-Save) ─────────


def test_selective_confirmation_zero_auto_save(client: TestClient, db_path: Path):
    """2단계 순차 마감 공지 추출 시 사용자가 선택한 1건만 등록되고 미선택 후보는 저장되지 않는다."""
    # 로그인
    reg = client.post("/api/v1/auth/register", json={"username": "selective_user", "password": "Password123!"})
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": "selective_user", "password": "Password123!"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    multi_notice = (
        "제26회 TOPCIT 정기평가 단체접수: 구글 설문 접수 마감은 9월 9일 23:59까지이며, "
        "보증금 납부는 9월 11일 13:00까지입니다."
    )
    extract_resp = client.post("/api/v1/schedules/extract", headers=headers, json={"text": multi_notice})
    assert extract_resp.status_code == 200
    candidates = extract_resp.json()["candidates"]
    assert len(candidates) == 2

    # 사용자가 첫 번째 후보(구글 설문 접수 마감)만 승인하여 저장
    cand1 = candidates[0]
    cand1_payload = {
        "title": cand1["title"],
        "schedule_kind": "TIME_CONFIRMED_DEADLINE",
        "end_date": "2026-09-09",
        "end_datetime": "2026-09-09T23:59:00+09:00",
        "timezone": "Asia/Seoul",
        "priority": "MEDIUM",
        "extracted_quote": cand1["source_quote"],
        "confirmed": True,
    }
    create_resp = client.post("/api/v1/schedules", headers=headers, json=cand1_payload)
    assert create_resp.status_code == 201

    # 두 번째 후보(보증금 납부)는 사용자가 확인하지 않았으므로 DB에 존재하지 않아야 함
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT title FROM personal_schedules")
    saved_titles = [row[0] for row in cur.fetchall()]
    conn.close()

    assert len(saved_titles) == 1
    assert saved_titles[0] == "TOPCIT 구글 설문 접수 마감"
    assert "TOPCIT 보증금 납부 마감" not in saved_titles
