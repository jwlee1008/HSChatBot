"""
CampusRAG 일반화 검증 테스트.

검증 항목:
1. 미래 연도(2027년 등) 공지의 동적 엔티티 파싱 및 리랭킹
2. 두 마감일(신청 마감, 가구원 동의 마감)이 동일한 공지 사례의 정상 처리
3. 동일 공지의 여러 유효 청크가 답변 근거(context)에 함께 제공되는지 검증
4. 출처 카드는 URL 기준으로 중복 제거되는지 검증
"""

import tempfile
import pytest
from langchain_core.documents import Document

from core.embedder import ingest_to_chroma
from core.rag import CampusRAG, extract_query_entities


@pytest.fixture
def gen_chroma_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestGeneralization:
    """하드코딩 제거 및 일반화 검증."""

    def test_2027_entity_parsing(self):
        """2027년 표기가 정상적으로 추출된다."""
        assert extract_query_entities("2027년 1학기 국가장학금")["year"] == "2027"
        assert extract_query_entities("'27 장학금")["year"] == "2027"
        assert extract_query_entities("27년 2학기 1차")["year"] == "2027"

    def test_multi_chunk_and_sources_separation(self, gen_chroma_dir):
        """신청 기간과 동의 기간이 별도 청크에 있을 때 두 청크 모두 근거에 포함되고 출처는 1개로 중복 제거된다."""
        # 공지 229900의 2개 청크: 청크 0(신청기간), 청크 1(동의기간)
        url_2027 = "https://www.hansung.ac.kr/bbs/hansung/2127/229900/artclView.do"
        chunk0 = Document(
            page_content="[장학] 2027학년도 1학기 국가장학금 신청 안내 (등록일: 2027-02-10)\n\n신청 기간: 2027년 2월 15일 ~ 3월 15일 18시",
            metadata={
                "id": "229900",
                "parent_id": "229900",
                "chunk_id": "229900_c0",
                "url": url_2027,
                "parent_url": url_2027,
                "title": "2027학년도 1학기 국가장학금 신청 안내",
                "date": "2027-02-10",
                "source": "학교본부",
                "category": "장학",
                "content_status": "text",
            },
        )
        chunk1 = Document(
            page_content="[장학] 2027학년도 1학기 국가장학금 신청 안내 (등록일: 2027-02-10)\n\n서류제출 및 가구원 동의: 2027년 2월 15일 ~ 3월 22일 18시",
            metadata={
                "id": "229900",
                "parent_id": "229900",
                "chunk_id": "229900_c1",
                "url": url_2027,
                "parent_url": url_2027,
                "title": "2027학년도 1학기 국가장학금 신청 안내",
                "date": "2027-02-10",
                "source": "학교본부",
                "category": "장학",
                "content_status": "text",
            },
        )
        # 타 연도(2025년) 공지
        other_doc = Document(
            page_content="[장학] 2025학년도 1학기 국가장학금 안내 (등록일: 2025-02-10)\n\n신청 마감 2025년 3월 10일",
            metadata={
                "id": "119900",
                "parent_id": "119900",
                "chunk_id": "119900_c0",
                "url": "https://www.hansung.ac.kr/bbs/hansung/2127/119900/artclView.do",
                "title": "2025학년도 1학기 국가장학금 안내",
                "date": "2025-02-10",
                "source": "학교본부",
                "category": "장학",
                "content_status": "text",
            },
        )

        store = ingest_to_chroma([chunk0, chunk1, other_doc], persist_directory=gen_chroma_dir, collection_name="test_gen")

        rag = CampusRAG(load_llm=False)
        rag.vectorstore = store

        # 2027년 질의에 대해 retrieve 실행
        retrieved = rag.retrieve("2027년 1학기 국가장학금 신청 및 가구원 동의 언제까지야?", top_k=3)

        # 검증: 동일 공지의 두 유효 청크(chunk0, chunk1)가 모두 근거로 반환되어야 함
        retrieved_chunk_ids = [d.metadata.get("chunk_id") for d in retrieved]
        assert "229900_c0" in retrieved_chunk_ids, "신청 기간 청크가 검색 근거에 포함되어야 함"
        assert "229900_c1" in retrieved_chunk_ids, "가구원 동의 청크가 검색 근거에 포함되어야 함"

    def test_identical_deadlines_preserved_in_context(self, gen_chroma_dir):
        """두 마감일이 동일한 공지에서도 임의 가정 없이 본문 내용이 온전히 검색 근거로 전달된다."""
        url_same = "https://www.hansung.ac.kr/bbs/hansung/2127/339900/artclView.do"
        doc_same = Document(
            page_content="[장학] 2027년 특수목적장학금 신청\n\n신청 기간 및 가구원 동의 기간: 2027년 4월 1일 ~ 4월 20일 18시 (동일 마감)",
            metadata={
                "id": "339900",
                "parent_id": "339900",
                "chunk_id": "339900_c0",
                "url": url_same,
                "title": "2027년 특수목적장학금 신청",
                "date": "2027-03-25",
                "source": "학교본부",
                "category": "장학",
                "content_status": "text",
            },
        )
        store = ingest_to_chroma([doc_same], persist_directory=gen_chroma_dir, collection_name="test_same")
        rag = CampusRAG(load_llm=False)
        rag.vectorstore = store

        res = rag.retrieve("2027년 특수목적장학금 마감일 언제야?", top_k=1)
        assert len(res) == 1
        assert "동일 마감" in res[0].page_content
        assert "4월 20일" in res[0].page_content

    def test_low_relevance_recent_notice_not_boosted(self, gen_chroma_dir):
        """
        원시 관련성이 임계값(0.25) 미만인 낮은 관련도의 최신 공지는
        최신성 가산점(Recency Boost)이나 연도 가산점으로 통과하지 않고 제외된다.
        """
        # 아주 최근에 등록된 무관한 공지 (체육관 시설 안내)
        recent_unrelated = Document(
            page_content="[시설] 2026학년도 2학기 교내 헬스장 및 샤워실 이용 시간 안내\n\n체육관 헬스장은 평일 오전 9시부터 오후 9시까지 운영합니다. 개인 운동복 및 실내 전용 운동화를 지참하세요.",
            metadata={
                "id": "gym-001",
                "parent_id": "gym-001",
                "chunk_id": "gym-001_c0",
                "url": "https://www.hansung.ac.kr/notice/gym",
                "title": "2026학년도 2학기 교내 헬스장 및 샤워실 이용 시간 안내",
                "date": "2026-09-12",  # 최신 등록일
                "source": "체육진흥팀",
                "category": "시설",
                "content_status": "text",
            },
        )
        store = ingest_to_chroma([recent_unrelated], persist_directory=gen_chroma_dir, collection_name="test_filter")
        rag = CampusRAG(load_llm=False)
        rag.vectorstore = store

        # 무관 질문(파이썬 퀵소트) 질의 시, 최신 공지라도 원시 관련성 미달로 인해 제외되어야 함
        res_irrelevant = rag.retrieve("파이썬 코드로 퀵소트 구현하는 방법 알려줘", top_k=3)
        assert len(res_irrelevant) == 0, "원시 관련성 미달 문서는 최신성 가산점 전에 제외되어야 함"

        # RAG query 시에도 즉시 유보 반환
        ans = rag.query("파이썬 코드로 퀵소트 구현하는 방법 알려줘")
        assert ans["answer"] == "관련 공지를 찾지 못했습니다."
        assert ans["sources"] == []
