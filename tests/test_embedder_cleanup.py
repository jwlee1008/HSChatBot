"""
CampusRAG 공지사항 갱신(upsert) 시 불필요한 이전 청크 정리 테스트.

검증 항목:
1. 본문 축소 시 이전 청크 정리 (3개 청크 -> 1개 청크 전환 시 stale 청크 삭제)
2. 기존 단일 문서 모드에서 청킹 모드로 전환 시 구형 ID 삭제
3. 입력에 없는 다른 공지는 완전 보존
4. 적재 중간 실패 시 기존 청크 안전 보존 (롤백 무결성)
"""

import tempfile
import pytest
from langchain_core.documents import Document
from unittest.mock import patch

from core.embedder import ingest_to_chroma


@pytest.fixture
def temp_chroma_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestEmbedderStaleChunkCleanup:
    """upsert 시 이전 청크 정리 기능 테스트."""

    def test_body_reduction_removes_stale_chunks(self, temp_chroma_dir):
        """본문이 축소되어 청크 수가 줄어든 경우, 이전 청크가 정상 삭제된다."""
        # 1. 공지 A(3개 청크)와 공지 B(1개 청크) 적재
        a_c0 = Document(page_content="A 내용 1", metadata={"parent_id": "notice-A", "chunk_id": "notice-A_c0", "url": "https://h.ac.kr/A"})
        a_c1 = Document(page_content="A 내용 2", metadata={"parent_id": "notice-A", "chunk_id": "notice-A_c1", "url": "https://h.ac.kr/A"})
        a_c2 = Document(page_content="A 내용 3", metadata={"parent_id": "notice-A", "chunk_id": "notice-A_c2", "url": "https://h.ac.kr/A"})
        b_c0 = Document(page_content="B 내용 1", metadata={"parent_id": "notice-B", "chunk_id": "notice-B_c0", "url": "https://h.ac.kr/B"})

        vs = ingest_to_chroma([a_c0, a_c1, a_c2, b_c0], persist_directory=temp_chroma_dir, collection_name="test_clean")
        assert set(vs.get()["ids"]) == {"notice-A_c0", "notice-A_c1", "notice-A_c2", "notice-B_c0"}

        # 2. 공지 A가 축소되어 1개 청크만 생성되는 상황으로 업데이트
        a_c0_new = Document(page_content="A 축소 내용", metadata={"parent_id": "notice-A", "chunk_id": "notice-A_c0", "url": "https://h.ac.kr/A"})
        vs_updated = ingest_to_chroma([a_c0_new], persist_directory=temp_chroma_dir, collection_name="test_clean")

        # 3. 검증: A_c1, A_c2는 삭제되고 A_c0만 남음, B_c0는 그대로 보존됨
        current_ids = set(vs_updated.get()["ids"])
        assert current_ids == {"notice-A_c0", "notice-B_c0"}

    def test_legacy_single_doc_transition_removes_old_id(self, temp_chroma_dir):
        """기존 단일 문서(ID: notice-legacy)가 청킹 모드(notice-legacy_c0)로 전환되면 구형 ID가 삭제된다."""
        # 1. 단일 문서 모드로 적재된 공지
        legacy_doc = Document(
            page_content="단일 문서 내용",
            metadata={"id": "notice-legacy", "url": "https://h.ac.kr/legacy", "title": "레거시 공지"}
        )
        vs = ingest_to_chroma([legacy_doc], persist_directory=temp_chroma_dir, collection_name="test_legacy")
        # 청크 ID가 없으므로 URL 해시 또는 id 기반으로 ID 생성됨
        initial_ids = vs.get()["ids"]
        assert len(initial_ids) == 1

        # 2. 청킹 모드로 2개 청크 적재
        c0 = Document(page_content="청크 0", metadata={"parent_id": "notice-legacy", "chunk_id": "notice-legacy_c0", "url": "https://h.ac.kr/legacy"})
        c1 = Document(page_content="청크 1", metadata={"parent_id": "notice-legacy", "chunk_id": "notice-legacy_c1", "url": "https://h.ac.kr/legacy"})

        vs_updated = ingest_to_chroma([c0, c1], persist_directory=temp_chroma_dir, collection_name="test_legacy")
        current_ids = set(vs_updated.get()["ids"])

        assert current_ids == {"notice-legacy_c0", "notice-legacy_c1"}
        assert initial_ids[0] not in current_ids

    def test_untouched_notices_strictly_preserved(self, temp_chroma_dir):
        """입력에 포함되지 않은 다른 공지는 어떠한 경우에도 삭제되지 않는다."""
        doc1 = Document(page_content="공지 1", metadata={"parent_id": "N1", "chunk_id": "N1_c0", "url": "http://1"})
        doc2 = Document(page_content="공지 2", metadata={"parent_id": "N2", "chunk_id": "N2_c0", "url": "http://2"})
        doc3 = Document(page_content="공지 3", metadata={"parent_id": "N3", "chunk_id": "N3_c0", "url": "http://3"})

        vs = ingest_to_chroma([doc1, doc2, doc3], persist_directory=temp_chroma_dir, collection_name="test_untouched")
        assert len(vs.get()["ids"]) == 3

        # N1만 수정
        doc1_new = Document(page_content="공지 1 수정", metadata={"parent_id": "N1", "chunk_id": "N1_c0", "url": "http://1"})
        vs_updated = ingest_to_chroma([doc1_new], persist_directory=temp_chroma_dir, collection_name="test_untouched")

        current_ids = set(vs_updated.get()["ids"])
        assert current_ids == {"N1_c0", "N2_c0", "N3_c0"}

    def test_failed_insertion_preserves_old_chunks(self, temp_chroma_dir):
        """적재 도중 예외가 발생하면 삭제가 실행되지 않고 기존 청크가 안전하게 보존된다."""
        doc1_c0 = Document(page_content="원본 0", metadata={"parent_id": "FAIL_TEST", "chunk_id": "FAIL_TEST_c0", "url": "http://f"})
        doc1_c1 = Document(page_content="원본 1", metadata={"parent_id": "FAIL_TEST", "chunk_id": "FAIL_TEST_c1", "url": "http://f"})

        vs = ingest_to_chroma([doc1_c0, doc1_c1], persist_directory=temp_chroma_dir, collection_name="test_fail")
        assert set(vs.get()["ids"]) == {"FAIL_TEST_c0", "FAIL_TEST_c1"}

        # add_documents에서 에러 발생 모의
        from langchain_chroma import Chroma
        doc1_new = Document(page_content="새로운 내용", metadata={"parent_id": "FAIL_TEST", "chunk_id": "FAIL_TEST_c0", "url": "http://f"})
        with patch.object(Chroma, "add_documents", side_effect=RuntimeError("디스크 쓰기 실패")):
            with pytest.raises(RuntimeError, match="디스크 쓰기 실패"):
                # 같은 디렉토리와 컬렉션으로 ingest 시도
                ingest_to_chroma([doc1_new], persist_directory=temp_chroma_dir, collection_name="test_fail")

        # 기존 청크가 삭제되지 않고 온전히 남아있는지 확인
        current_vs = ingest_to_chroma([doc1_c0, doc1_c1], persist_directory=temp_chroma_dir, collection_name="test_fail")
        assert set(current_vs.get()["ids"]) == {"FAIL_TEST_c0", "FAIL_TEST_c1"}
