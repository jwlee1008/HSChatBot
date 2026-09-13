"""
OCR 및 첨부파일 보강 문서의 Chroma DB 적재, 중복 방지 및 검색 가능성 통합 테스트.

운영 DB를 일절 건드리지 않고 tmp_path 격리 환경에서 실행한다.
"""

import json
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from core import embedder
from core.rag import CampusRAG


class MockKoreanEmbeddings(Embeddings):
    """테스트용 초경량 결정론적 임베딩."""

    def embed_documents(self, texts):
        res = []
        for t in texts:
            # '국가장학' 또는 '신청' 키워드가 있으면 특정 벡터 활성화
            v1 = 1.0 if ("장학" in t or "신청" in t or "봉사" in t) else 0.1
            v2 = 0.5
            res.append([v1, v2])
        return res

    def embed_query(self, text):
        v1 = 1.0 if ("장학" in text or "신청" in text or "봉사" in text) else 0.1
        return [v1, 0.5]


def test_chroma_ingest_enriched_notice_and_upsert_dedup(tmp_path, monkeypatch):
    """보강된 문서 적재 시 원문 링크 유지, 반복 적재 시 중복 없음 검증."""
    monkeypatch.setattr(embedder, "get_embedding_model", lambda: MockKoreanEmbeddings())

    # 임시 JSON 파일 생성 (보강된 공지 형태)
    enriched_data = [
        {
            "id": "hansung-notice-223971",
            "title": "2026년 2학기 국가장학금 2차 신청 안내",
            "content": (
                "2026년 2학기 국가장학금 2차 신청 안내\n\n"
                "[이미지 OCR 추출 #1: (포스터)_2026_2학기_2차_국가장학금_신청.jpg]\n"
                "신청기간: 2026.08.12.(수) 09시 ~ 09.09.(수) 18시\n"
                "서류제출 및 가구원 동의: 2026.08.12 ~ 09.16\n"
                "대상: 재학생, 신입생, 편입생, 복학생 등 모든 대학생"
            ),
            "source": "학생복지팀",
            "category": "장학",
            "date": "2026-08-12",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do",
            "content_status": "ocr",
            "has_ocr": True,
            "has_attachment": False,
            "extraction_summary": "images: 1/1 ok",
            "images": [
                {
                    "url": "https://www.hansung.ac.kr/CrossEditor/binary/images/000402/poster.jpg",
                    "status": "success",
                    "method": "ocr_tesseract",
                }
            ],
            "attachments": [],
        }
    ]

    json_path = tmp_path / "enriched_test.json"
    json_path.write_text(json.dumps(enriched_data, ensure_ascii=False), encoding="utf-8")

    # 1. Document 로드 검증
    docs = embedder.load_notices_from_json(str(json_path))
    assert len(docs) == 1
    doc = docs[0]
    assert doc.metadata["has_ocr"] is True
    assert doc.metadata["content_status"] == "ocr"
    assert doc.metadata["url"] == "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do"
    assert "신청기간: 2026.08.12" in doc.page_content

    # 2. Chroma DB 최초 적재
    persist_dir = str(tmp_path / "test_chroma")
    vectorstore = embedder.ingest_to_chroma(docs, persist_directory=persist_dir, collection_name="test_col")
    assert vectorstore._collection.count() == 1

    # 3. 동일 URL 문서 반복 적재 시 중복 없이 단 1건으로 유지되는지 검증 (upsert)
    vectorstore2 = embedder.ingest_to_chroma(docs, persist_directory=persist_dir, collection_name="test_col")
    assert vectorstore2._collection.count() == 1

    # 4. 추출 결과 검색 가능 여부 검증
    results = vectorstore2.similarity_search("국가장학금 신청기간이 언제야?", k=1)
    assert len(results) == 1
    found_doc = results[0]
    assert found_doc.metadata["title"] == "2026년 2학기 국가장학금 2차 신청 안내"
    assert found_doc.metadata["url"] == "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do"
    assert "2026.08.12" in found_doc.page_content
