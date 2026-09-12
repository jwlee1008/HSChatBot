"""
CampusRAG FastAPI 백엔드 API 테스트

FastAPI TestClient를 사용하여 엔드포인트를 검증한다.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """운영 DB 대신 별도 샘플 DB를 사용하는 API 테스트."""
    from core.embedder import ingest_to_chroma, load_notices_from_json
    import core.rag

    sample = Path(__file__).resolve().parent.parent / "data" / "sample_notices.json"
    store = ingest_to_chroma(
        load_notices_from_json(str(sample)),
        persist_directory=str(tmp_path_factory.mktemp("api_chroma")),
        collection_name="api_tests",
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(core.rag, "get_chroma_vectorstore", lambda: store)
        with TestClient(app) as c:
            yield c


class TestHealthEndpoint:
    """헬스 체크 엔드포인트 테스트."""

    def test_health_returns_200(self, client):
        """헬스 체크가 200을 반환하는지 확인."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_fields(self, client):
        """헬스 체크 응답에 필수 필드가 포함되는지 확인."""
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data
        assert "doc_count" in data
        assert data["doc_count"] >= 1


class TestRetrieveEndpoint:
    """검색 전용 엔드포인트 테스트."""

    def test_retrieve_returns_results(self, client):
        """검색 API가 결과를 반환하는지 확인."""
        resp = client.post(
            "/api/retrieve",
            json={"question": "수강신청 일정", "top_k": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 3
        assert len(data["contents"]) == 3

    def test_retrieve_source_card_fields(self, client):
        """검색 결과 출처 카드에 필수 필드가 포함되는지 확인."""
        resp = client.post(
            "/api/retrieve",
            json={"question": "장학금", "top_k": 1},
        )
        data = resp.json()
        card = data["results"][0]
        assert "title" in card
        assert "source" in card
        assert "date" in card
        assert "url" in card
        assert "category" in card

    def test_retrieve_relevance(self, client):
        """검색 결과가 질의와 관련 있는지 확인."""
        resp = client.post(
            "/api/retrieve",
            json={"question": "도서관 운영시간", "top_k": 1},
        )
        data = resp.json()
        assert "도서관" in data["results"][0]["title"]

    def test_retrieve_empty_question_rejected(self, client):
        """빈 질문이 거부되는지 확인."""
        resp = client.post(
            "/api/retrieve",
            json={"question": "", "top_k": 3},
        )
        assert resp.status_code == 422

    def test_retrieve_top_k_range(self, client):
        """top_k 범위 검증 (1~10)."""
        resp = client.post(
            "/api/retrieve",
            json={"question": "테스트", "top_k": 5},
        )
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 5
