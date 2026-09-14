"""
CampusRAG 데이터 수집-적재-검색 격리 파이프라인 무결성 회귀 테스트.

검증 항목:
1. 새 공지가 수집/적재되면 실제 Chroma 검색 결과에 즉시 반영되는가?
2. 같은 URL의 본문이나 첨부파일 텍스트가 변경되면 답변 근거도 갱신되는가?
3. 동일 데이터로 재적재를 반복 실행해도 중복 문서·청크가 늘어나지 않는가? (Idempotent)
4. 본문이 짧아져 청크 수가 감소했을 때 이전의 불필요 청크(stale chunks)가 남지 않고 삭제되는가?
5. 특정 공지의 OCR/다운로드 실패가 다른 정상 공지의 수집 및 적재를 중단시키지 않는가?
"""

import json
from pathlib import Path
import pytest

from core.embedder import get_chroma_vectorstore, ingest_to_chroma, split_notice_into_chunks
from core.extractor.pipeline import NoticeEnricher
from core.rag import CampusRAG


class TestPipelineIsolation:
    """임시 DB와 격리 데이터를 사용한 수집-적재-검색 무결성 검증."""

    def test_new_notice_appears_in_search(self, tmp_path):
        """1. 새 공지가 추가되면 실제 검색 결과에 정상 노출되는지 검증."""
        db_dir = str(tmp_path / "temp_chroma")
        col_name = "test_pipeline_col"

        initial_notices = [
            {
                "id": "notice_101",
                "title": "2026학년도 2학기 폐강 강좌 및 수강신청 정정 안내",
                "content": "폐강 강좌 공고는 9월 2일이며 수강신청 정정 기간은 9월 3일부터 9월 5일까지입니다.",
                "source": "학교본부 (학사운영팀)",
                "category": "학사",
                "date": "2026-09-01",
                "url": "https://www.hansung.ac.kr/bbs/hansung/2127/101/artclView.do",
                "content_status": "text",
            }
        ]

        # 1차 적재
        ingest_to_chroma(initial_notices, persist_directory=db_dir, collection_name=col_name)

        # 검색 검증
        store = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        results = store.similarity_search("폐강 강좌 정정 기간", k=1)
        assert len(results) == 1
        assert "폐강 강좌" in results[0].metadata["title"]

        # 새 공지 수집 발생
        new_notice = {
            "id": "notice_102",
            "title": "2026-2학기 런던 글로벌 창업교육 프로그램 참가자 모집",
            "content": "런던 글로벌 창업연수 선발 인원은 15명이며 접수 마감은 9월 25일까지입니다.",
            "source": "학교본부 (글로벌창업교육센터)",
            "category": "공지",
            "date": "2026-09-10",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/102/artclView.do",
            "content_status": "text",
        }

        # 증분 적재 (replace=False)
        ingest_to_chroma([new_notice], persist_directory=db_dir, collection_name=col_name)

        # 새 공지가 검색되는지 검증
        store_updated = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        res_new = store_updated.similarity_search("런던 글로벌 창업연수", k=1)
        assert len(res_new) == 1
        assert "런던 글로벌" in res_new[0].metadata["title"]
        assert "15명" in res_new[0].page_content

    def test_updated_notice_content_refreshes_retrieval(self, tmp_path):
        """2. 동일 URL 공지의 내용(일정 변경 등)이 바뀌면 검색 결과 내용도 갱신되는지 검증."""
        db_dir = str(tmp_path / "temp_chroma")
        col_name = "test_pipeline_col"

        v1_notice = {
            "id": "notice_201",
            "title": "TOPCIT 소프트웨어 역량검정 시험 안내",
            "content": "접수 마감은 9월 2일 18시까지입니다.",
            "source": "학교본부 (SW중심대학사업단)",
            "category": "공지",
            "date": "2026-08-20",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/201/artclView.do",
            "content_status": "text",
        }
        ingest_to_chroma([v1_notice], persist_directory=db_dir, collection_name=col_name)

        # 내용 변경 (마감일 연장)
        v2_notice = {
            "id": "notice_201",
            "title": "★기간연장★ TOPCIT 소프트웨어 역량검정 시험 안내",
            "content": "접수 마감이 9월 9일 18시까지로 연장되었습니다.",
            "source": "학교본부 (SW중심대학사업단)",
            "category": "공지",
            "date": "2026-09-02",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/201/artclView.do",
            "content_status": "text",
        }
        ingest_to_chroma([v2_notice], persist_directory=db_dir, collection_name=col_name)

        store = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        results = store.similarity_search("TOPCIT 접수 마감일", k=2)
        # 이전 9월 2일 텍스트가 아닌 9월 9일 연장 텍스트가 반영되어야 함
        assert len(results) >= 1
        top_doc = results[0]
        assert "연장" in top_doc.metadata["title"] or "9월 9일" in top_doc.page_content

    def test_idempotent_reingest_does_not_multiply_chunks(self, tmp_path):
        """3. 재실행해도 동일 공지의 청크가 중복 증식되지 않는지 검증."""
        db_dir = str(tmp_path / "temp_chroma")
        col_name = "test_pipeline_col"

        long_notice = {
            "id": "notice_301",
            "title": "2026학년도 2학기 학부 재학생 등록금 납부 및 분할납부 상세 안내",
            "content": (
                "1. 등록금 납부 기간: 2026. 8. 24.(월) ~ 8. 28.(금) 16:00\n"
                "2. 분할납부 신청 기간: 2026. 8. 10.(월) ~ 8. 14.(금) 17:00\n"
                "3. 대상자: 학부 재학생 및 복학생 (학기초과자 제외)\n"
                "4. 납부 은행: 국민은행, 신한은행 가상계좌 납부\n"
                "5. 유의사항: 등록금 미납 시 학칙에 의거 제적 처리될 수 있습니다.\n"
            ) * 5,  # 긴 본문 -> 다중 청크 분할 유도
            "source": "학교본부 (재무회계팀)",
            "category": "학사",
            "date": "2026-07-30",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/301/artclView.do",
            "content_status": "text",
        }

        # 1차 실행
        ingest_to_chroma([long_notice], persist_directory=db_dir, collection_name=col_name)
        store1 = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        count_1 = store1._collection.count()
        assert count_1 >= 2, "다중 청크로 분할되어야 합니다."

        # 2차 실행 (동일 데이터 재적재)
        ingest_to_chroma([long_notice], persist_directory=db_dir, collection_name=col_name)
        store2 = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        count_2 = store2._collection.count()

        # 청크 수가 2배로 증가하지 않고 정확히 동일해야 함
        assert count_2 == count_1

    def test_shortened_body_removes_stale_chunks(self, tmp_path):
        """4. 공지 본문이 짧아졌을 때 이전의 불필요 청크(stale chunks)가 남지 않는지 검증."""
        db_dir = str(tmp_path / "temp_chroma")
        col_name = "test_pipeline_col"

        # 처음엔 긴 본문 (다중 청크)
        long_notice = {
            "id": "notice_401",
            "title": "해외봉사활동 51기 WFK 청년봉사단 단원 모집 요강",
            "content": "가나다라마바사 아자차카타파하 " * 150,  # 여러 청크
            "source": "학교본부 (학생복지팀)",
            "category": "공지",
            "date": "2026-09-07",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/401/artclView.do",
            "content_status": "text",
        }
        ingest_to_chroma([long_notice], persist_directory=db_dir, collection_name=col_name)
        store1 = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        count_before = store1._collection.count()
        assert count_before >= 3

        # 본문이 요약형으로 대폭 짧아짐 (단일 청크)
        short_notice = {
            "id": "notice_401",
            "title": "해외봉사활동 51기 WFK 청년봉사단 단원 모집 요강",
            "content": "마감되었습니다.",
            "source": "학교본부 (학생복지팀)",
            "category": "공지",
            "date": "2026-09-07",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/401/artclView.do",
            "content_status": "text",
        }
        ingest_to_chroma([short_notice], persist_directory=db_dir, collection_name=col_name)
        store2 = get_chroma_vectorstore(persist_directory=db_dir, collection_name=col_name)
        count_after = store2._collection.count()

        # 이전의 잉여 청크들이 삭제되고 1개 청크만 남아야 함
        assert count_after == 1
        remaining_doc = store2.get()
        assert remaining_doc["metadatas"][0]["id"] in ("notice_401", "notice_401_c0")
        assert "마감되었습니다" in remaining_doc["documents"][0]

    def test_extraction_failure_does_not_corrupt_pipeline(self, tmp_path):
        """5. 특정 공지의 다운로드/추출 실패가 전체 파이프라인과 타 정상 공지를 중단시키지 않는지 검증."""
        enricher = NoticeEnricher()

        # 손상된 파일이나 비표준 HTML이 들어있는 공지
        broken_notice = {
            "id": "notice_501",
            "title": "서버 오류 공지",
            "content": "",
            "source": "학교본부",
            "category": "공지",
            "date": "2026-09-01",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/501/artclView.do",
            "images": [{"url": "http://127.0.0.1/malicious.jpg"}],  # SSRF 차단 대상
            "attachments": [{"url": "https://invalid-host-that-does-not-exist.hansung.ac.kr/file.pdf"}],
        }

        # 예외를 던지지 않고 graceful하게 fallback 처리되어야 함
        enriched = enricher.enrich_notice(broken_notice, detail_html="<html><body>내용 없음</body></html>")
        assert enriched["content_status"] in ("title_only", "failed", "partial")
        # 제목은 그대로 보존되어야 함
        assert enriched["title"] == "서버 오류 공지"


class TestVerifyOpsPipelineSafety:
    """verify_ops_pipeline의 디렉터리 삭제 방어 및 격리 무결성 검증."""

    def test_verify_ops_refuses_existing_dir_without_deleting(self, tmp_path):
        """사용자가 넘긴 기존 디렉터리를 감지하면 삭제하지 않고 즉시 예외를 발생시키는지 검증."""
        from scripts.verify_ops_pipeline import verify_ops_pipeline

        existing_dir = tmp_path / "user_designated_existing_dir"
        existing_dir.mkdir()
        sentinel_file = existing_dir / "precious_data.txt"
        sentinel_file.write_text("절대 삭제되면 안 되는 데이터", encoding="utf-8")

        # 기존 디렉터리 경로를 넘기면 ValueError 발생
        with pytest.raises(ValueError, match="기존에 존재하는 경로"):
            verify_ops_pipeline(temp_db_path=str(existing_dir))

        # 기존 디렉터리와 내부 파일이 전혀 삭제되지 않고 보존되었는지 검증
        assert existing_dir.exists(), "기존 디렉터리가 삭제되었습니다!"
        assert sentinel_file.exists(), "기존 디렉터리 내부 파일이 삭제되었습니다!"
        assert sentinel_file.read_text(encoding="utf-8") == "절대 삭제되면 안 되는 데이터"

    def test_verify_ops_refuses_symlink_without_deleting_target(self, tmp_path):
        """심볼릭 링크 경로가 지정된 경우 링크 및 링크 대상이 삭제되지 않고 즉시 거부되는지 검증."""
        from scripts.verify_ops_pipeline import verify_ops_pipeline

        target_dir = tmp_path / "symlink_real_target"
        target_dir.mkdir()
        target_file = target_dir / "target_data.txt"
        target_file.write_text("심볼릭 링크 대상 원본", encoding="utf-8")

        link_dir = tmp_path / "symlink_pointer"
        link_dir.symlink_to(target_dir, target_is_directory=True)

        with pytest.raises(ValueError, match="심볼릭 링크"):
            verify_ops_pipeline(temp_db_path=str(link_dir))

        # 링크 및 실제 타깃 디렉터리가 전혀 훼손되지 않았는지 검증
        assert link_dir.is_symlink(), "심볼릭 링크가 훼손되었습니다!"
        assert target_dir.exists(), "심볼릭 링크 대상 원본이 삭제되었습니다!"
        assert target_file.exists(), "심볼릭 링크 대상 내부 파일이 삭제되었습니다!"

    def test_verify_ops_refuses_prod_db_path(self):
        """운영 DB(config.CHROMA_PERSIST_DIR) 경로를 임시 DB로 지정하려는 경우 즉시 거부되는지 검증."""
        from scripts.verify_ops_pipeline import verify_ops_pipeline
        import config

        prod_db = config.CHROMA_PERSIST_DIR
        with pytest.raises(ValueError, match="운영 DB 경로"):
            verify_ops_pipeline(temp_db_path=prod_db)

        # 운영 DB 디렉터리가 그대로 안전하게 유지되는지 검증
        assert Path(prod_db).exists(), "운영 DB 경로가 손상되었습니다!"

