"""
CampusRAG 다도메인 브라우저 E2E 테스트 (Playwright)

4대 도메인(학사, 장학, 행사, 취업/창업) 질문, 무관 질문 유보,
출처 카드 원문 링크 접근성, 연속 대화 흐름, 모바일 뷰포트(390x844) 레이아웃을 검증한다.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
import urllib.request

import pytest

# 로컬 프록시 우회 설정
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    """테스트용 백엔드 및 프론트엔드 서버를 백그라운드로 실행한다."""
    root = Path(__file__).resolve().parent.parent
    log_dir = tmp_path_factory.mktemp("e2e_md_servers")
    st_home = tmp_path_factory.mktemp("st_home")

    commands = {
        "backend": [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        "frontend": [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "frontend/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
            "--server.headless",
            "true",
        ],
    }
    endpoints = {
        "backend": "http://127.0.0.1:8000/health",
        "frontend": "http://127.0.0.1:8501/_stcore/health",
    }
    processes = {}
    logs = {}

    backend_env = dict(os.environ)
    backend_env["NO_PROXY"] = "127.0.0.1,localhost"
    backend_env["no_proxy"] = "127.0.0.1,localhost"

    frontend_env = dict(os.environ)
    frontend_env["HOME"] = str(st_home)
    frontend_env["STREAMLIT_SERVER_HEADLESS"] = "true"
    frontend_env["NO_PROXY"] = "127.0.0.1,localhost"
    frontend_env["no_proxy"] = "127.0.0.1,localhost"

    # 로컬 프록시 바이패스 opener 생성
    direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        logs["backend"] = (log_dir / "backend.log").open("w")
        processes["backend"] = subprocess.Popen(
            commands["backend"], cwd=str(root), stdout=logs["backend"], stderr=subprocess.STDOUT, env=backend_env
        )

        logs["frontend"] = (log_dir / "frontend.log").open("w")
        processes["frontend"] = subprocess.Popen(
            commands["frontend"], cwd=str(root), stdout=logs["frontend"], stderr=subprocess.STDOUT, env=frontend_env
        )

        deadline = time.monotonic() + 90
        pending = set(processes)
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                if processes[name].poll() is not None:
                    backend_log = (log_dir / "backend.log").read_text() if (log_dir / "backend.log").exists() else ""
                    frontend_log = (log_dir / "frontend.log").read_text() if (log_dir / "frontend.log").exists() else ""
                    pytest.fail(f"{name} 서버 조기 종료\nBackend:\n{backend_log}\nFrontend:\n{frontend_log}")
                try:
                    with direct_opener.open(endpoints[name], timeout=1) as response:
                        if response.status == 200:
                            pending.remove(name)
                except (URLError, TimeoutError, Exception):
                    pass
            if pending:
                time.sleep(0.5)

        if pending:
            backend_log = (log_dir / "backend.log").read_text() if (log_dir / "backend.log").exists() else ""
            frontend_log = (log_dir / "frontend.log").read_text() if (log_dir / "frontend.log").exists() else ""
            pytest.fail(f"서버 준비 시간 초과: {sorted(pending)}\nBackend:\n{backend_log}\nFrontend:\n{frontend_log}")

        yield processes

    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for name, log in logs.items():
            log.close()


def _get_latest_assistant_message(page, timeout=45000):
    """
    최신 assistant 응답 생성이 완료될 때까지 대기하고 해당 턴의 assistant 메시지 요소를 반환한다.
    스피너 대기 후 마지막 stChatMessage 컨테이너를 반환하여
    사용자 입력 프롬프트나 이전 턴의 텍스트가 검증에 혼입되지 않도록 격리한다.
    """
    try:
        page.locator("[data-testid='stSpinner']").wait_for(state="attached", timeout=5000)
    except Exception:
        pass
    page.locator("[data-testid='stSpinner']").wait_for(state="detached", timeout=timeout)
    page.wait_for_timeout(1000)

    messages = page.locator("[data-testid='stChatMessage']")
    assert messages.count() >= 2, "메시지 컨테이너가 충분히 렌더링되지 않았습니다."
    return messages.last


class TestE2EMultiDomain:
    """다도메인 UI 브라우저 E2E 테스트"""

    def test_mobile_viewport_layout(self, servers):
        """모바일 뷰포트(390x844)에서 레이아웃 및 여백이 정상 작동하는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # 제목 확인
            content = page.content()
            assert "CampusRAG" in content

            # 모바일에서 가로 스크롤이 발생하지 않는지 확인
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            assert scroll_width <= client_width + 5, f"가로 스크롤 발생: {scroll_width} > {client_width}"

            # 입력창 존재 확인
            chat_input = page.query_selector("textarea, input[type='text']")
            assert chat_input is not None, "모바일에서 채팅 입력창이 렌더링되지 않았습니다"

            browser.close()

    def test_academic_search_and_source_cards(self, servers):
        """학사 도메인 검색 시 출처 카드가 렌더링되고 원문 링크가 존재하는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # 채팅 입력창 찾기 및 학사 질문 전송
            chat_input = page.query_selector("textarea")
            assert chat_input is not None
            chat_input.fill("폐강 강좌 수강신청 정정")
            chat_input.press("Enter")

            # 응답 대기 (최대 20초)
            page.wait_for_selector(".source-card", timeout=20000)

            # 마지막 assistant 메시지 컨테이너 스코프에서 출처 카드 검증
            messages = page.locator("[data-testid='stChatMessage']")
            last_msg = messages.last
            cards = last_msg.locator(".source-card")
            assert cards.count() >= 1, "해당 턴에 출처 카드가 렌더링되지 않았습니다"

            # 해당 턴의 출처 카드 내 원문 보기 링크 속성 확인
            link = last_msg.locator(".source-card-link").first
            assert link is not None
            href = link.get_attribute("href")
            assert href and "hansung.ac.kr" in href, f"유효하지 않은 원문 링크: {href}"

            browser.close()

    def test_irrelevant_query_abstain(self, servers):
        """무관 질문 시 관련 공지 부재 및 유보 안내가 표시되는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            chat_input = page.query_selector("textarea")
            assert chat_input is not None
            chat_input.fill("파이썬 이진 탐색 트리 알고리즘")
            chat_input.press("Enter")

            page.wait_for_timeout(4000)

            # 마지막 assistant 메시지에서만 유보 문구 확인 (사용자 프롬프트나 전체 DOM 제외)
            messages = page.locator("[data-testid='stChatMessage']")
            last_msg = messages.last
            ans_text = last_msg.inner_text()
            assert any(w in ans_text for w in ("찾지 못", "찾을 수 없", "0건")), "무관 질문에 대해 assistant 유보 안내가 나타나지 않았습니다"

            browser.close()

    def test_multi_turn_conversation_isolation(self, servers):
        """연속 질문 시 이전 메시지와 새 메시지가 격리되어 누적되는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # 1턴: 행사 질문
            chat_input = page.query_selector("textarea")
            chat_input.fill("TOPCIT 정기평가")
            chat_input.press("Enter")
            page.wait_for_timeout(4000)

            # 1턴 메시지 확인
            messages = page.locator("[data-testid='stChatMessage']")
            assert messages.count() >= 3, "1턴 메시지가 렌더링되지 않았습니다"
            turn1_assistant = messages.nth(2)
            turn1_text = turn1_assistant.inner_text()
            assert "TOPCIT" in turn1_text or turn1_assistant.locator(".source-card").count() > 0

            # 2턴: 장학 질문
            chat_input = page.query_selector("textarea")
            chat_input.fill("인송문화재단 장학금")
            chat_input.press("Enter")
            page.wait_for_timeout(4000)

            # 2턴 assistant 메시지 격리 검증 (2턴 응답에는 1턴의 출처가 섞이지 않고, 2턴 내용만 존재해야 함)
            assert messages.count() >= 5, "2턴 메시지가 정상 누적되지 않았습니다"
            turn2_assistant = messages.nth(4)
            turn2_text = turn2_assistant.inner_text()
            assert "인송" in turn2_text or turn2_assistant.locator(".source-card").count() > 0
            # 2턴 assistant 메시지에 1턴 고유 내용(TOPCIT)이 섞이지 않음을 턴 단위로 검증
            assert "TOPCIT" not in turn2_text, "2턴 assistant 메시지에 1턴 내용이 잘못 혼입되었습니다"

            browser.close()

    def test_ai_mode_test_md_01_target_isolation(self, servers):
        """AI 모드 선택 후 편입생 질문 시 타 공지(2016 이전 입학자) 혼입 없이 편입생 대상만 답변하고 정확한 출처 URL을 반환하는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # 사이드바에서 "🤖 AI 답변 + 검색 (RAG)" 라디오 버튼 명시적 선택
            ai_mode_radio = page.get_by_text("🤖 AI 답변 + 검색 (RAG)")
            ai_mode_radio.click()
            page.wait_for_timeout(1000)

            # 질문 입력
            chat_input = page.query_selector("textarea")
            assert chat_input is not None
            chat_input.fill("편입생 전적대학 학점 재인정 신청 대상자가 누구야?")
            chat_input.press("Enter")

            # LLM 생성 및 출처 카드 렌더링 대기 후 마지막 assistant 메시지 확보
            page.wait_for_selector(".source-card", timeout=45000)
            assistant_msg = _get_latest_assistant_message(page, timeout=45000)
            ans_text = assistant_msg.inner_text()

            # 1. 올바른 대상 포함 검증 (사용자 질문이 아닌 assistant 답변 본문에서만 검증)
            assert any(w in ans_text for w in ("일반편입생", "편입생")), "AI 답변에 편입생 대상 안내가 누락되었습니다"
            # 2. 타 공지 대상 사실 혼입 차단 검증
            assert "2016학년도" not in ans_text, "타 공지의 '2016학년도 이전 입학자' 대상이 잘못 혼입되었습니다"
            assert "기존 학부제" not in ans_text, "타 공지의 '기존 학부제' 내용이 잘못 혼입되었습니다"

            # 3. 해당 턴의 출처 카드에서 정확한 URL 검증 (공지 224588)
            link = assistant_msg.locator(".source-card-link").first
            assert link is not None, "해당 턴의 출처 카드 링크가 없습니다"
            href = link.get_attribute("href")
            assert "224588" in href, f"예상 출처 URL(224588)과 불일치: {href}"

            browser.close()

    def test_ai_mode_test_md_02_schedule_accuracy(self, servers):
        """AI 모드에서 편입생 학점 재인정 기간 질문 시 시작/마감 일정이 정확히 답변되는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # AI 모드 선택
            page.get_by_text("🤖 AI 답변 + 검색 (RAG)").click()
            page.wait_for_timeout(1000)

            chat_input = page.query_selector("textarea")
            chat_input.fill("2026학년도 2학기 편입생 전적대학 학점 재인정 신청 접수 기간이 언제까지야?")
            chat_input.press("Enter")

            page.wait_for_selector(".source-card", timeout=45000)
            assistant_msg = _get_latest_assistant_message(page, timeout=45000)
            ans_text = assistant_msg.inner_text()

            # 오직 assistant 답변 본문에서만 날짜 검증 (질문 프롬프트 혼입 차단)
            assert any(w in ans_text for w in ("9월 10일", "9. 10", "9.10")), "신청 시작일(9월 10일)이 누락되었습니다"
            assert any(w in ans_text for w in ("9월 18일", "9. 18", "9.18")), "신청 마감일(9월 18일)이 누락되었습니다"
            assert "9월 9일" not in ans_text and "9월 16일" not in ans_text, "다른 공지의 날짜(9월 9일, 16일)가 혼입되었습니다"

            # 해당 턴의 출처 카드에서 링크 확인
            link = assistant_msg.locator(".source-card-link").first
            assert link is not None, "해당 턴의 출처 카드 링크가 없습니다"
            assert "224588" in link.get_attribute("href")

            browser.close()

    def test_ai_mode_abstain_unmentioned_detail(self, servers):
        """AI 모드에서 본문이 미확보된 공지(title_only) 질문 시 임의 추측 없이 세부 내용 확인 불가 및 원문 확인 유보를 안내하는지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://127.0.0.1:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            page.get_by_text("🤖 AI 답변 + 검색 (RAG)").click()
            page.wait_for_timeout(1000)

            chat_input = page.query_selector("textarea")
            chat_input.fill("2026학년도 장학제도 개편 및 국가장학금 2유형 세부 개편 내용이 어떻게 돼?")
            chat_input.press("Enter")

            page.wait_for_selector(".stChatMessage", timeout=45000)
            assistant_msg = _get_latest_assistant_message(page, timeout=45000)
            ans_text = assistant_msg.inner_text()

            # 임의 내용 추측 없이 assistant가 확인할 수 없다고 안내하고 원문 보기 안내를 제공하는지 검증
            assert any(w in ans_text for w in ("확인할 수 없습니다", "제목뿐이므로", "원문 보기")), "미기재 세부 정보에 대한 유보 안내가 없습니다"

            browser.close()

