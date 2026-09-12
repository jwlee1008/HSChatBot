"""
CampusRAG Playwright E2E 브라우저 자동화 테스트

Streamlit 프론트엔드 UI의 핵심 흐름을 자동으로 검증한다.
FastAPI 백엔드 + Streamlit 프론트엔드 모두 실행 중이어야 한다.

사용법:
    # 백엔드 + 프론트엔드 먼저 기동
    uvicorn backend.main:app --port 8000 &
    streamlit run frontend/app.py --server.port 8501 --server.headless true &

    # E2E 테스트 실행
    pytest tests/test_e2e.py -v
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def servers():
    """백엔드 + 프론트엔드 서버를 기동하고 테스트 후 종료한다."""
    venv_python = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python")

    # 백엔드 서버 기동
    backend = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "backend.main:app", "--port", "8000"],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 프론트엔드 서버 기동
    frontend = subprocess.Popen(
        [
            venv_python, "-m", "streamlit", "run", "frontend/app.py",
            "--server.port", "8501", "--server.headless", "true",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 서버 기동 대기
    time.sleep(8)

    yield {"backend": backend, "frontend": frontend}

    # 테스트 후 서버 종료
    backend.terminate()
    frontend.terminate()
    backend.wait(timeout=5)
    frontend.wait(timeout=5)


class TestE2EStreamlit:
    """Streamlit UI E2E 테스트."""

    def test_page_loads(self, servers):
        """Streamlit 페이지가 정상 로드되는지 확인."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://localhost:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(3000)

            # 페이지 타이틀 확인
            assert "CampusRAG" in page.content()

            browser.close()

    def test_chat_input_exists(self, servers):
        """채팅 입력창이 존재하는지 확인."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://localhost:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(3000)

            # 채팅 입력창 존재 확인
            chat_input = page.query_selector("textarea, input[type='text']")
            assert chat_input is not None, "채팅 입력창이 없습니다"

            browser.close()

    def test_sidebar_shows_server_status(self, servers):
        """사이드바에 서버 연결 상태가 표시되는지 확인."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("http://localhost:8501", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(3000)

            content = page.content()
            # 서버 연결 상태 또는 설정 섹션이 표시되는지 확인
            assert "설정" in content or "서버" in content

            browser.close()
