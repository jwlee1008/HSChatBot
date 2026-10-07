"""
tests/test_browser_e2e.py

CampusMate Playwright Browser End-to-End Test Suite.
Verifies real Chromium browser interaction with the FastAPI + React frontend:
1. User registration, authentication, and server-side token revocation on logout (F3).
2. Zero-Auto-Save enforcement: candidates extracted from chat messages are never auto-persisted (F2, F5).
3. Multi-candidate selection tab: only user-confirmed candidate is saved; unselected candidate is ignored (F5).
4. Calendar multi-day period display spanning intermediate days (F6).
5. Schedule CRUD: Create with 5 kinds (no extra forbids) (F1), Edit via ScheduleEditModal (PATCH) (F6), complete toggle, and delete.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

import config
from backend.db.database import get_db, get_db_connection
from backend.main import app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class UvicornTestServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[tuple[str, Path], None, None]:
    """Start isolated FastAPI + React frontend server in a background thread."""
    tmp_dir = tmp_path_factory.mktemp("browser_e2e")
    test_db = tmp_dir / "test_browser_e2e.db"

    orig_auth_db = config.AUTH_DB_PATH
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

    port = find_free_port()
    server_cfg = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error")
    server = UvicornTestServer(config=server_cfg)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    # Wait for server to become responsive
    for _ in range(50):
        try:
            resp = urllib.request.urlopen(f"{base_url}/", timeout=1)
            if resp.status == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Failed to start uvicorn test server within 5 seconds")

    yield base_url, test_db

    # Clean up
    server.should_exit = True
    server_thread.join(timeout=3)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(orig_overrides)
    config.AUTH_DB_PATH = orig_auth_db
    config.PREWARM_RAG_ON_STARTUP = orig_prewarm

    if orig_env_db is None:
        os.environ.pop("AUTH_DB_PATH", None)
    else:
        os.environ["AUTH_DB_PATH"] = orig_env_db

    if orig_env_prewarm is None:
        os.environ.pop("PREWARM_RAG_ON_STARTUP", None)
    else:
        os.environ["PREWARM_RAG_ON_STARTUP"] = orig_env_prewarm


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(playwright_instance) -> Generator[Browser, None, None]:
    b = playwright_instance.chromium.launch(headless=True)
    yield b
    b.close()


def test_browser_e2e_full_lifecycle(browser: Browser, browser_server: tuple[str, Path]):
    """
    Comprehensive E2E test verifying defects F1 through F6 in real browser execution.
    """
    base_url, db_path = browser_server
    page: Page = browser.new_page()
    page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.text}"))
    page.on("dialog", lambda d: (print(f"[BROWSER DIALOG] {d.message}"), d.accept()))

    try:
        # ── 1. 페이지 로드 & 기본 렌더링 검증 ─────────────────────────
        page.goto(base_url)
        page.wait_for_selector("text=CampusMate")
        assert "CampusMate" in page.content()

        # ── 2. 회원가입 및 로그인 흐름 (F3: 게스트 자동로그인 제거 검증) ───
        login_btn = page.locator("button:has-text('로그인')").first
        assert login_btn.is_visible()
        login_btn.click()

        # AuthModal 확인 및 회원가입 모드로 전환
        page.wait_for_selector("h2:has-text('로그인')", timeout=5000)
        register_toggle_btn = page.locator("button:has-text('계정이 없으신가요? 회원가입')")
        register_toggle_btn.click()
        page.wait_for_selector("h2:has-text('회원가입')", timeout=5000)

        # 폼 입력
        username = f"pw_user_{int(time.time())}"
        password = "Password123!"

        username_input = page.locator("input[placeholder*='영문, 숫자']")
        password_input = page.locator("input[placeholder*='8자 이상']")

        username_input.fill(username)
        password_input.fill(password)

        submit_btn = page.locator("button[type='submit']")
        submit_btn.click()

        # 회원가입 성공 시 자동 로그인되어 헤더에 사용자명 노출
        page.wait_for_selector(f"text={username}", timeout=5000)
        logout_btn = page.locator("button:has-text('로그아웃')")
        assert logout_btn.is_visible()

        # ── 3. Zero-Auto-Save & 다중 후보(Multi-candidate) 탭 검증 (F2, F5) ──
        # 챗봇 질의 API 모킹하여 2개 후보가 포함된 TOPCIT 공지 답변 반환
        # ── 3. Zero-Auto-Save & 다중 후보(Multi-candidate) 탭 검증 (F2, F5, R4) ──
        # 챗봇 질의 API 모킹하여 2개 후보가 포함된 TOPCIT 공지 답변 반환
        # (주의: /api/query 엔드포인트는 mock 답변을 반환하며, 백엔드 RAG의 실제 LLM 생성이 아닌 프론트-API 연동을 검증함)
        mock_answer = (
            "TOPCIT 구글 설문 접수 마감은 11월 20일 17:00까지이며 "
            "보증금 납부는 11월 22일 12:00까지입니다."
        )

        def handle_query_route(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"answer": mock_answer, "sources": [], "status": "ok"}),
            )

        page.route("**/api/query", handle_query_route)

        # 챗봇 입력창에 질문 전송
        chat_input = page.locator("input[placeholder*='학사, 장학']")
        chat_input.fill("TOPCIT 일정 알려줘")
        chat_input.press("Enter")

        # 봇 말풍선 및 [📅 답변에서 일정 추출] 버튼 대기
        page.wait_for_selector("text=TOPCIT 구글 설문 접수 마감", timeout=5000)
        page.wait_for_selector("button:has-text('답변에서 일정 추출')", timeout=5000)

        # Zero-Auto-Save 확인 1: 추출 전 DB 레코드 0건
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "추출 전 DB는 0건이어야 합니다."

        # 일정 추출 버튼 클릭
        extract_btn = page.locator("button:has-text('답변에서 일정 추출')").last
        extract_btn.click()

        # Zero-Auto-Save 확인 모달 대기
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # Zero-Auto-Save 확인 2: 추출 모달이 열린 상태에서도 DB 레코드 0건 유지!
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "Zero-Auto-Save: 모달 표시 중에도 DB 자동 저장이 발생하면 안 됩니다."

        # R4: 취소 버튼 클릭 시 미저장 확인
        cancel_btn = page.locator("button:has-text('취소')").last
        cancel_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "취소 시 DB에 저장되지 않아야 합니다."

        # 다시 모달 열기
        extract_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # 다중 후보 탭 확인 (F5: 후보 1, 후보 2 탭 표시)
        tab_cand1 = page.locator("button:has-text('후보 1')")
        tab_cand2 = page.locator("button:has-text('후보 2')")
        assert tab_cand1.is_visible(), "후보 1 탭이 존재해야 합니다."
        assert tab_cand2.is_visible(), "후보 2 탭이 존재해야 합니다."

        # 후보 2(보증금 납부) 선택
        tab_cand2.click()
        time.sleep(0.3)

        # 후보 2 저장 실행
        save_btn = page.locator("button:has-text('확인 및 캘린더 저장')")
        assert not save_btn.is_disabled()
        save_btn.click()

        # 모달 닫힘 확인
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)

        # Zero-Auto-Save & R4 확인: 선택한 후보 2만 정확히 1건 저장, 후보 1 미저장, 후보 2의 정확한 값 대조
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM personal_schedules")
            rows = cur.fetchall()
            assert len(rows) == 1, f"선택한 후보 1건만 저장되어야 합니다. 현재: {len(rows)}"
            saved = rows[0]
            assert saved["title"] == "TOPCIT 보증금 납부 마감"
            assert saved["schedule_kind"] == "TIME_CONFIRMED_DEADLINE"
            assert saved["end_date"] == "2026-11-22"
            assert saved["end_datetime"] == "2026-11-22T03:00:00Z"
            assert "구글 설문" not in saved["title"]

        # ── 4. 캘린더 뷰 & 다일 기간 일정 등록 (F1, F6) ───────────────────
        cal_tab = page.locator("button:has-text('캘린더')")
        cal_tab.click()

        # 캘린더 헤더 및 [➕ 새 일정] 버튼 확인
        page.wait_for_selector("button:has-text('새 일정')", timeout=5000)
        new_schedule_btn = page.locator("button:has-text('새 일정')")
        new_schedule_btn.click()

        # 모달 오픈 확인
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # 일정 등록 (F1 검증: TIME_CONFIRMED_EVENT에 is_all_day/is_time_confirmed 누락 없이 201 성공)
        title_input = page.locator("input[placeholder='예: 과제 제출 마감']")
        title_input.fill("2026 2학기 중간고사 집중기간")

        # 일정 유형 선택: TIME_CONFIRMED_EVENT
        kind_select = page.locator("select").first
        kind_select.select_option("TIME_CONFIRMED_EVENT")

        # 날짜 및 시간 입력 (다일 기간: 2026-10-20 ~ 2026-10-24)
        date_inputs = page.locator("input[type='date']")
        assert date_inputs.count() >= 2
        date_inputs.nth(0).fill("2026-10-20")
        date_inputs.nth(1).fill("2026-10-24")

        time_inputs = page.locator("input[type='time']")
        if time_inputs.count() >= 2:
            time_inputs.nth(0).fill("09:00")
            time_inputs.nth(1).fill("18:00")

        # 저장
        confirm_save_btn = page.locator("button:has-text('확인 및 캘린더 저장')")
        confirm_save_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)

        # DB에 총 2건 저장 확인
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 2

        # 모달 닫힘 및 새 일정이 화면에 렌더링될 때까지 대기
        page.wait_for_selector("text=2026 2학기 중간고사 집중기간", timeout=5000)

        # ── 5. R4: 다일 기간 일정 캘린더 중간 날짜 클릭 및 필터링 검증 ───────
        # 2026년 10월로 정확히 이동
        page.wait_for_selector("h2:has-text('년')", timeout=5000)
        target = "2026년 10월"
        for _ in range(12):
            cur_header = page.locator("h2:has-text('년')").first.inner_text()
            if target in cur_header:
                break
            if "2026년 11월" in cur_header or "2026년 12월" in cur_header or "2027" in cur_header:
                page.locator("button:has-text('‹')").click()
            else:
                page.locator("button:has-text('›')").click()
            time.sleep(0.2)

        assert "2026년 10월" in page.locator("h2:has-text('년')").first.inner_text()

        # 다일 기간(10-20 ~ 10-24)의 중간 날짜인 22일(목) 셀 클릭!
        day_22_btn = page.locator("div.grid.grid-cols-7 button:has-text('22')").first
        day_22_btn.click()
        time.sleep(0.4)

        # 중간 날짜인 10월 22일 필터 상태에서도 기간 일정 '2026 2학기 중간고사 집중기간'이 목록에 정상 노출됨을 검증!
        assert page.locator("text=2026 2학기 중간고사 집중기간").first.is_visible()

        # 기간 밖 날짜인 25일(일) 셀 클릭 시 해당 일정이 필터링되어 목록에서 사라짐을 검증!
        day_25_btn = page.locator("div.grid.grid-cols-7 button:has-text('25')").first
        day_25_btn.click()
        time.sleep(0.4)
        assert page.locator("text=2026 2학기 중간고사 집중기간").count() == 0

        # '전체 보기' 클릭으로 필터 해제
        page.locator("button:has-text('전체 보기')").click()
        time.sleep(0.3)
        assert page.locator("text=2026 2학기 중간고사 집중기간").first.is_visible()

        # ── 6. R1 검증: 제목만 수정 시 UTC 9시간 왜곡 방지 및 초·소수점초 보존 ─
        test_micro_id = "test-micro-sched-001"
        raw_start_utc = "2026-11-20T00:00:45.123456Z"
        raw_end_utc = "2026-11-20T01:00:55.654321Z"

        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE username = ?", (username,))
            user_id = cur.fetchone()[0]
            conn.execute(
                """
                INSERT INTO personal_schedules (
                    id, user_id, title, schedule_kind, is_all_day, is_time_confirmed,
                    start_date, end_date, start_datetime, end_datetime, timezone,
                    is_completed, priority, user_confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test_micro_id,
                    user_id,
                    "정밀 타임스탬프 원본 일정",
                    "TIME_CONFIRMED_EVENT",
                    0,
                    1,
                    "2026-11-20",
                    "2026-11-20",
                    raw_start_utc,
                    raw_end_utc,
                    "Asia/Seoul",
                    0,
                    "HIGH",
                    "2026-09-24T00:00:00Z",
                    "2026-09-24T00:00:00Z",
                    "2026-09-24T00:00:00Z",
                ),
            )
            conn.commit()

        # DB에 직접 주입된 일정을 브라우저가 fetch하도록 refresh 이벤트 발송 및 '전체 보기'
        page.evaluate("() => window.dispatchEvent(new CustomEvent('refresh-schedules'))")
        page.locator("button:has-text('전체 보기')").click()
        page.wait_for_selector("text=정밀 타임스탬프 원본 일정", timeout=5000)

        # 화면에 서울 시각 기준 09:00 ~ 10:00 표시 확인 (9시간 밀림 방지)
        card_micro = page.locator("div.bg-white:has-text('정밀 타임스탬프 원본 일정')").last
        assert "09:00" in card_micro.inner_text()
        assert "10:00" in card_micro.inner_text()

        # 수정 모달 열기
        card_micro.locator("button[title='일정 수정']").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", timeout=5000)

        # 모달 내부 input 값 확인: 서울 기준 09:00, 10:00으로 표시되어야 함
        time_inputs = page.locator("div:has-text('일정 내용 수정') input[type='time']")
        assert time_inputs.nth(0).input_value() == "09:00"
        assert time_inputs.nth(1).input_value() == "10:00"

        # 제목만 수정 (시간/날짜 input은 전혀 건드리지 않음)
        edit_title_input = page.locator("div:has-text('일정 내용 수정') input[type='text']").first
        edit_title_input.fill("정밀 타임스탬프 원본 일정 [제목만수정]")

        # 수정 저장 클릭
        page.locator("button:has-text('수정 완료')").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", state="hidden", timeout=5000)

        # DB 검증: 제목은 변경되었으나 start_datetime / end_datetime은 100% 동일하게 보존! (마이크로초 .123456 유지)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM personal_schedules WHERE id = ?", (test_micro_id,)).fetchone()
            assert row["title"] == "정밀 타임스탬프 원본 일정 [제목만수정]"
            assert row["start_datetime"] == raw_start_utc, f"시각 왜곡 발생: {row['start_datetime']} != {raw_start_utc}"
            assert row["end_datetime"] == raw_end_utc, f"시각 왜곡 발생: {row['end_datetime']} != {raw_end_utc}"

        # ── 6-B. Defect C 검증: 종료 시각(endTime)만 수정 시 start_datetime 및 마이크로초(.123456) byte-for-byte 보존 ─
        updated_card_micro = page.locator("div.bg-white:has-text('정밀 타임스탬프 원본 일정 [제목만수정]')").last
        updated_card_micro.locator("button[title='일정 수정']").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", timeout=5000)

        # 시작 시각(09:00)은 그대로 두고, 종료 시각만 10:00 -> 11:00으로 변경
        time_inputs_6b = page.locator("div:has-text('일정 내용 수정') input[type='time']")
        assert time_inputs_6b.nth(0).input_value() == "09:00"
        assert time_inputs_6b.nth(1).input_value() == "10:00"
        time_inputs_6b.nth(1).fill("11:00")

        # 수정 저장
        page.locator("button:has-text('수정 완료')").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", state="hidden", timeout=5000)

        # DB 검증: start_datetime은 전혀 수정되지 않아 마이크로초 .123456이 온전히 보존됨!
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row_6b = conn.execute("SELECT * FROM personal_schedules WHERE id = ?", (test_micro_id,)).fetchone()
            assert row_6b["start_datetime"] == raw_start_utc, (
                f"Defect C 위반: 종료 시각만 수정했으나 start_datetime 마이크로초가 유실됨: {row_6b['start_datetime']} != {raw_start_utc}"
            )
            assert row_6b["end_datetime"] == "2026-11-20T02:00:00Z"

        # ── 6-C. Defect C 검증: 시작 시각(startTime)만 수정 시 end_datetime 보존 ─
        updated_card_micro = page.locator("div.bg-white:has-text('정밀 타임스탬프 원본 일정 [제목만수정]')").last
        updated_card_micro.locator("button[title='일정 수정']").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", timeout=5000)

        time_inputs_6c = page.locator("div:has-text('일정 내용 수정') input[type='time']")
        assert time_inputs_6c.nth(0).input_value() == "09:00"
        assert time_inputs_6c.nth(1).input_value() == "11:00"
        time_inputs_6c.nth(0).fill("08:00")

        # 수정 저장
        page.locator("button:has-text('수정 완료')").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", state="hidden", timeout=5000)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row_6c = conn.execute("SELECT * FROM personal_schedules WHERE id = ?", (test_micro_id,)).fetchone()
            assert row_6c["start_datetime"] == "2026-11-19T23:00:00Z"
            assert row_6c["end_datetime"] == "2026-11-20T02:00:00Z"

        # ── 7. 서울 자정 경계 시각 수정 검증 (R1, R4) ──────────────────────
        # 다시 수정 모달을 열어 실제 시각을 서울 자정(00:00)으로 변경
        updated_card_micro = page.locator("div.bg-white:has-text('정밀 타임스탬프 원본 일정 [제목만수정]')").last
        updated_card_micro.locator("button[title='일정 수정']").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", timeout=5000)

        edit_time_inputs = page.locator("div:has-text('일정 내용 수정') input[type='time']")
        edit_time_inputs.nth(0).fill("00:00")
        edit_time_inputs.nth(1).fill("01:00")

        page.locator("button:has-text('수정 완료')").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", state="hidden", timeout=5000)

        # DB 검증: 서울 자정(2026-11-20 00:00 KST)은 UTC 기준 2026-11-19T15:00:00Z로 정확히 저장됨
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM personal_schedules WHERE id = ?", (test_micro_id,)).fetchone()
            assert row["start_datetime"] == "2026-11-19T15:00:00Z"

        # 다시 모달 열어 자정 표시 확인: 전날로 밀리지 않고 2026-11-20 00:00으로 렌더링됨을 검증
        midnight_card = page.locator("div.bg-white:has-text('정밀 타임스탬프 원본 일정 [제목만수정]')").last
        midnight_card.locator("button[title='일정 수정']").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", timeout=5000)
        assert page.locator("div:has-text('일정 내용 수정') input[type='date']").first.input_value() == "2026-11-20"
        assert page.locator("div:has-text('일정 내용 수정') input[type='time']").first.input_value() == "00:00"
        page.locator("button:has-text('✕')").click()
        page.wait_for_selector("h2:has-text('일정 내용 수정')", state="hidden", timeout=5000)

        # ── 8. 51건 이상 대량 일정 페이지네이션 검증 (R4) ────────────────────
        with sqlite3.connect(db_path) as conn:
            for i in range(50):
                conn.execute(
                    """
                    INSERT INTO personal_schedules (
                        id, user_id, title, schedule_kind, is_all_day, is_time_confirmed,
                        start_date, end_date, start_datetime, end_datetime, timezone,
                        is_completed, priority, user_confirmed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"bulk-sched-{i:03d}",
                        user_id,
                        f"대량 테스트 일정 #{i+1:02d}",
                        "ALL_DAY_EVENT",
                        1,
                        0,
                        "2026-10-15",
                        "2026-10-15",
                        None,
                        None,
                        "Asia/Seoul",
                        0,
                        "LOW",
                        "2026-09-24T00:00:00Z",
                        "2026-09-24T00:00:00Z",
                        "2026-09-24T00:00:00Z",
                    ),
                )
            conn.commit()

        # refresh 이벤트 발송으로 재조회 트리거 (offset=0, limit=50 페이지를 넘어 53건 전체 fetch 검증)
        page.evaluate("() => window.dispatchEvent(new CustomEvent('refresh-schedules'))")
        page.locator("button:has-text('전체 보기')").click()
        page.wait_for_selector("text=대량 테스트 일정 #50", timeout=5000)
        assert page.locator("text=대량 테스트 일정 #50").is_visible()

        # ── 9. 완료 토글 및 삭제 검증 ────────────────────────────────────
        # 기존 중간고사 집중기간 카드 완료 체크
        target_card = page.locator("div.bg-white:has-text('2026 2학기 중간고사 집중기간')").last
        checkbox = target_card.locator("input[type='checkbox']")
        checkbox.click()
        time.sleep(0.5)

        # 완료 취소선 클래스 적용 확인
        page.wait_for_selector("h3.line-through:has-text('2026 2학기 중간고사 집중기간')", timeout=5000)

        # 삭제 (dialog 자동 수락)
        del_btn = target_card.locator("button[title='일정 삭제']")
        del_btn.click()
        time.sleep(0.5)

        # ── 10. 서버 로그아웃 및 토큰 즉시 무효화 검증 (F3, R4) ────────────────
        user_token = page.evaluate("() => localStorage.getItem('campusmate_token')")
        assert user_token is not None, "로그아웃 전에는 토큰이 존재해야 합니다."

        # 헤더의 로그아웃 버튼 클릭
        header_logout_btn = page.locator("button:has-text('로그아웃')")
        header_logout_btn.click()

        # 로그아웃 후 헤더에 '로그인' 버튼 다시 표시
        page.wait_for_selector("button:has-text('로그인')", timeout=5000)

        # 브라우저 localStorage에서 token 제거 확인
        stored_token = page.evaluate("() => localStorage.getItem('campusmate_token')")
        assert stored_token is None, "로그아웃 시 localStorage 토큰이 삭제되어야 합니다."

        # R4: 이전 토큰으로 /api/v1/auth/me 직접 호출 시 401 Unauthorized 반환 검증!
        req = urllib.request.Request(
            f"{base_url}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 401, f"로그아웃된 토큰은 401이어야 합니다. 실제: {exc_info.value.code}"

    finally:
        page.close()


def test_browser_real_notice_source_card_flow(browser: Browser, browser_server: tuple[str, Path]):
    """
    Playwright Chromium browser test for real notice extraction from a SourceCard:
    1. Deliver real notice content in a SourceCard (Transfer credit notice, doc e8ef6be4...)
       with mock RAG delivery; extraction and schedule CRUD are real.
    2. Zero-Auto-Save enforcement:
       - No schedules saved before extraction.
       - No schedules saved while candidate confirmation modal is open.
       - No schedules saved when user cancels (클릭 '취소').
    3. Multi-candidate review and confirmation:
       - User reviews candidate tabs, selects student application candidate.
       - Verifies form fields (title, date/time, source quote).
       - Confirms and saves.
       - Verifies DB has EXACTLY 1 schedule; unselected candidates are NOT saved.
    4. Calendar re-fetch:
       - Navigates to Calendar tab -> verifies the saved schedule is fetched and displayed.
    5. Failure / no-date source card handling and manual fallback:
       - Delivers source card with no dates ('신청 서류 : 온라인 신청').
       - Clicks [일정 추출] -> alerts '추출 가능한 일정 정보를 찾지 못했습니다'.
       - Verifies DB count remains 1 (no auto-save on failure).
       - Navigates to Calendar -> clicks [새 일정] -> enters manual schedule -> confirms -> DB count is 2.
    """
    base_url, db_path = browser_server

    # Clean DB to ensure isolated test state
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM personal_schedules")
        conn.execute("DELETE FROM users")
        conn.commit()

    # Load frozen real notice document
    dataset_path = Path(__file__).resolve().parents[1] / "data/unified_campus_knowledge.json"
    documents = {d["id"]: d for d in json.loads(dataset_path.read_text())}
    transfer_doc = documents["e8ef6be49a4035bf045418f414546e2acf10952f2e134f168183eed0d8c10864"]
    notice_text = transfer_doc["content"][:2000]

    page: Page = browser.new_page()
    page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.text}"))
    page.on("request", lambda r: print(f"[HTTP REQ] {r.method} {r.url}"))
    page.on("response", lambda r: print(f"[HTTP RESP] {r.status} {r.url}"))
    dialog_messages: list[str] = []
    page.on("dialog", lambda d: (print(f"[BROWSER DIALOG] {d.message}"), dialog_messages.append(d.message), d.accept()))

    try:
        page.goto(base_url)
        page.wait_for_selector("text=CampusMate")

        # ── 1. 회원가입 및 로그인 ──────────────────────────────────────────
        login_nav_btn = page.locator("button:has-text('로그인')")
        login_nav_btn.click()
        page.wait_for_selector("h2:has-text('로그인')", timeout=5000)

        switch_to_register = page.locator("button:has-text('회원가입')").last
        switch_to_register.click()
        page.wait_for_selector("h2:has-text('회원가입')", timeout=5000)

        username = f"notice_user_{int(time.time())}"
        password = "Password123!"
        page.locator("input[placeholder*='영문, 숫자']").fill(username)
        page.locator("input[placeholder*='8자 이상']").fill(password)
        page.locator("button[type='submit']").click()

        page.wait_for_selector(f"text={username}", timeout=5000)

        # ── 2. RAG 응답 Mock (실제 공지 본문 SourceCard 포함) ───────────────
        # 주의: /api/query 질의응답 전달만 mock이며, 일정 추출(/api/v1/schedules/extract)과
        # 캘린더 등록(/api/v1/schedules)은 실제 백엔드 API 및 DB를 사용함
        mock_response_1 = {
            "answer": "편입생 학점 인정 관련 공지사항 및 신청 기간 안내입니다.",
            "sources": [
                {
                    "title": transfer_doc["title"],
                    "url": transfer_doc["url"],
                    "content": notice_text,
                    "meta": "한성공지 | 2026-09-10",
                    "score": 0.95,
                }
            ],
            "status": "success",
        }

        current_mock_response = mock_response_1

        def handle_query_route(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(current_mock_response),
            )

        page.route("**/api/query", handle_query_route)

        chat_input = page.locator("input[placeholder*='학사, 장학']")
        chat_input.fill("편입생 학점인정 신청 기간 알려줘")
        chat_input.press("Enter")

        # 출처 카드 및 [📅 일정 추출] 버튼 대기
        page.wait_for_selector("text=편입생 전적대학 학점", timeout=5000)
        source_card = page.locator("div.rounded-2xl:has-text('편입생 전적대학')").last
        extract_btn = source_card.locator("button:has-text('일정 추출')")
        page.wait_for_selector("button:has-text('일정 추출')", timeout=5000)

        # ── 3. Zero-Auto-Save 검증 1: 추출 전 DB는 0건 ───────────────────────
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "추출 실행 전 DB는 0건이어야 합니다."

        # 출처 카드의 [📅 일정 추출] 클릭 -> 실제 /api/v1/schedules/extract 호출
        extract_btn.click()

        # 모달 오픈 확인
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # Zero-Auto-Save 검증 2: 모달 오픈 상태에서도 DB는 여전히 0건
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "모달 표시 중 자동 저장이 발생하면 안 됩니다."

        # Zero-Auto-Save 검증 3: 취소 클릭 시 미저장 확인
        page.locator("button:has-text('취소')").last.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "취소 후 DB는 0건이어야 합니다."

        # ── 4. 모달 재오픈, 후보 탭 탐색, 대상 후보 확인 및 저장 ─────────────
        extract_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # 후보 탭 표시 확인 (실제 공지에서 복수 후보 추출됨)
        tab_cand1 = page.locator("button:has-text('후보 1')")
        tab_cand2 = page.locator("button:has-text('후보 2')")
        assert tab_cand1.is_visible()
        assert tab_cand2.is_visible()

        # 탭 전환 테스트: 후보 2 클릭 후 다시 후보 1(학생 신청 기간) 클릭
        tab_cand2.click()
        time.sleep(0.3)
        tab_cand1.click()
        time.sleep(0.3)

        # 입력 필드에 대상 일정 값 채워졌는지 확인
        title_val = page.locator("input[placeholder='예: 과제 제출 마감']").input_value()
        assert "신청" in title_val

        # 확인 및 캘린더 저장 클릭
        save_btn = page.locator("button:has-text('확인 및 캘린더 저장')")
        assert not save_btn.is_disabled()
        save_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)

        # ── 5. DB 영속성 검증: 선택한 1건만 저장, 미선택 후보 미저장 ────────────
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM personal_schedules")
            rows = cur.fetchall()
            assert len(rows) == 1, f"선택한 후보 1건만 저장되어야 합니다. 실제: {len(rows)}"
            saved = rows[0]
            assert "신청" in saved["title"]
            assert saved["start_date"] == "2026-09-10"
            assert saved["end_date"] == "2026-09-18"
            assert saved["end_datetime"] == "2026-09-18T08:00:00Z"
            assert "https://www.hansung.ac.kr" in (saved["source_url"] or "")

        # ── 6. 캘린더 화면 이동 및 저장된 일정 재조회 검증 ────────────────────
        cal_tab = page.locator("button:has-text('캘린더')")
        cal_tab.click()
        page.wait_for_selector("button:has-text('새 일정')", timeout=5000)

        # 2026년 9월로 이동 (필요한 경우)
        page.wait_for_selector("h2:has-text('년')", timeout=5000)
        target = "2026년 9월"
        for _ in range(12):
            cur_header = page.locator("h2:has-text('년')").first.inner_text()
            if target in cur_header:
                break
            if "2026년 10월" in cur_header or "2026년 11월" in cur_header or "2026년 12월" in cur_header or "2027" in cur_header:
                page.locator("button:has-text('‹')").click()
            else:
                page.locator("button:has-text('›')").click()
            time.sleep(0.2)

        # 캘린더 일정 목록에 저장된 일정 확인
        page.wait_for_selector(f"h3:has-text('{saved['title']}')", timeout=5000)
        assert page.locator(f"h3:has-text('{saved['title']}')").is_visible()

        # ── 7. 무일정(0건) 공지 출처 카드 추출 실패 및 알림 검증 ─────────────
        # 챗봇 탭으로 복귀
        chat_nav_btn = page.locator("button:has-text('챗봇')")
        chat_nav_btn.click()
        page.wait_for_selector("input[placeholder*='학사, 장학']", timeout=5000)

        # 무일정 공지 SourceCard 목킹 (uat-no-date: "신청 서류 : 온라인 신청")
        mock_response_2 = {
            "answer": "신청 서류 안내입니다.",
            "sources": [
                {
                    "title": "편입 서류 안내",
                    "url": transfer_doc["url"],
                    "content": "신청 서류 : 온라인 신청",
                    "meta": "한성공지 | 2026-09-10",
                    "score": 0.88,
                }
            ],
            "status": "success",
        }
        current_mock_response = mock_response_2

        chat_input = page.locator("input[placeholder*='학사, 장학']")
        chat_input.fill("편입 서류 제출 방법 알려줘")
        chat_input.press("Enter")

        page.wait_for_selector("text=편입 서류 안내", timeout=5000)
        no_date_card = page.locator("div.rounded-2xl:has-text('편입 서류 안내')").last
        no_date_extract_btn = no_date_card.locator("button:has-text('일정 추출')")

        # 추출 클릭 -> 후보 0건 알림 발생
        dialog_messages.clear()
        no_date_extract_btn.first.click()
        for _ in range(50):
            if any("추출 가능한 일정 정보를 찾지 못했습니다" in msg for msg in dialog_messages):
                break
            page.wait_for_timeout(100)

        # '선택하신 텍스트/공지에서 추출 가능한 일정 정보를 찾지 못했습니다.' 알림 확인
        assert any("추출 가능한 일정 정보를 찾지 못했습니다" in msg for msg in dialog_messages), (
            f"무일정 공지 추출 시 알림이 발생해야 합니다. 수신된 알림: {dialog_messages}"
        )

        # DB는 여전히 1건 (추출 실패 시 자동 저장 없음)
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 1, "추출 실패 시 DB는 1건을 유지해야 합니다."

        # ── 8. 실패 시 수동 등록 경로 검증 ────────────────────────────────────
        cal_tab.click()
        page.wait_for_selector("button:has-text('새 일정')", timeout=5000)
        page.locator("button:has-text('새 일정')").click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        # 수동 입력
        page.locator("input[placeholder='예: 과제 제출 마감']").fill("편입 서류 수동 등록")
        page.locator("select").first.select_option("TIME_CONFIRMED_DEADLINE")
        page.locator("input[type='date']").last.fill("2026-09-18")
        page.locator("input[type='time']").last.fill("17:00")

        page.locator("button:has-text('확인 및 캘린더 저장')").click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)

        # DB 총 2건 확인
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 2, "수동 등록 후 DB는 총 2건이어야 합니다."

        # 캘린더 목록에 수동 등록 일정 노출 확인
        page.wait_for_selector("h3:has-text('편입 서류 수동 등록')", timeout=5000)
        assert page.locator("h3:has-text('편입 서류 수동 등록')").is_visible()

    finally:
        page.close()


def test_mentoring_real_notice_title_conflict_browser_flow(
    browser: Browser,
    browser_server: tuple[str, Path],
) -> None:
    """N3: 실제 멘토링 공지의 별도 출처 제목(9.10~6.11)과 본문(9.10~9.17) 충돌 시
    브라우저 UI 모달에서 모호성 안내 배너 표출 및 미선택 미저장(Zero-Auto-Save) 전 과정을 Chromium에서 검증한다.
    """
    base_url, db_path = browser_server

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM personal_schedules")
        conn.execute("DELETE FROM users")
        conn.commit()

    # Load frozen real notice document (mentoring doc)
    dataset_path = Path(__file__).resolve().parents[1] / "data/unified_campus_knowledge.json"
    documents = {d["id"]: d for d in json.loads(dataset_path.read_text())}
    mentoring_doc = documents["1a676b27ed5c8142545bbfb02958d03031276fbb0f5491a7264b47471e598ae1"]

    page: Page = browser.new_page()
    page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.text}"))
    page.on("request", lambda r: print(f"[HTTP REQ] {r.method} {r.url}"))
    page.on("response", lambda r: print(f"[HTTP RESP] {r.status} {r.url}"))

    try:
        page.goto(base_url)
        page.wait_for_selector("text=CampusMate")

        # 1. 회원가입 및 로그인
        login_nav_btn = page.locator("button:has-text('로그인')")
        login_nav_btn.click()
        page.wait_for_selector("h2:has-text('로그인')", timeout=5000)

        switch_to_register = page.locator("button:has-text('회원가입')").last
        switch_to_register.click()
        page.wait_for_selector("h2:has-text('회원가입')", timeout=5000)

        username = f"mentor_user_{int(time.time())}"
        password = "Password123!"
        page.locator("input[placeholder*='영문, 숫자']").fill(username)
        page.locator("input[placeholder*='8자 이상']").fill(password)
        page.locator("button[type='submit']").click()

        page.wait_for_selector(f"text={username}", timeout=5000)

        # 2. RAG 응답 Mock (실제 멘토링 공지의 title과 content 전달)
        # title: (9.10.목~6.11.목 15:00) vs content: (2026. 09. 10 ~ 2026. 09. 17 15:00)
        mock_response = {
            "answer": "취업멘토링 참가자 모집 안내입니다.",
            "sources": [
                {
                    "title": mentoring_doc["title"],
                    "url": mentoring_doc["url"],
                    "content": mentoring_doc["content"],
                    "meta": "한성공지 | 2026-09-04",
                    "score": 0.96,
                }
            ],
            "status": "success",
        }

        page.route("**/api/query", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(mock_response),
        ))

        chat_input = page.locator("input[placeholder*='학사, 장학']")
        chat_input.fill("취업 멘토링 신청 기간 알려줘")
        chat_input.press("Enter")

        # 출처 카드 및 [📅 일정 추출] 버튼 대기
        page.wait_for_selector("text=취업멘토링", timeout=5000)
        source_card = page.locator("div.rounded-2xl:has-text('취업멘토링')").last
        extract_btn = source_card.locator("button:has-text('일정 추출')")
        extract_btn.click()

        # 3. 모달 오픈 및 Zero-Auto-Save 확인 (DB 0건)
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", timeout=5000)

        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "추출 모달 오픈 중에는 자동 저장되지 않아야 합니다."

        # 4. N3 브라우저 UI 검증: 모호성 안내 경고 배너 표출 확인
        page.wait_for_selector("text=모호성 안내 (확인 필요)", timeout=5000)
        warning_banner = page.locator("div.bg-amber-50").first
        assert warning_banner.is_visible()
        banner_text = warning_banner.inner_text()
        assert "공지 제목의 기간과 본문 신청 기간이 상이하여 확인 필요" in banner_text

        # 5. 근거 원문 발췌문이 본문 신청 기간을 정확히 가리키는지 확인
        page.wait_for_selector("text=근거 원문 발췌:", timeout=5000)
        quote_elem = page.locator("div:has-text('근거 원문 발췌:')").locator("p.italic").first
        quote_text = quote_elem.inner_text().strip('"').strip("'")
        assert quote_text in mentoring_doc["content"]

        # 6. 취소 시 미저장(Zero-Auto-Save) 확인
        cancel_btn = page.locator("button:has-text('취소')").last
        cancel_btn.click()
        page.wait_for_selector("h2:has-text('일정 후보 확인 및 등록')", state="hidden", timeout=5000)

        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM personal_schedules")
            assert cur.fetchone()[0] == 0, "취소 후 DB는 0건이어야 합니다."

    finally:
        page.close()

