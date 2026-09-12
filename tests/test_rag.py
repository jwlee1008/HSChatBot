"""
CampusRAG RAG 코어 모듈 유닛 테스트

샘플 데이터 적재 → 유사도 검색 동작 검증.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.embedder import (
    get_chroma_vectorstore,
    get_embedding_model,
    ingest_to_chroma,
    load_notices_from_json,
)


@pytest.fixture(scope="module")
def sample_json_path():
    """테스트용 샘플 JSON 파일 경로를 반환한다."""
    path = Path(__file__).resolve().parent.parent / "data" / "sample_notices.json"
    assert path.exists(), f"샘플 데이터 파일이 없습니다: {path}"
    return str(path)


@pytest.fixture(scope="module")
def chroma_dir():
    """테스트 전용 임시 Chroma DB 디렉토리를 생성/삭제한다."""
    tmp_dir = tempfile.mkdtemp(prefix="campusrag_test_chroma_")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def loaded_vectorstore(sample_json_path, chroma_dir):
    """샘플 데이터를 Chroma DB에 적재하고 벡터스토어를 반환한다."""
    documents = load_notices_from_json(sample_json_path)
    vectorstore = ingest_to_chroma(
        documents,
        persist_directory=chroma_dir,
        collection_name="test_notices",
    )
    return vectorstore


class TestEmbedding:
    """임베딩 모델 관련 테스트."""

    def test_embedding_model_loads(self):
        """임베딩 모델이 정상 로드되는지 확인."""
        model = get_embedding_model()
        assert model is not None

    def test_embedding_produces_vector(self):
        """임베딩 모델이 벡터를 생성하는지 확인."""
        model = get_embedding_model()
        vector = model.embed_query("수강신청 일정을 알려줘")
        assert isinstance(vector, list)
        assert len(vector) > 0
        assert all(isinstance(v, float) for v in vector)


class TestDataLoading:
    """JSON 데이터 로딩 테스트."""

    def test_load_notices(self, sample_json_path):
        """JSON 파일에서 공지사항을 정상 로드하는지 확인."""
        documents = load_notices_from_json(sample_json_path)
        assert len(documents) == 10

    def test_document_has_metadata(self, sample_json_path):
        """로드된 Document에 필요한 메타데이터가 포함되는지 확인."""
        documents = load_notices_from_json(sample_json_path)
        doc = documents[0]
        required_keys = {"id", "title", "source", "category", "date", "url"}
        assert required_keys.issubset(set(doc.metadata.keys()))

    def test_document_content_combines_title_and_body(self, sample_json_path):
        """page_content에 제목과 내용이 결합되는지 확인."""
        documents = load_notices_from_json(sample_json_path)
        doc = documents[0]
        assert doc.metadata["title"] in doc.page_content
        assert len(doc.page_content) > len(doc.metadata["title"])


class TestChromaIngestion:
    """Chroma DB 적재 및 검색 테스트."""

    def test_ingest_count(self, loaded_vectorstore):
        """적재된 문서 수가 올바른지 확인."""
        count = loaded_vectorstore._collection.count()
        assert count == 10

    def test_similarity_search_returns_results(self, loaded_vectorstore):
        """유사도 검색이 결과를 반환하는지 확인."""
        results = loaded_vectorstore.similarity_search("수강신청 일정", k=3)
        assert len(results) == 3

    def test_similarity_search_relevance(self, loaded_vectorstore):
        """유사도 검색 결과가 질의와 관련 있는지 확인."""
        results = loaded_vectorstore.similarity_search("수강신청 일정", k=1)
        assert len(results) == 1
        top_result = results[0]
        # 수강신청 관련 공지가 최상위에 와야 함
        assert "수강신청" in top_result.metadata["title"]

    def test_search_result_has_metadata(self, loaded_vectorstore):
        """검색 결과에 출처 카드용 메타데이터가 포함되는지 확인."""
        results = loaded_vectorstore.similarity_search("장학금 신청", k=1)
        top = results[0]
        assert "url" in top.metadata
        assert "date" in top.metadata
        assert "source" in top.metadata
        assert top.metadata["url"].startswith("https://")

    def test_search_different_queries(self, loaded_vectorstore):
        """다양한 질의에 대해 적절한 결과가 반환되는지 확인."""
        test_cases = [
            ("캡스톤 디자인 경진대회", "캡스톤"),
            ("졸업요건 변경", "졸업요건"),
            ("도서관 운영시간", "도서관"),
        ]
        for query, expected_keyword in test_cases:
            results = loaded_vectorstore.similarity_search(query, k=1)
            assert len(results) >= 1, f"질의 '{query}'에 대한 결과가 없음"
            assert expected_keyword in results[0].metadata["title"], (
                f"질의 '{query}': 기대 키워드 '{expected_keyword}'가 "
                f"결과 '{results[0].metadata['title']}'에 없음"
            )
