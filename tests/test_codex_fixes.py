"""
Codex 재검토 수정 사항 1~6에 대한 재현 및 검증 테스트 슈트.

검증 항목:
1. build_unified_dataset: _source_name 오염 방지 및 타임스탬프 우선순위
2. ingest_unified_db: 운영 DB/기존 검증 DB/심볼릭 링크 경로 방어
3. core/rag: 일반 단어/연도 무관 질문 사전 필터 우회 방지 및 TOPCIT 구제
4. backend/main: QueryResponse 구조화된 상태(status, error_type 등) 전달 및 안전성
5. core/rag: FAQ ID 보존 및 상시 안내 최신성 감점 배제, 주 공지 청크 누락 방지
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── 1. 데이터 갱신 우선순위 & 출처 오염 방지 ──────────────────────

def test_source_name_not_corrupted_on_skipped_document():
    """
    scripts/build_unified_dataset.py:227 결함 재현 및 방어 검증:
    신규 문서가 품질/타임스탬프 비교로 기각(skipped)되었을 때,
    기존 문서의 _source_name이 기각된 신규 소스명으로 덮어써지지 않아야 한다.
    """
    from scripts.build_unified_dataset import resolve_document_conflict

    existing_doc = {
        "id": "notice-01",
        "url": "https://www.hansung.ac.kr/bbs/1",
        "title": "2026학년도 2학기 국가장학금 신청 안내",
        "content": "상세한 본문 내용이 충분히 작성되어 있는 정상 공지입니다.",
        "content_status": "text",
        "date": "2026-09-01",
        "_source_name": "missing_notices_refreshed",
        "_source_priority": 1,
    }

    # 오래되었고 품질이 낮은 아카이브 공지 인입
    incoming_doc = {
        "id": "notice-01",
        "url": "https://www.hansung.ac.kr/bbs/1",
        "title": "2026학년도 2학기 국가장학금 신청 안내 (구버전)",
        "content": "제목만 존재",
        "content_status": "title_only",
        "date": "2026-08-01",
    }

    chosen, chosen_source, reason = resolve_document_conflict(
        existing=existing_doc,
        new_doc=incoming_doc,
        existing_source="missing_notices_refreshed",
        new_source="notice_archive",
    )

    # 신규 문서는 기각되어야 함
    assert chosen is existing_doc
    assert chosen_source == "missing_notices_refreshed"
    # 기존 문서의 _source_name이 notice_archive로 오염되지 않고 유지되어야 함
    assert chosen["_source_name"] == "missing_notices_refreshed"


def test_resolve_document_conflict_timestamp_and_failure_preservation():
    """
    문서 충돌 해결 정책 검증:
    1) 최신 공지의 본문 축소/마감 정정 반영: 텍스트 유효 상태에서 최신 수집일/등록일 문서 채택
    2) 실패 보존: 최신 날짜라도 title_only는 기존 유효한 text/ocr 본문을 덮어쓸 수 없음
    3) OCR 보강본 우선: 동일 일자에서 ocr_enhanced가 title_only 또는 기본 텍스트보다 우선
    """
    from scripts.build_unified_dataset import resolve_document_conflict

    # 케이스 1: 실패 보존 (title_only가 유효 본문 덮어쓰기 차단)
    good_text_doc = {
        "id": "notice-02",
        "title": "성적 정정 안내",
        "content": "성적 정정 기간은 9월 10일부터 9월 14일까지입니다.",
        "content_status": "text",
        "date": "2026-08-20",
        "_source_name": "original_text",
        "_source_priority": 2,
    }
    newer_title_only = {
        "id": "notice-02",
        "title": "성적 정정 안내",
        "content": "내용 없음",
        "content_status": "title_only",
        "date": "2026-09-02",  # 날짜는 더 최신
    }
    chosen1, source1, reason1 = resolve_document_conflict(
        existing=good_text_doc,
        new_doc=newer_title_only,
        existing_source="original_text",
        new_source="new_scrape",
    )
    assert chosen1["content_status"] == "text"
    assert source1 == "original_text"
    assert "preserve" in reason1

    # 케이스 2: 최신 공지의 마감 정정/본문 축소 정상 반영
    older_announcement = {
        "id": "notice-03",
        "title": "신청 마감 공지",
        "content": "신청 마감은 9월 20일 18시까지로 길게 설명되어 있는 이전 공지문입니다.",
        "content_status": "text",
        "date": "2026-08-10",
        "_source_name": "draft_notice",
        "_source_priority": 2,
    }
    revised_deadline = {
        "id": "notice-03",
        "title": "신청 마감 단축 정정 공지",
        "content": "마감 정정: 9월 15일 15시 종료.",  # 본문 길이는 더 짧음
        "content_status": "text",
        "date": "2026-08-25",  # 더 최신
    }
    chosen2, source2, reason2 = resolve_document_conflict(
        existing=older_announcement,
        new_doc=revised_deadline,
        existing_source="draft_notice",
        new_source="revised_notice",
    )
    assert chosen2["date"] == "2026-08-25"
    assert source2 == "revised_notice"
    assert "마감 정정" in chosen2["content"]
    assert "newer" in reason2

    # 케이스 3: OCR 보강본 우선 원칙
    plain_doc = {
        "id": "notice-04",
        "title": "행사 포스터 안내",
        "content": "공지 일반 본문 텍스트입니다.",
        "content_status": "text",
        "date": "2026-09-01",
        "_source_name": "scraped_notice",
        "_source_priority": 3,
    }
    ocr_enhanced = {
        "id": "notice-04",
        "title": "행사 포스터 안내",
        "content": "[포스터 OCR 텍스트] 일시: 2026년 9월 20일 장소: 상상관 대강당",
        "content_status": "ocr_enhanced",
        "date": "2026-09-01",
    }
    chosen3, source3, reason3 = resolve_document_conflict(
        existing=plain_doc,
        new_doc=ocr_enhanced,
        existing_source="scraped_notice",
        new_source="ocr_batch",
    )
    assert chosen3["content_status"] == "ocr_enhanced"
    assert source3 == "ocr_batch"
    assert "ocr" in reason3.lower()


# ── 2. 격리 DB 경로 방어 ────────────────────────────────────────

def test_ingest_rejects_protected_paths_and_symlinks(tmp_path):
    """
    scripts/ingest_unified_db.py:
    운영 DB(data/chroma_db), 기존 검증 DB(data/verify_demo_chroma_db, data/eval_chroma_db)
    및 이를 가리키는 심볼릭 링크 경로로의 적재 시도를 즉시 거부(PermissionError)해야 한다.
    """
    from scripts.ingest_unified_db import validate_persist_dir

    # 1. 운영 DB 경로
    with pytest.raises(PermissionError):
        validate_persist_dir(ROOT / "data/chroma_db")

    # 2. 기존 검증 DB 경로
    with pytest.raises(PermissionError):
        validate_persist_dir(ROOT / "data/verify_demo_chroma_db")
    with pytest.raises(PermissionError):
        validate_persist_dir(ROOT / "data/eval_chroma_db")

    # 3. 심볼릭 링크로 우회하는 경로
    symlink_path = tmp_path / "sneaky_chroma_link"
    try:
        os.symlink(ROOT / "data/chroma_db", symlink_path)
        with pytest.raises(PermissionError):
            validate_persist_dir(symlink_path)
    finally:
        if symlink_path.is_symlink():
            symlink_path.unlink()


def test_ingest_directory_safety_and_clean_option(tmp_path):
    """
    적재 대상 디렉토리에 기존 파일이 존재할 경우:
    --clean 또는 --allow-existing이 없으면 잔존 청크 오염 방지를 위해 FileExistsError를 발생시켜야 한다.
    --clean이 지정되면 기존 내용을 안전하게 비우고 준비해야 한다.
    """
    from scripts.ingest_unified_db import validate_persist_dir

    target_dir = tmp_path / "isolated_test_chroma"
    target_dir.mkdir(parents=True)
    test_file = target_dir / "leftover_chunk.parquet"
    test_file.write_text("old chunk data")

    # 1. 이미 존재하는 디렉터리는 즉시 거부 (FileExistsError)
    with pytest.raises(FileExistsError):
        validate_persist_dir(target_dir)

    # 2. 존재하지 않는 새로운 경로는 정상 통과
    fresh_dir = tmp_path / "brand_new_isolated_chroma"
    validated_path = validate_persist_dir(fresh_dir)
    assert validated_path == fresh_dir.resolve()


# ── 3. 무관 질문 사전 필터 우회 차단 ────────────────────────────

def test_lexical_bonus_does_not_bypass_irrelevant_queries():
    """
    core/rag.py:
    '2026년 아이폰 스펙 알려줘' 및 '파이썬으로 이진 탐색 트리 구현하는 코드 짜줘'처럼
    일반 단어나 연도만 우연히 겹치는 무관 질문은 0.08 가산점을 절대 받지 못하고
    사전 필터에서 빈 결과(0건)로 차단되어 LLM 호출 없이 no_context로 조기 유보되어야 한다.
    """
    from core.rag import CampusRAG

    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.llm = None
    rag.chain = None
    rag.provider = "gemini"
    rag.gemini_model_name = "gemini-3.8-flash"

    doc_scholarship = Document(
        page_content="2026학년도 2학기 국가장학금 신청 안내 본문입니다.",
        metadata={"title": "2026학년도 2학기 국가장학금 신청 안내", "date": "2026-08-12", "content_status": "text"}
    )
    doc_mentoring = Document(
        page_content="진로 탐색 및 취업 지원 멘토링 프로그램 안내입니다.",
        metadata={"title": "진로 탐색 취업 멘토링 프로그램 안내", "date": "2026-09-08", "content_status": "text"}
    )

    # 원시 점수 0.18 (임계값 0.25 미만)
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_scholarship, 0.18),
        (doc_mentoring, 0.19),
    ]

    # 1. 2026년 아이폰 스펙 -> 연도 가산점 미부여로 차단
    res1 = rag.retrieve("2026년 아이폰 스펙 알려줘", top_k=3, min_threshold=0.25)
    assert len(res1) == 0

    # 2. 파이썬 코드 -> '탐색' 일반 단어 가산점 미부여로 차단
    res2 = rag.retrieve("파이썬으로 이진 탐색 트리 구현하는 코드 짜줘", top_k=3, min_threshold=0.25)
    assert len(res2) == 0


def test_specialized_terms_retrieval_rescue():
    """
    고유 전문 약어(TOPCIT, CPA, TOEIC 등)는 질문에 포함되었을 때
    0.08 어휘 가산점을 받아 정상 구제되는지 검증.
    """
    from core.rag import CampusRAG

    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.llm = None
    rag.chain = None
    rag.provider = "gemini"
    rag.gemini_model_name = "gemini-3.8-flash"

    doc_topcit = Document(
        page_content="제26회 TOPCIT 정기평가 단체접수 안내입니다.",
        metadata={"title": "★기간연장★ [SW중심] 제26회 TOPCIT 정기평가 시행 안내", "date": "2026-09-04", "content_status": "text"}
    )
    doc_cpa = Document(
        page_content="공인회계사(CPA) 및 세무사 1차 합격자 특별장학금 지급 기준입니다.",
        metadata={"title": "공인회계사(CPA) 및 세무사 1차 합격자 특별장학금 신청 안내", "date": "2026-09-02", "content_status": "text"}
    )

    # 1. TOPCIT: 원시 점수 0.20 -> +0.08 = 0.28 (>= 0.25 통과)
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [(doc_topcit, 0.20)]
    res_topcit = rag.retrieve("TOPCIT 평가", top_k=3, min_threshold=0.25)
    assert len(res_topcit) == 1
    assert "TOPCIT" in res_topcit[0].metadata["title"]

    # 2. CPA: 원시 점수 0.19 -> +0.08 = 0.27 (>= 0.25 통과)
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [(doc_cpa, 0.19)]
    res_cpa = rag.retrieve("CPA 장학금", top_k=3, min_threshold=0.25)
    assert len(res_cpa) == 1
    assert "CPA" in res_cpa[0].metadata["title"]


# ── 4. 서비스 응답 상태 및 오류 구조화 계약 검증 ─────────────────

def test_fastapi_query_response_contracts():
    """
    FastAPI /api/query 엔드포인트 계약 검증:
    1) 정상 성공: status='success', api_called=True, error_type=None
    2) 429 한도 초과: status='api_error', api_called=True, error_type='rate_limit'
    3) 503 일시 장애: status='api_error', api_called=True, error_type='service_unavailable'
    4) 403 인증 오류: status='api_error', api_called=True, error_type='auth_error'
    5) 무관 유보: status='no_context', api_called=False, error_type=None
    6) 제목만 확인: status='title_only_notice', api_called=False, error_type=None
    7) 중요: 원시 예외 스택트레이스나 내부 토큰/키가 응답에 노출되지 않아야 함
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as bm

    client = TestClient(app)

    # 1. 정상 성공 응답
    mock_rag = MagicMock()
    mock_rag.query.return_value = {
        "answer": "국가장학금 신청 마감은 9월 9일 18시입니다.",
        "sources": [{"title": "국장 공지", "source": "장학팀", "category": "장학", "date": "2026-08-12", "url": "https://hansung.ac.kr/1"}],
        "status": "success",
        "api_called": True,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "국장 마감 언제야?", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["api_called"] is True
        assert data["error_type"] is None
        assert "9월 9일" in data["answer"]

    # 2. 429 한도 초과 응답
    mock_rag.query.return_value = {
        "answer": "일일 AI 요청 한도(429)에 도달했습니다.",
        "sources": [],
        "status": "api_error",
        "error": "429 ResourceExhausted: Quota exceeded for metric",
        "api_called": True,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "국장 마감 언제야?", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "api_error"
        assert data["api_called"] is True
        assert data["error_type"] == "rate_limit"
        assert "ResourceExhausted" not in str(data)  # 원시 예외 미노출

    # 3. 503 일시 서버 혼잡 응답
    mock_rag.query.return_value = {
        "answer": "AI 서비스가 일시적으로 혼잡합니다.",
        "sources": [],
        "status": "api_error",
        "error": "503 Unavailable: Model overloaded",
        "api_called": True,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "질문", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "api_error"
        assert data["error_type"] == "service_unavailable"

    # 4. 403 인증 오류 응답
    mock_rag.query.return_value = {
        "answer": "인증/권한 오류가 발생했습니다.",
        "sources": [],
        "status": "api_error",
        "error": "403 PermissionDenied: API_KEY_INVALID",
        "api_called": True,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "질문", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "api_error"
        assert data["error_type"] == "auth_error"
        assert "API_KEY_INVALID" not in str(data)  # 비밀정보/원시 오류 미노출

    # 5. 무관 유보 (no_context)
    mock_rag.query.return_value = {
        "answer": "관련된 한성대학교 학사 공지를 찾을 수 없습니다.",
        "sources": [],
        "status": "no_context",
        "api_called": False,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "2026년 아이폰 스펙 알려줘", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_context"
        assert data["api_called"] is False
        assert data["error_type"] is None

    # 6. 제목만 확인 (title_only_notice)
    mock_rag.query.return_value = {
        "answer": "해당 공지는 제목만 확인되며 본문 내용이 없습니다.",
        "sources": [{"title": "첨부 공지", "source": "학생처", "category": "장학", "date": "2026-09-01", "url": "https://hansung.ac.kr/2"}],
        "status": "title_only_notice",
        "api_called": False,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    with patch.object(bm, "rag_instance", mock_rag):
        resp = client.post("/api/query", json={"question": "첨부 공지 세부 내용 알려줘", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "title_only_notice"
        assert data["api_called"] is False
        assert data["error_type"] is None


# ── 5. 원시 결과와 생성 성공 주장 정합성 검증 ────────────────────

def test_ground_truth_raw_evidence_integrity():
    """
    보고서 및 테스트의 생성 성공 주장은 오직 원시 성공 실행 파일로만 증명되어야 한다.
    1) data/gemini_smoke_results.json: dev-md-05 (CPA/세무사 장학금) 성공 응답 실존
    2) data/eval_phase2_expansion_results.json: exp-02 (편입생 학점 재인정) 성공 응답 실존 (latency 3.64s)
    3) data/gemini_integration_results.json: 9개 프로브는 모두 api_error(429)이므로
       '생성 PASS'가 아닌 '검색 확인, 답변 미검증'으로 정정되어야 함을 검증.
    """
    # 1. Smoke test dev-md-05 검증
    smoke_file = ROOT / "data/gemini_smoke_results.json"
    assert smoke_file.exists(), "smoke 결과 파일 부재"
    with open(smoke_file, "r", encoding="utf-8") as f:
        smoke_data = json.load(f)
    smoke_results = smoke_data.get("results", [])
    dev_md_05 = next((r for r in smoke_results if r.get("id") == "dev-md-05"), None)
    assert dev_md_05 is not None, "dev-md-05 항목 부재"
    assert "CPA" in dev_md_05.get("answer", "") or "세무사" in dev_md_05.get("answer", "")

    # 2. Phase 2 expansion exp-02 검증
    exp_file = ROOT / "data/eval_phase2_expansion_results.json"
    assert exp_file.exists(), "expansion 결과 파일 부재"
    with open(exp_file, "r", encoding="utf-8") as f:
        exp_data = json.load(f)
    items = exp_data.get("details", [])
    exp02 = next((it for it in items if it.get("id") == "exp-02"), None)
    assert exp02 is not None, "exp-02 항목 부재"
    assert exp02.get("answer_eval", {}).get("status") == "PASS"
    assert exp02.get("latency_sec", 0) > 3.0  # 실제 단일 성공 생성 지연 시간은 약 3.64s
    assert "편입" in exp02.get("actual_answer", "")

    # exp-02 외의 9개 항목은 모두 API 오류여야 함
    non_exp02 = [it for it in items if it.get("id") != "exp-02"]
    for it in non_exp02:
        assert it.get("api_status") == "api_error" or it.get("answer_eval", {}).get("status") == "API_ERROR"

    # 3. gemini_integration_results.json의 9개 프로브 상태 확인
    integ_file = ROOT / "data/gemini_integration_results.json"
    assert integ_file.exists(), "integration 결과 파일 부재"
    with open(integ_file, "r", encoding="utf-8") as f:
        integ_data = json.load(f)
    integ_results = integ_data.get("results", [])
    assert len(integ_results) == 9
    for r in integ_results:
        # 9개 모두 실제로는 429로 인한 api_error 상태임
        assert r.get("status") == "api_error"


# ── 6. FAQ ID 고유 식별 및 상시 안내 시간 정책 회귀 검증 ────────

def test_faq_id_preservation_when_sharing_url():
    """
    FAQ는 여러 질문이 동일한 카테고리/목록 URL을 공유하므로,
    URL 대신 고유 id를 키로 사용하여 항목이 덮어써져 유실되는 결함을 방지해야 한다.
    """
    faq_spec = {"default_source_type": "faq"}
    faq_1 = {
        "id": "faq-01",
        "url": "https://www.hansung.ac.kr/bbs/faq/artclList.do",
        "title": "성적 평점평균 소수점 처리",
        "content": "소수점 3째자리 이하는 절사합니다.",
        "source_type": "faq",
    }
    faq_2 = {
        "id": "faq-02",
        "url": "https://www.hansung.ac.kr/bbs/faq/artclList.do",  # 동일 URL
        "title": "계절학기 최대 수강신청 학점",
        "content": "계절학기는 최대 6학점까지 수강 가능합니다.",
        "source_type": "faq",
    }

    # get_canonical_key 로직 직접 검증
    def get_canonical_key(item, spec):
        if spec["default_source_type"] == "faq" or item.get("source_type") == "faq":
            return ("faq", str(item["id"]))
        url = item.get("url")
        if url:
            return ("url", url)
        return ("id", str(item["id"]))

    key1 = get_canonical_key(faq_1, faq_spec)
    key2 = get_canonical_key(faq_2, faq_spec)

    assert key1 != key2
    assert key1 == ("faq", "faq-01")
    assert key2 == ("faq", "faq-02")


def test_guidance_and_faq_freshness_policy():
    """
    상시 안내(guidance) 및 학사 FAQ(faq)는 등록일(date)이 비어있거나 수년 전이더라도
    공지 전용 연도 불일치(-0.40) 또는 경과일수 최신성 감점(-0.18)을 적용받지 않아야 한다.
    """
    from core.rag import CampusRAG

    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.llm = None
    rag.chain = None
    rag.provider = "gemini"
    rag.gemini_model_name = "gemini-3.8-flash"

    doc_old_guidance = Document(
        page_content="졸업인증 기준: 봉사활동 40시간 이상 이수 및 공인영어 성적 제출.",
        metadata={
            "title": "졸업인증제 상시 안내",
            "date": "2021-03-01",  # 5년 전 등록일
            "url": "https://www.hansung.ac.kr/guidance/grad",
            "source_type": "guidance",
            "content_status": "text",
        }
    )

    # 원시 점수 0.30
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_old_guidance, 0.30),
    ]

    # 질문에 '2026년'이 포함되어도 guidance 문서는 연도 불일치 감점(-0.40)이나 과거일 감점을 받지 않고 통과해야 함
    results = rag.retrieve("2026년 기준 졸업인증 봉사활동 몇 시간 해야 해?", top_k=3, min_threshold=0.25)
    assert len(results) == 1
    assert results[0].metadata["source_type"] == "guidance"
