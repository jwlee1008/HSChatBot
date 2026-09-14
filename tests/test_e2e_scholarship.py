"""
CampusRAG 국가장학금 Playwright E2E 브라우저 및 UI 통합 테스트.

검증 항목:
1. Mock 기반 프론트엔드/백엔드 인터랙션 테스트:
   - 검색 결과 출처 카드(제목, 출처, 날짜, 원문 링크) 렌더링 검증
   - 원문 보기 링크가 올바른 URL(artclView.do)로 연결되는지 검증
2. 라이브 서버 E2E 브라우저 테스트 (FastAPI + Streamlit + Playwright):
   - 질문 입력 -> AI 응답 생성 및 출처 카드 표시 확인
   - 원문 링크(223971) 포함 여부 검증
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from frontend.app import get_source_card_html


class TestScholarshipSourceCardMock:
    """프론트엔드 출처 카드 렌더링 및 링크 데이터 정합성 mock 검증."""

    def test_render_source_card_html(self):
        """실제 frontend.app.get_source_card_html을 호출하여 223971 공지 원문 링크와 올바른 필드를 포함하는지 검증."""
        source_data = {
            "title": "2026년 2학기 국가장학금 2차 신청 안내",
            "source": "학교본부 (학생복지팀)",
            "category": "장학",
            "date": "2026-08-12",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do",
        }

        # 실제 frontend/app.py의 get_source_card_html 함수 호출 검증
        card_html = get_source_card_html(source_data)
        assert source_data["url"] in card_html
        assert "223971" in card_html
        assert source_data["title"] in card_html
        assert source_data["source"] in card_html
        assert source_data["category"] in card_html
        assert source_data["date"] in card_html
        assert 'target="_blank"' in card_html


@pytest.fixture(scope="module")
def scholarship_servers(tmp_path_factory):
    """E2E 테스트용 백엔드(포트 8008) 및 프론트엔드(포트 8508) 기동 fixture."""
    root = Path(__file__).resolve().parent.parent
    log_dir = tmp_path_factory.mktemp("scholarship_e2e_logs")

    env = os.environ.copy()
    backend_env = env.copy()
    backend_env["CHROMA_PERSIST_DIR"] = "data/eval_chroma_db"
    backend_env["CHROMA_COLLECTION_NAME"] = "eval_notices"
    backend_env["LLM_PROVIDER"] = "local"
    backend_env["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")

    frontend_env = env.copy()
    frontend_env["API_BASE_URL"] = "http://localhost:8008"
    frontend_env["HOME"] = str(log_dir)
    frontend_env["STREAMLIT_CONFIG_DIR"] = str(log_dir)
    frontend_env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    proc_configs = {
        "backend": {
            "cmd": [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8008"],
            "env": backend_env,
        },
        "frontend": {
            "cmd": [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "frontend/app.py",
                "--server.port",
                "8508",
                "--server.headless",
                "true",
            ],
            "env": frontend_env,
        },
    }
    endpoints = {
        "backend": "http://localhost:8008/health",
        "frontend": "http://localhost:8508/_stcore/health",
    }
    processes = {}
    logs = {}

    try:
        for name, cfg in proc_configs.items():
            logs[name] = (log_dir / f"{name}.log").open("w")
            processes[name] = subprocess.Popen(
                cfg["cmd"],
                cwd=str(root),
                env=cfg["env"],
                stdout=logs[name],
                stderr=subprocess.STDOUT,
            )

        deadline = time.monotonic() + 45
        pending = set(processes)
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                if processes[name].poll() is not None:
                    logs[name].flush()
                    log_content = (log_dir / f"{name}.log").read_text()
                    pytest.fail(f"{name} 서버 조기 종료 (code {processes[name].returncode}):\n{log_content}")
                try:
                    with urlopen(endpoints[name], timeout=1) as response:
                        if response.status == 200:
                            pending.remove(name)
                except (URLError, TimeoutError):
                    pass
            if pending:
                time.sleep(0.5)

        if pending:
            details = {}
            for name in pending:
                logs[name].flush()
                details[name] = (log_dir / f"{name}.log").read_text()
            pytest.fail(f"서버 준비 시간 초과: {sorted(pending)}\n로그: {details}")

        yield processes
    finally:
        for p in processes.values():
            p.terminate()
        for p in processes.values():
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        for log in logs.values():
            log.close()


def _select_ai_mode(page):
    """사이드바에서 AI 답변 + 검색 (RAG) 라디오 모드를 선택한다."""
    page.wait_for_selector("[data-testid='stRadio']", timeout=15000)
    radio = page.locator("[data-testid='stRadio'] label").filter(has_text="AI 답변")
    if radio.count() > 0:
        radio.first.click()
    else:
        page.get_by_text("🤖 AI 답변 + 검색 (RAG)").click()
    page.wait_for_timeout(1000)


def _submit_chat_question(page, question: str):
    """채팅 입력창을 찾아 질문을 전송한다."""
    page.wait_for_selector("textarea[data-testid='stChatInputTextArea']", timeout=15000)
    chat_input = page.locator("textarea[data-testid='stChatInputTextArea']")
    chat_input.fill(question)
    page.wait_for_timeout(300)
    submit_btn = page.locator("button[data-testid='stChatInputSubmitButton']")
    if submit_btn.count() > 0 and submit_btn.is_enabled():
        submit_btn.click()
    else:
        chat_input.press("Enter")


def _wait_for_assistant_response(page, timeout=60000):
    """어시스턴트의 응답 생성이 완료될 때까지 스피너 소멸을 대기하고 어시스턴트 메시지 요소를 반환한다."""
    try:
        page.locator("[data-testid='stSpinner']").wait_for(state="attached", timeout=5000)
    except Exception:
        pass
    page.locator("[data-testid='stSpinner']").wait_for(state="detached", timeout=timeout)
    page.wait_for_timeout(1000)
    messages = page.locator("[data-testid='stChatMessage']")
    return messages.last


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_E2E") != "1",
    reason="실제 LLM/UI E2E 테스트는 로컬 GPU 및 루프백 네트워크 환경(RUN_LIVE_LLM_E2E=1)에서만 실행됩니다.",
)
class TestScholarshipLiveE2E:
    """라이브 Playwright 브라우저 E2E 테스트 (UI 상호작용, AI 답변, 출처 원문 확인)."""

    def test_browser_page_and_chat(self, scholarship_servers):
        """브라우저에서 페이지가 로드되고 입력창이 정상 상호작용 가능한지 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            page.goto("http://localhost:8508", wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            # 제목 및 사이드바 확인
            content = page.content()
            assert "CampusRAG" in content

            # 채팅 입력창 존재 확인
            chat_input = page.query_selector("textarea, input[type='text']")
            assert chat_input is not None, "채팅 입력창이 렌더링되지 않았습니다"

            browser.close()

    def test_e2e_ai_mode_apply_period(self, scholarship_servers):
        """시나리오 1: AI 모드 선택 -> 신청 마감 질문 -> 답변 확인 -> 출처 클릭 -> 원문 제목 확인."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})

            # 원문 링크 클릭 시 외부망 의존성 없이 결정적 검증을 위한 라우트 가로채기
            context.route(
                "**/*artclView.do*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body="""<!DOCTYPE html>
<html>
<head><title>2026년 2학기 국가장학금 2차 신청 안내</title></head>
<body>
  <h1>2026년 2학기 국가장학금 2차 신청 안내</h1>
  <p>신청기간: 2026. 8. 14.(금) 09:00 ~ 9. 9.(수) 18:00</p>
  <p>가구원동의: 2026. 8. 14.(금) 09:00 ~ 9. 16.(수) 18:00</p>
</body>
</html>""",
                ),
            )

            page = context.new_page()
            page.goto("http://localhost:8508", wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            # 1. AI 모드 라디오 버튼 선택
            _select_ai_mode(page)

            # 2. 국가장학금 신청 기간 질문 입력
            _submit_chat_question(page, "2026년 2학기 국가장학금 2차 신청 기간이 언제까지야?")

            # 3. AI 답변 생성 완료 대기 및 내용 확인
            assistant_msg = _wait_for_assistant_response(page, timeout=60000)
            ans_text = assistant_msg.inner_text()
            assert "국가장학금" in ans_text
            assert "9월" in ans_text or "8월" in ans_text

            # 4. 출처 카드 렌더링 확인 (223971 공지)
            page.wait_for_selector("text=2026년 2학기 국가장학금 2차 신청 안내", timeout=15000)
            source_card = page.locator("text=2026년 2학기 국가장학금 2차 신청 안내").first
            assert source_card.is_visible()

            # 5. 출처 링크 클릭 -> 원문 제목 확인
            with page.expect_popup() as popup_info:
                page.locator("a:has-text('원문 보기')").first.click()
            popup = popup_info.value
            popup.wait_for_load_state()
            popup_title = popup.title()
            popup_body = popup.content()
            assert "2026년 2학기 국가장학금 2차 신청 안내" in popup_title or "2026년 2학기 국가장학금 2차 신청 안내" in popup_body

            popup.close()
            browser.close()

    def test_e2e_ai_mode_period_distinction(self, scholarship_servers):
        """시나리오 2: AI 모드 선택 -> 신청 마감 vs 동의 마감 구분 질문 -> 답변 및 출처 확인."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            page.goto("http://localhost:8508", wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            _select_ai_mode(page)
            _submit_chat_question(page, "국가장학금 신청 마감일이랑 가구원 동의 마감일이 같아?")

            # AI 응답 대기
            assistant_msg = _wait_for_assistant_response(page, timeout=60000)
            ans_text = assistant_msg.inner_text()
            assert "국가장학금" in ans_text
            assert "동의" in ans_text

            # 출처 카드 노출 확인
            assert page.locator("a:has-text('원문 보기')").count() > 0

            browser.close()

    def test_e2e_ai_mode_irrelevant_abstain(self, scholarship_servers):
        """시나리오 3: 무관 질문 -> 관련 공지 미발견 유보 응답 확인 및 출처 미노출 검증."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            page.goto("http://localhost:8508", wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            _select_ai_mode(page)
            _submit_chat_question(page, "파이썬 코드로 퀵소트 구현하는 방법 알려줘")

            # 유보 응답 대기
            assistant_msg = _wait_for_assistant_response(page, timeout=60000)
            ans_text = assistant_msg.inner_text()
            assert "관련 공지를 찾지 못했습니다" in ans_text

            # 무관 질문이므로 참고 공지사항 출처 카드가 없어야 함
            assert page.locator("text=📌").count() == 0
            assert page.locator("text=참고 공지사항").count() == 0
            assert page.locator("a:has-text('원문 보기')").count() == 0

            browser.close()
