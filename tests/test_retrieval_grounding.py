"""
CampusRAG 검색 근거 누락 및 지식 검색 회귀 테스트

취업멘토링 신청기간, 편입생 제외조건, 짧은 단축검색어(TOPCIT 평가),
상시 안내/FAQ 보존 여부를 검증한다.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from langchain_core.documents import Document

import config
from core.rag import CampusRAG, extract_query_entities


class TestRetrievalGrounding:
    """검색 근거 누락 방지 및 청크 선택 최적화 검증 (완전 격리 mock 기반)."""

    def _create_mock_rag(self):
        """외부 DB나 임베딩 모델 로드 없이 완전 격리된 Mock CampusRAG 인스턴스를 생성한다."""
        rag = CampusRAG.__new__(CampusRAG)
        rag.vectorstore = MagicMock()
        rag.llm = None
        rag.chain = None
        rag.provider = "gemini"
        rag.gemini_model_name = "gemini-3.8-flash"
        return rag

    def test_query_entities_extraction(self):
        """엔티티 추출이 연도, 학기, 차수를 올바르게 추출하는지 검증."""
        res = extract_query_entities("2026학년도 2학기 편입생 신청")
        assert res.get("year") == "2026"
        assert res.get("semester") == "2학기"

        res2 = extract_query_entities("24-1학기 국가장학금 2차 신청")
        assert res2.get("year") == "2024"
        assert res2.get("semester") == "1학기"
        assert res2.get("round") == "2차"

    def test_short_query_lexical_preservation_real(self):
        """
        짧은 검색어 'TOPCIT 평가'가 고유 전문 약어(TOPCIT)를 포함할 때
        어휘 매칭 보너스(+0.08)를 받아 정상 구제되는지 실제 retrieve 메서드를 통해 검증.
        """
        rag = self._create_mock_rag()

        doc_topcit = Document(
            page_content="제26회 TOPCIT(소프트웨어 역량검정 시험) 정기평가 시행 안내입니다.",
            metadata={
                "title": "한성공지\n[SW중심] 제26회 TOPCIT(소프트웨어 역량검정 시험) 정기평가 시행 안내",
                "date": "2026-09-04",
                "url": "https://www.hansung.ac.kr/bbs/1",
                "source_type": "notice",
                "content_status": "text",
            }
        )
        doc_other = Document(
            page_content="2026학년도 교내 장학금 신청 안내입니다.",
            metadata={
                "title": "2026학년도 교내 장학금 신청 안내",
                "date": "2026-09-01",
                "url": "https://www.hansung.ac.kr/bbs/2",
                "source_type": "notice",
                "content_status": "text",
            }
        )

        # 원시 점수: TOPCIT 공지는 0.21 (0.25 미만), 타 공지는 0.18
        rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
            (doc_topcit, 0.21),
            (doc_other, 0.18),
        ]

        results = rag.retrieve("TOPCIT 평가", top_k=3, min_threshold=0.25)
        # TOPCIT 공지는 0.21 + 0.08 = 0.29로 0.25를 통과해야 함
        assert len(results) == 1
        assert "TOPCIT" in results[0].metadata["title"]

    def test_irrelevant_query_not_bypassed_by_generic_words(self):
        """
        '2026년 아이폰 스펙 알려줘' 및 '파이썬으로 이진 탐색 트리 구현하는 코드 짜줘'처럼
        일반 단어(2026년, 탐색 등)만 우연히 겹치는 무관 질문은 0.08 가산점을 받지 못하고
        임계값(0.25) 미만으로 확실히 차단(빈 결과 반환)되는지 검증.
        """
        rag = self._create_mock_rag()

        doc_scholarship = Document(
            page_content="2026학년도 2학기 국가장학금 신청 안내 본문입니다.",
            metadata={
                "title": "2026학년도 2학기 국가장학금 신청 안내",
                "date": "2026-08-12",
                "url": "https://www.hansung.ac.kr/bbs/scholarship",
                "source_type": "notice",
                "content_status": "text",
            }
        )
        doc_mentoring = Document(
            page_content="진로 탐색 및 취업 지원 멘토링 프로그램 안내입니다.",
            metadata={
                "title": "진로 취업 멘토링 프로그램 안내",
                "date": "2026-09-08",
                "url": "https://www.hansung.ac.kr/bbs/mentoring",
                "source_type": "notice",
                "content_status": "text",
            }
        )

        # 원시 점수 0.18 (임계값 0.25 미만)
        rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
            (doc_scholarship, 0.18),
            (doc_mentoring, 0.19),
        ]

        # 1. 아이폰 질문 -> '2026년' 연도나 일반 단어로 구제되면 안 됨
        res1 = rag.retrieve("2026년 아이폰 스펙 알려줘", top_k=3, min_threshold=0.25)
        assert len(res1) == 0, f"무관 아이폰 질문이 통과됨: {[d.metadata['title'] for d in res1]}"

        # 2. 파이썬 코드 질문 -> '탐색' 단어로 구제되면 안 됨
        res2 = rag.retrieve("파이썬으로 이진 탐색 트리 구현하는 코드 짜줘", top_k=3, min_threshold=0.25)
        assert len(res2) == 0, f"무관 파이썬 질문이 통과됨: {[d.metadata['title'] for d in res2]}"

    def test_guidance_and_faq_not_penalized_by_notice_freshness(self):
        """
        상시 안내(guidance) 및 학사 FAQ(faq)는 등록 연도가 오래되었거나 없더라도
        공지 전용 연도 불일치(-0.40) 또는 최신성 감점(-0.18)이 적용되지 않아야 한다.
        """
        rag = self._create_mock_rag()

        doc_faq = Document(
            page_content="평점평균 계산시 소숫점 3째자리 이하는 절사(버림) 처리합니다.",
            metadata={
                "title": "평점평균 계산시 반올림 인가요? (소숫점 3째자리부터 절사입니다)",
                "date": "",  # 날짜 없음
                "url": "https://www.hansung.ac.kr/bbs/faq",
                "source_type": "faq",
                "content_status": "text",
            }
        )
        # 원시 점수 0.35
        rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
            (doc_faq, 0.35),
        ]

        results = rag.retrieve("성적 평점평균 반올림 여부가 어떻게 돼?", top_k=3, min_threshold=0.25)
        assert len(results) == 1
        assert results[0].metadata["source_type"] == "faq"


class TestGeminiErrorHandling:
    """Gemini API 503 재시도, 429 한도, 인증 오류 분기 처리 검증 (완전 격리 mock)."""

    def _create_mock_rag(self):
        rag = CampusRAG.__new__(CampusRAG)
        rag.vectorstore = MagicMock()
        rag.provider = "gemini"
        rag.gemini_model_name = "gemini-3.8-flash"
        return rag

    def test_gemini_503_backoff_and_user_message(self, monkeypatch):
        """503 오류 발생 시 제한된 재시도 후 명확한 사용자 일시 장애 안내를 반환하는지 검증."""
        rag = self._create_mock_rag()


        attempts = 0
        def fake_invoke(inputs):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("503 Server Unavailable: The model is overloaded. Please try again later.")

        class FakeChain:
            def invoke(self, inputs):
                return fake_invoke(inputs)

        rag.llm = object()
        rag.chain = FakeChain()

        dummy_doc = Document(
            page_content="테스트 본문",
            metadata={"title": "테스트", "date": "2026-09-15", "url": "https://test.com", "source": "테스트"}
        )
        monkeypatch.setattr(rag, "retrieve", lambda q, top_k=None: [dummy_doc])

        result = rag.query("테스트 질문")
        assert attempts == 2  # 1회 시도 + 1회 503 재시도
        assert "503" in result["answer"] or "일시적인 서버 혼잡" in result["answer"]
        assert result.get("status") == "api_error"
        assert "503" in result.get("error", "")

    def test_gemini_429_quota_exhausted_immediate_stop(self, monkeypatch):
        """429 오류 발생 시 재시도 없이 즉시 한도 초과 안내를 반환하는지 검증."""
        rag = self._create_mock_rag()

        attempts = 0
        def fake_invoke(inputs):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("429 ResourceExhausted: Quota exceeded for quota metric.")

        class FakeChain:
            def invoke(self, inputs):
                return fake_invoke(inputs)

        rag.llm = object()
        rag.chain = FakeChain()

        dummy_doc = Document(
            page_content="테스트 본문",
            metadata={"title": "테스트", "date": "2026-09-15", "url": "https://test.com", "source": "테스트"}
        )
        monkeypatch.setattr(rag, "retrieve", lambda q, top_k=None: [dummy_doc])

        result = rag.query("테스트 질문")
        assert attempts == 1  # 429는 재시도 없이 즉시 중단
        assert "429" in result["answer"] or "요청 한도" in result["answer"]
        assert result.get("status") == "api_error"
        assert "429" in result.get("error", "")

    def test_gemini_auth_error_immediate_stop(self, monkeypatch):
        """인증 오류(401/403) 발생 시 즉시 중단하고 인증 오류 안내를 반환하는지 검증."""
        rag = self._create_mock_rag()

        attempts = 0
        def fake_invoke(inputs):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("403 PermissionDenied: API_KEY_INVALID")

        class FakeChain:
            def invoke(self, inputs):
                return fake_invoke(inputs)

        rag.llm = object()
        rag.chain = FakeChain()

        dummy_doc = Document(
            page_content="테스트 본문",
            metadata={"title": "테스트", "date": "2026-09-15", "url": "https://test.com", "source": "테스트"}
        )
        monkeypatch.setattr(rag, "retrieve", lambda q, top_k=None: [dummy_doc])

        result = rag.query("테스트 질문")
        assert attempts == 1
        assert "인증" in result["answer"]
        assert result.get("status") == "api_error"
