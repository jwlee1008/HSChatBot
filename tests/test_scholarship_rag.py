"""
CampusRAG 장학금 RAG 파이프라인 단위 및 회귀 테스트.

검증 항목:
1. 본문 청킹 (split_notice_into_chunks): 헤더 보존, 500자/80자 오버랩, 메타데이터 연계
2. 엔티티 추출 (extract_query_entities): 연도, 학기, 차수 파싱
3. 무관 질문 필터링 (MIN_RELEVANCE_THRESHOLD)
4. 리랭킹 규칙: 연도/학기/차수 가중치, title_only 감점, 최신성 보정
5. 공지 출처 URL 단위 디듀플리케이션
"""

import sys
from pathlib import Path
import pytest
from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.embedder import split_notice_into_chunks
from core.rag import extract_query_entities, MIN_RELEVANCE_THRESHOLD


class TestChunking:
    """공지사항 청킹 로직 테스트."""

    def test_short_notice_remains_single_chunk(self):
        """500자 이하의 짧은 공지는 1개의 청크로 유지된다."""
        doc = Document(
            page_content="[제목] 단기 공지\n[출처] 학교본부 | [등록일] 2026-08-10\n짧은 본문 내용입니다.",
            metadata={"id": "doc-01", "url": "https://example.com/1", "title": "단기 공지"},
        )
        chunks = split_notice_into_chunks(doc, chunk_size=500, chunk_overlap=80)
        assert len(chunks) == 1
        assert chunks[0].metadata["chunk_id"] == "doc-01_c0"
        assert chunks[0].metadata["total_chunks"] == 1
        assert chunks[0].metadata["parent_id"] == "doc-01"

    def test_long_notice_is_split_with_header_preserved(self):
        """500자 초과 공지는 분할되며 각 청크마다 헤더 맥락이 보존된다."""
        header = "[제목] 2026학년도 2학기 국가장학금 2차 신청 안내\n[출처] 학교본부 | [등록일] 2026-08-12\n\n"
        body = "본문 내용입니다. " * 60  # 약 600자 이상
        doc = Document(
            page_content=header + body,
            metadata={
                "id": "doc-long",
                "url": "https://example.com/long",
                "title": "2026학년도 2학기 국가장학금 2차 신청 안내",
                "category": "장학",
                "source": "학교본부",
                "date": "2026-08-12",
            },
        )
        chunks = split_notice_into_chunks(doc, chunk_size=500, chunk_overlap=80)
        assert len(chunks) > 1
        for i, ch in enumerate(chunks):
            assert ch.metadata["chunk_id"] == f"doc-long_c{i}"
            assert ch.metadata["parent_id"] == "doc-long"
            assert ch.metadata["parent_url"] == "https://example.com/long"
            # 각 청크가 제목 헤더 맥락을 포함하는지 확인
            assert "2026학년도 2학기 국가장학금 2차 신청 안내" in ch.page_content
            assert "[장학]" in ch.page_content


class TestEntityExtraction:
    """질의 엔티티 추출 테스트."""

    def test_extract_year_formats(self):
        """다양한 연도 표기를 올바르게 파싱한다."""
        assert extract_query_entities("2026년 2학기 장학금")["year"] == "2026"
        assert extract_query_entities("2025학년도 국가장학금")["year"] == "2025"
        assert extract_query_entities("24년 1차 신청")["year"] == "2024"
        assert extract_query_entities("'26 장학금")["year"] == "2026"
        assert "year" not in extract_query_entities("국가장학금 신청 기간 알려줘")

    def test_extract_semester_and_round(self):
        """학기와 차수를 올바르게 파싱한다."""
        res = extract_query_entities("2026년 2학기 2차 신청")
        assert res["year"] == "2026"
        assert res["semester"] == "2학기"
        assert res["round"] == "2차"

        res2 = extract_query_entities("1학기 1차 신청 일정")
        assert res2.get("semester") == "1학기"
        assert res2.get("round") == "1차"
        assert "year" not in res2


class TestRAGBehavior:
    """RAG 파이프라인 임계값 및 유보(Abstain) 처리 테스트."""

    def test_threshold_value(self):
        """무관 질문 차단 임계값이 올바르게 설정되어 있다."""
        assert MIN_RELEVANCE_THRESHOLD >= 0.0
        assert MIN_RELEVANCE_THRESHOLD <= 0.40
