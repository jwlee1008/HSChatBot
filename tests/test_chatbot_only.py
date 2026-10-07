"""The chatbot deployment must not depend on archived accounts or schedules."""
import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_startup_never_opens_account_database(tmp_path):
    # Use a fresh interpreter so cached imports cannot hide accidental coupling.
    code = '''
import sys
import config
config.PREWARM_RAG_ON_STARTUP = False

def deny_sqlite(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('chatbot startup must not open a SQLite database')
sys.addaudithook(deny_sqlite)
from backend.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    paths = client.get('/openapi.json').json()['paths']
    assert set(paths) == {'/health', '/api/query', '/api/retrieve'}
    assert not any(m.startswith(('backend.auth', 'backend.db', 'backend.schedules')) for m in sys.modules)
'''
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True,
                   env=dict(os.environ, PREWARM_RAG_ON_STARTUP='false'), timeout=60)


def test_anonymous_chat_returns_answer_and_source(monkeypatch):
    import backend.main as main
    monkeypatch.setattr(main.config, 'PREWARM_RAG_ON_STARTUP', False)
    class Rag:
        def query(self, question, top_k):
            return {'answer': '장학 안내는 공식 공지를 확인하세요.',
                    'sources': [{'title': '장학 안내', 'source': '학교',
                                 'category': '장학', 'date': '2026-09-27',
                                 'url': 'https://www.hansung.ac.kr/', 'content': '공지 본문'}],
                    'status': 'success', 'api_called': False}
    monkeypatch.setattr(main, 'get_or_init_rag', AsyncMock(return_value=Rag()))
    with TestClient(main.app) as client:
        result = client.post('/api/query', json={'question': '장학금 안내', 'top_k': 3})
        assert result.status_code == 200
        assert result.json()['sources'][0]['title'] == '장학 안내'
        assert '공식 공지' in result.json()['answer']
