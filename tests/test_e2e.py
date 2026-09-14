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

import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    """현재 Python으로 서버를 실행하고 준비 상태와 실패 로그를 확인한다."""
    root = Path(__file__).resolve().parent.parent
    log_dir = tmp_path_factory.mktemp("e2e_servers")
    home_dir = tmp_path_factory.mktemp("st_home")
    commands = {
        "backend": [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8000"],
        "frontend": [sys.executable, "-m", "streamlit", "run", "frontend/app.py",
                     "--server.port", "8501", "--server.headless", "true"],
    }
    endpoints = {
        "backend": "http://localhost:8000/health",
        "frontend": "http://localhost:8501/_stcore/health",
    }
    processes = {}
    logs = {}
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    try:
        for name, command in commands.items():
            logs[name] = (log_dir / f"{name}.log").open("w")
            processes[name] = subprocess.Popen(
                command, cwd=str(root), stdout=logs[name], stderr=subprocess.STDOUT, env=env,
            )
        deadline = time.monotonic() + 90
        pending = set(processes)
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                if processes[name].poll() is not None:
                    pytest.fail(f"{name} 서버 조기 종료")
                try:
                    with urlopen(endpoints[name], timeout=1) as response:
                        if response.status == 200:
                            pending.remove(name)
                except (URLError, TimeoutError):
                    pass
            if pending:
                time.sleep(0.5)
        if pending:
            pytest.fail(f"서버 준비 시간 초과: {sorted(pending)}")
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
            # pytest가 실패한 테스트/fixture의 캡처 출력에 로그를 첨부한다.
            print(f"{name} server log:\n{(log_dir / f'{name}.log').read_text()}")


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
