"""
Codex 2차 재검토 수정 사항 1~5에 대한 재현 및 검증 테스트 슈트.

검증 항목:
1. build_unified_dataset: 게시일이 동일한 상태에서 확인 시각에 따른 정정 공지(내용 축소/마감일 변경) 채택,
   원문 수정일과 확인 시각 분리 및 타임존 처리
2. ingest_unified_db: --clean/--allow-existing 제거 및 오직 존재하지 않는 새 경로만 허용 (빈 기존 디렉터리도 거부)
3. core/rag: '교내 파이썬 코딩 교육 신청' 등 학내 기술 질문 정상 통과 vs '파이썬 코드 짜줘', '아이폰 스펙' 차단
4. core/rag & backend: 알 수 없는 API 예외 시 비밀 토큰/내부 URL이 answer 및 HTTP 응답에 일절 노출되지 않고 안전한 고정 안내문 반환
5. scripts/run_eval: 429 한도 초과 시 즉시 평가 중단, 미실행 항목 NOT_RUN 기록, 체크포인트 저장 및 성공 생성 지연 분리
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


# ── 1. 게시일이 같은 정정본 및 타임스탬프 처리 ───────────────────

def test_same_date_later_crawl_content_revision_adopted():
    """
    scripts/build_unified_dataset.py 결함 재현 1:
    두 문서의 게시일(date)이 '2026-09-01'로 동일하고,
    기존 문서는 긴 마감 공지('9월 20일 마감', 확인일 9/14, missing_notices_refreshed),
    신규 문서는 짧은 정정 공지('9월 15일 마감', 확인일 9/15, notice_archive)인 경우,
    확인 시각이 더 최신이고 본문이 변경되었으므로 신규 정정본이 채택되어야 한다.
    (단순 소스 우선순위나 긴 본문 우선으로 기각되지 않아야 함)
    """
    from scripts.build_unified_dataset import resolve_document_conflict

    existing_doc = {
        "id": "notice-deadline-01",
        "url": "https://www.hansung.ac.kr/bbs/101",
        "title": "2026학년도 2학기 특강 신청 안내",
        "content": "신청 마감은 9월 20일 18:00까지로 아주 길게 상세히 설명되어 있는 구버전 본문입니다.",
        "content_status": "text",
        "date": "2026-09-01",
        "last_checked_at": "2026-09-14T10:00:00+09:00",
        "_source_name": "missing_notices_refreshed",
    }

    incoming_doc = {
        "id": "notice-deadline-01",
        "url": "https://www.hansung.ac.kr/bbs/101",
        "title": "2026학년도 2학기 특강 신청 안내",
        "content": "마감 정정: 9월 15일 15:00 조기 마감.",
        "content_status": "text",
        "date": "2026-09-01",
        "last_checked_at": "2026-09-15T11:00:00+09:00",
    }

    chosen, chosen_source, reason = resolve_document_conflict(
        existing=existing_doc,
        new_doc=incoming_doc,
        existing_source="missing_notices_refreshed",
        new_source="notice_archive",
    )

    assert chosen is incoming_doc
    assert chosen_source == "notice_archive"
    assert "9월 15일" in chosen["content"]
    assert "revision" in reason or "newer" in reason or "crawl" in reason


def test_source_updated_at_stronger_than_last_checked_at():
    """
    원문 수정일(source_updated_at)이 확인 시각(last_checked_at)보다 강한 근거인 경우:
    기존 문서에 원문 수정일 '2026-09-16'이 있고,
    신규 문서는 원문 수정일이 없거나 더 과거인데 단순히 9/17에 재수집된 옛날 캐시 문서라면,
    기존 문서의 원문 수정일 최신성이 우선하여 기존 문서를 보존해야 한다.
    """
    from scripts.build_unified_dataset import resolve_document_conflict

    existing_doc = {
        "id": "notice-edit-02",
        "title": "장학금 지급 규정",
        "content": "최신 수정된 장학 규정 본문입니다.",
        "content_status": "text",
        "date": "2026-09-01",
        "source_updated_at": "2026-09-16T15:00:00+09:00",
        "last_checked_at": "2026-09-16T15:10:00+09:00",
        "_source_name": "official_pages_enriched",
    }

    stale_incoming = {
        "id": "notice-edit-02",
        "title": "장학금 지급 규정",
        "content": "과거 장학 규정 본문 (캐시 오류)",
        "content_status": "text",
        "date": "2026-09-01",
        "source_updated_at": "2026-09-10T10:00:00+09:00",  # 원문 수정일이 더 오래됨
        "last_checked_at": "2026-09-17T09:00:00+09:00",     # 수집일만 늦음
    }

    chosen, chosen_source, reason = resolve_document_conflict(
        existing=existing_doc,
        new_doc=stale_incoming,
        existing_source="official_pages_enriched",
        new_source="notice_archive",
    )

    assert chosen is existing_doc
    assert chosen_source == "official_pages_enriched"
    assert "최신 수정된" in chosen["content"]


def test_timezone_aware_timestamp_comparison():
    """
    타임존 차이(UTC vs KST)를 올바르게 인식하는지 검증:
    2026-09-15T09:00:00Z (UTC 09시 = KST 18시)가 2026-09-15T15:00:00+09:00 (KST 15시)보다
    3시간 더 늦은(최신) 시각임을 정확히 판정해야 한다.
    """
    from scripts.build_unified_dataset import resolve_document_conflict

    doc_kst = {
        "id": "tz-01",
        "title": "공지",
        "content": "KST 15시 버전",
        "content_status": "text",
        "date": "2026-09-15",
        "source_updated_at": "2026-09-15T15:00:00+09:00",
    }
    doc_utc = {
        "id": "tz-01",
        "title": "공지",
        "content": "UTC 09시(=KST 18시) 버전",
        "content_status": "text",
        "date": "2026-09-15",
        "source_updated_at": "2026-09-15T09:00:00Z",
    }

    chosen, chosen_source, reason = resolve_document_conflict(
        existing=doc_kst,
        new_doc=doc_utc,
        existing_source="src_a",
        new_source="src_b",
    )

    assert chosen is doc_utc
    assert chosen_source == "src_b"
    assert "KST 18시" in chosen["content"]


# ── 2. 격리 DB 새 경로만 허용 (--clean/--allow-existing 제거) ────

def test_ingest_strictly_requires_new_path_and_rejects_existing_dir(tmp_path):
    """
    scripts/ingest_unified_db.py:
    1) --clean, --allow-existing 옵션을 전면 제거하고 오직 '새 경로만' 허용.
    2) 빈 기존 디렉터리라도 이미 존재하면 FileExistsError 발생.
    3) 파일이 존재하는 기존 디렉터리도 FileExistsError 발생.
    4) 심볼릭 링크 및 보호 DB(data/chroma_db 등)는 PermissionError 발생.
    5) 아직 존재하지 않는 새 경로만 정상 반환.
    """
    import inspect
    from scripts.ingest_unified_db import validate_persist_dir, ingest_unified

    # 1. 함수의 인자 시그니처에서 clean, allow_existing 제거 확인
    val_params = inspect.signature(validate_persist_dir).parameters
    assert "clean" not in val_params, "validate_persist_dir에 clean 인자가 남아있습니다."
    assert "allow_existing" not in val_params, "validate_persist_dir에 allow_existing 인자가 남아있습니다."

    ingest_params = inspect.signature(ingest_unified).parameters
    assert "clean" not in ingest_params, "ingest_unified에 clean 인자가 남아있습니다."
    assert "allow_existing" not in ingest_params, "ingest_unified에 allow_existing 인자가 남아있습니다."

    # 2. 빈 디렉터리 거부
    empty_dir = tmp_path / "empty_existing_dir"
    empty_dir.mkdir()
    with pytest.raises(FileExistsError):
        validate_persist_dir(empty_dir)

    # 3. 파일이 있는 디렉터리 거부
    populated_dir = tmp_path / "populated_dir"
    populated_dir.mkdir()
    (populated_dir / "some.db").write_text("dummy")
    with pytest.raises(FileExistsError):
        validate_persist_dir(populated_dir)

    # 4. 심볼릭 링크 거부
    symlink_path = tmp_path / "link_dir"
    os.symlink(tmp_path, symlink_path)
    try:
        with pytest.raises(PermissionError):
            validate_persist_dir(symlink_path)
    finally:
        if symlink_path.is_symlink():
            symlink_path.unlink()

    # 5. 아직 존재하지 않는 새 경로는 정상 통과
    new_dir = tmp_path / "fresh_new_isolated_db"
    assert not new_dir.exists()
    validated = validate_persist_dir(new_dir)
    assert validated == new_dir.resolve()
    assert not new_dir.exists()  # 검증 함수가 디렉터리를 미리 생성하지 않음


# ── 3. 학내 파이썬 교육 질문 통과 vs 무관 코드 요청 차단 ─────────

def test_campus_tech_education_queries_distinguished_from_generic_code_gen():
    """
    core/rag.py:
    1) '교내 파이썬 코딩 교육 신청 방법 알려줘'처럼 학내 교육/특강/신청 맥락이 있는 질문은
       단순히 '파이썬' 단어가 포함되었다는 이유로 차단(0건)되지 않고 정상 통과(점수 0.35)해야 한다.
    2) '파이썬으로 이진 탐색 트리 구현하는 코드 짜줘'처럼 일반 코드 작성을 요청하는 질문은
       차단되어 빈 결과(0건) -> LLM 호출 없이 조기 no_context 유보되어야 한다.
    3) '2026년 아이폰 스펙 알려줘' 질문도 차단되어야 한다.
    4) 'TOPCIT 평가', 'CPA 장학금' 단축 질문 구제는 정상 유지되어야 한다.
    """
    from core.rag import CampusRAG

    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.llm = None
    rag.chain = None
    rag.provider = "gemini"
    rag.gemini_model_name = "gemini-3.8-flash"

    doc_python_edu = Document(
        page_content="2026학년도 SW중심대학 교내 파이썬 코딩 역량강화 교육 신청 안내입니다. 한성대 학부생 대상.",
        metadata={
            "title": "[SW중심] 교내 파이썬 코딩 역량강화 교육생 모집 안내",
            "date": "2026-09-05",
            "url": "https://hansung.ac.kr/bbs/python_edu",
            "content_status": "text",
        }
    )
    doc_scholarship = Document(
        page_content="2026학년도 2학기 국가장학금 2차 신청 안내 본문입니다.",
        metadata={
            "title": "2026학년도 2학기 국가장학금 신청 안내",
            "date": "2026-08-12",
            "url": "https://hansung.ac.kr/bbs/scholarship",
            "content_status": "text",
        }
    )
    doc_mentoring = Document(
        page_content="진로 탐색 및 취업 지원 멘토링 프로그램 안내입니다.",
        metadata={
            "title": "진로 탐색 멘토링 프로그램 안내",
            "date": "2026-09-08",
            "url": "https://hansung.ac.kr/bbs/mentoring",
            "content_status": "text",
        }
    )
    doc_topcit = Document(
        page_content="제26회 TOPCIT 정기평가 단체접수 안내입니다.",
        metadata={
            "title": "★기간연장★ [SW중심] 제26회 TOPCIT 정기평가 시행 안내",
            "date": "2026-09-04",
            "url": "https://hansung.ac.kr/bbs/topcit",
            "content_status": "text",
        }
    )

    # 1. 정상 학내 파이썬 교육 질문 (원시 점수 0.35) -> 반드시 회수되어야 함!
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_python_edu, 0.35),
    ]
    res_edu = rag.retrieve("교내 파이썬 코딩 교육 신청 방법 알려줘", top_k=3, min_threshold=0.25)
    assert len(res_edu) == 1, "정상 학내 파이썬 교육 공지가 차단되었습니다."
    assert "파이썬" in res_edu[0].metadata["title"]

    # 2. 무관 코드 생성 요구 (원시 점수 0.19) -> 차단되어야 함
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_mentoring, 0.19),
    ]
    res_code = rag.retrieve("파이썬으로 이진 탐색 트리 구현하는 코드 짜줘", top_k=3, min_threshold=0.25)
    assert len(res_code) == 0, "무관 코드 생성 요청이 통과되었습니다."

    # 3. 무관 기기 스펙 요구 (원시 점수 0.18) -> 차단되어야 함
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_scholarship, 0.18),
    ]
    res_gadget = rag.retrieve("2026년 아이폰 스펙 알려줘", top_k=3, min_threshold=0.25)
    assert len(res_gadget) == 0, "무관 아이폰 질문이 통과되었습니다."

    # 4. TOPCIT 단축 질의 구제 유지 확인 (원시 점수 0.20 -> 어휘 보너스 0.28)
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = [
        (doc_topcit, 0.20),
    ]
    res_topcit = rag.retrieve("TOPCIT 평가", top_k=3, min_threshold=0.25)
    assert len(res_topcit) == 1
    assert "TOPCIT" in res_topcit[0].metadata["title"]


# ── 4. 알 수 없는 API 예외 시 비밀정보 비노출 및 안전한 응답 ─────

def test_api_exception_sanitized_and_no_leak_in_answer_and_http():
    """
    core/rag.py & backend/main.py:
    LLM 호출 중 내부 URL이나 가짜 비밀 토큰이 포함된 임의의 예외(RuntimeError 등)가 발생했을 때:
    1) core/rag.py의 answer에 비밀 토큰이나 내부 URL이 절대 포함되지 않고 안전한 고정 안내문이 들어간다.
    2) FastAPI /api/query 응답의 JSON 전체 문자열에도 비밀 토큰이나 내부 URL이 노출되지 않는다.
    3) status='api_error', error_type='internal_api_error'가 구조화되어 반환된다.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    import backend.main as bm
    from core.rag import CampusRAG

    secret_leak_attempt = "Failed connecting to https://internal-mgmt.hansung.ac.kr:9443/v1?token=SUPER_SECRET_TOKEN_XYZ987654"

    # 1. RAG 레벨 검증
    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.provider = "gemini"
    rag.gemini_model_name = "gemini-3.8-flash"

    class LeakyChain:
        def invoke(self, inputs):
            raise RuntimeError(secret_leak_attempt)

    rag.llm = object()
    rag.chain = LeakyChain()

    dummy_doc = Document(
        page_content="테스트 공지 본문입니다.",
        metadata={"title": "테스트 공지", "date": "2026-09-15", "url": "https://hansung.ac.kr/test", "source": "테스트"}
    )
    with patch.object(rag, "retrieve", return_value=[dummy_doc]):
        res = rag.query("테스트 질문")

    # core/rag의 answer 검증
    assert "SUPER_SECRET_TOKEN" not in res["answer"]
    assert "internal-mgmt" not in res["answer"]
    assert "https://" not in res["answer"]
    assert res["status"] == "api_error"
    assert any(w in res["answer"] for w in ("일시적인 오류", "일시적인 장애", "서비스"))

    # 2. FastAPI HTTP 응답 검증
    mock_rag_for_api = MagicMock()
    mock_rag_for_api.query.return_value = res

    client = TestClient(app)
    with patch.object(bm, "rag_instance", mock_rag_for_api):
        resp = client.post("/api/query", json={"question": "테스트 질문", "top_k": 3})
        assert resp.status_code == 200
        body = resp.text
        assert "SUPER_SECRET_TOKEN" not in body
        assert "internal-mgmt" not in body
        data = resp.json()
        assert data["status"] == "api_error"
        assert data["error_type"] == "internal_api_error"
        assert "SUPER_SECRET_TOKEN" not in data["answer"]


# ── 5. 평가 실행 제어: 429 중단, NOT_RUN 기록, 지연 분리 ──────────

def test_run_eval_stops_on_rate_limit_and_records_not_run(tmp_path):
    """
    scripts/run_eval.py:
    1) 평가 실행 중 429(Rate Limit / Quota Exceeded) 에러가 발생하면,
       이후 질문들에 대해 불필요한 API 호출을 즉시 중단한다.
    2) 미실행된 잔여 질문들은 status='NOT_RUN', api_status='not_run'으로 명확히 기록한다.
    3) 중간 상태를 체크포인트 JSON 파일로 안전하게 저장한다.
    4) 지연 시간 메트릭: 정상 생성 지연(generation_latency)에는 429 실패 지연이나 NOT_RUN(0초)이
       섞이지 않고 성공 생성 표본만을 대상으로 분리 집계된다.
    """
    from scripts.run_eval import run_evaluation_controlled

    eval_dataset = [
        {
            "id": "item-01",
            "split": "test",
            "question": "첫 번째 질문 (성공 케이스)",
            "expected_urls": ["https://hansung.ac.kr/1"],
            "expected_facts": "성공 팩트",
            "grounding_quotes": ["성공 팩트"],
            "negative_constraints": [],
            "should_abstain": False,
        },
        {
            "id": "item-02",
            "split": "test",
            "question": "두 번째 질문 (429 한도 초과 케이스)",
            "expected_urls": ["https://hansung.ac.kr/2"],
            "expected_facts": "두 번째 팩트",
            "grounding_quotes": ["두 번째 팩트"],
            "negative_constraints": [],
            "should_abstain": False,
        },
        {
            "id": "item-03",
            "split": "test",
            "question": "세 번째 질문 (중단되어 실행되지 않아야 함)",
            "expected_urls": ["https://hansung.ac.kr/3"],
            "expected_facts": "세 번째 팩트",
            "grounding_quotes": ["세 번째 팩트"],
            "negative_constraints": [],
            "should_abstain": False,
        },
        {
            "id": "item-04",
            "split": "test",
            "question": "네 번째 질문 (중단되어 실행되지 않아야 함)",
            "expected_urls": ["https://hansung.ac.kr/4"],
            "expected_facts": "네 번째 팩트",
            "grounding_quotes": ["네 번째 팩트"],
            "negative_constraints": [],
            "should_abstain": False,
        },
    ]

    dataset_file = tmp_path / "test_eval_dataset.json"
    dataset_file.write_text(json.dumps(eval_dataset, ensure_ascii=False), encoding="utf-8")
    checkpoint_file = tmp_path / "test_eval_checkpoint.json"

    call_count = 0
    def mock_query(q, top_k=3):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 1번 질문: 성공 생성 (지연 3.5초)
            return {
                "answer": "성공 팩트 안내입니다.",
                "sources": [{"title": "1", "source": "1", "category": "1", "date": "2026-09-01", "url": "https://hansung.ac.kr/1"}],
                "status": "success",
                "api_called": True,
                "provider": "gemini",
                "model": "gemini-3.8-flash",
                "_mock_latency": 3.5,
            }
        elif call_count == 2:
            # 2번 질문: 429 한도 초과 (지연 0.3초)
            return {
                "answer": "AI 서비스 요청 한도(Rate Limit)에 도달했습니다(429 Resource Exhausted).",
                "sources": [],
                "status": "api_error",
                "error": "429 RESOURCE_EXHAUSTED: Quota exceeded for metric",
                "api_called": True,
                "provider": "gemini",
                "model": "gemini-3.8-flash",
                "_mock_latency": 0.3,
            }
        else:
            pytest.fail(f"429 발생 이후에 RAG query가 추가 호출되었습니다! (호출 번호: {call_count})")

    mock_rag = MagicMock()
    mock_rag.query.side_effect = mock_query
    mock_rag.retrieve.return_value = [
        Document(page_content="팩트", metadata={"url": "https://hansung.ac.kr/1", "title": "공지"})
    ]

    eval_result = run_evaluation_controlled(
        dataset_path=str(dataset_file),
        rag_instance=mock_rag,
        checkpoint_path=str(checkpoint_file),
        stop_on_rate_limit=True,
    )

    # 1. 429 발생 즉시 중단되어 총 2회만 호출되었는지 확인
    assert call_count == 2
    assert checkpoint_file.exists()

    details = eval_result["details"]
    assert len(details) == 4

    # 2. 개별 항목 상태 확인
    assert details[0]["answer_eval"]["status"] == "PASS"
    assert details[1]["answer_eval"]["status"] == "API_ERROR"
    assert details[2]["answer_eval"]["status"] == "NOT_RUN"
    assert details[3]["answer_eval"]["status"] == "NOT_RUN"

    # 3. 미실행 항목의 메타데이터 확인
    assert details[2]["api_status"] == "not_run"
    assert details[2]["api_called"] is False

    # 4. 메트릭 검증: NOT_RUN 수치 분리
    metrics = eval_result["metrics"]
    assert metrics["pass_count"] == 1
    assert metrics["api_error_count"] == 1
    assert metrics["not_run_count"] == 2

    # 5. 정상 생성 지연(gen_latency)에 429 오류 지연(0.3s)이 섞이지 않고 3.5s로 유지되는지 확인
    assert "gen_latency_p50_sec" in metrics
    assert metrics["gen_latency_p50_sec"] >= 3.0


@pytest.mark.parametrize('change', ['collection', 'missing_model'])
def test_checkpoint_rejects_collection_change_and_missing_context(change):
    from scripts.run_eval import validate_checkpoint_context
    context = {
        'dataset_sha256': 'fixed-dataset', 'split': 'all', 'provider': 'gemini',
        'model': 'test-model', 'chroma_persist_dir': '/tmp/isolated-eval',
        'chroma_collection_name': 'collection_a', 'top_k': 3, 'relevance_threshold': 0.25,
    }
    previous = dict(context)
    if change == 'collection':
        previous['chroma_collection_name'] = 'collection_b'
    else:
        del previous['model']
    with pytest.raises(ValueError):
        validate_checkpoint_context(context, previous)


def test_checkpoint_rejects_different_dataset_model_db_and_split(tmp_path):
    """
    scripts/run_eval.py:
    실행 조건(데이터셋 해시, 모델, DB 경로, split)이 다른 체크포인트에 대해
    재개(resume=True)를 시도할 때 오염 방지를 위해 즉시 ValueError를 발생시키는지 검증.
    """
    import hashlib
    from scripts.run_eval import run_evaluation_controlled, save_atomic_checkpoint

    dataset_a = [{"id": "a1", "split": "test", "question": "질문 A1", "expected_urls": [], "expected_facts": "A"}]
    dataset_b = [{"id": "b1", "split": "test", "question": "질문 B1", "expected_urls": [], "expected_facts": "B"}]

    file_a = tmp_path / "dataset_a.json"
    file_b = tmp_path / "dataset_b.json"
    file_a.write_text(json.dumps(dataset_a, ensure_ascii=False), encoding="utf-8")
    file_b.write_text(json.dumps(dataset_b, ensure_ascii=False), encoding="utf-8")

    hash_a = hashlib.sha256(file_a.read_bytes()).hexdigest()
    ckpt_file = tmp_path / "eval_checkpoint.json"

    base_context = {
        "dataset_path": str(file_a.resolve()),
        "dataset_name": file_a.name,
        "dataset_sha256": hash_a,
        "split": "test",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "chroma_persist_dir": str((tmp_path / "chroma_a").resolve()),
        "chroma_collection_name": "eval_notices",
        "top_k": 3,
        "relevance_threshold": 0.25,
    }

    # 기본 체크포인트 생성 (A 실행 결과)
    ckpt_payload = {
        "saved_at": "2026-09-15T10:00:00+09:00",
        "execution_context": base_context,
        "completed_count": 1,
        "total_count": 1,
        "rate_limit_triggered": False,
        "details": [{"id": "a1", "question": "질문 A1", "answer_eval": {"status": "PASS"}, "api_status": "success"}],
    }
    save_atomic_checkpoint(str(ckpt_file), ckpt_payload)

    mock_rag = MagicMock()
    mock_rag.provider = "gemini"
    mock_rag.gemini_model_name = "gemini-3.8-flash"
    mock_rag.vectorstore = MagicMock()
    mock_rag.vectorstore._persist_directory = str((tmp_path / "chroma_a").resolve())

    # 1. 다른 데이터셋(B)으로 재개 시도 -> 데이터셋 해시 불일치 거부
    with pytest.raises(ValueError, match="데이터셋 해시 불일치"):
        run_evaluation_controlled(
            dataset_path=str(file_b),
            split_filter="test",
            rag_instance=mock_rag,
            checkpoint_path=str(ckpt_file),
            resume=True,
        )

    # 2. 다른 모델(gemini-1.5-pro)로 재개 시도 -> 모델 불일치 거부
    mock_rag_diff_model = MagicMock()
    mock_rag_diff_model.provider = "gemini"
    mock_rag_diff_model.gemini_model_name = "gemini-1.5-pro"
    mock_rag_diff_model.vectorstore._persist_directory = str((tmp_path / "chroma_a").resolve())
    with pytest.raises(ValueError, match="LLM Model 불일치"):
        run_evaluation_controlled(
            dataset_path=str(file_a),
            split_filter="test",
            rag_instance=mock_rag_diff_model,
            checkpoint_path=str(ckpt_file),
            resume=True,
        )

    # 3. 다른 DB 경로(chroma_b)로 재개 시도 -> DB 경로 불일치 거부
    mock_rag_diff_db = MagicMock()
    mock_rag_diff_db.provider = "gemini"
    mock_rag_diff_db.gemini_model_name = "gemini-3.8-flash"
    mock_rag_diff_db.vectorstore._persist_directory = str((tmp_path / "chroma_b").resolve())
    with pytest.raises(ValueError, match="Chroma DB 경로 불일치"):
        run_evaluation_controlled(
            dataset_path=str(file_a),
            split_filter="test",
            rag_instance=mock_rag_diff_db,
            checkpoint_path=str(ckpt_file),
            resume=True,
        )

    # 4. 다른 split(dev)으로 재개 시도 -> split 불일치 거부
    with pytest.raises(ValueError, match="데이터 분할\\(split\\) 불일치"):
        run_evaluation_controlled(
            dataset_path=str(file_a),
            split_filter="dev",
            rag_instance=mock_rag,
            checkpoint_path=str(ckpt_file),
            resume=True,
        )


def test_checkpoint_explicit_resume_retries_failed_items_and_preserves_history(tmp_path):
    """
    scripts/run_eval.py:
    1) 이전 실행에서 429로 실패(API_ERROR) 및 미실행(NOT_RUN)된 체크포인트가 있을 때,
    2) 명시적 재개(resume=True, retry_policy='failed_and_unrun')를 실행하면:
       - 이미 PASS한 문항은 호출 없이 보존된다.
       - 실패했던 문항(API_ERROR)은 재시도되며 이전 실패 기록이 previous_attempts에 보존된다.
       - 미실행 문항(NOT_RUN)도 정상 실행되어 전체 PASS로 완주된다.
    """
    from scripts.run_eval import run_evaluation_controlled

    dataset = [
        {"id": "q1", "split": "test", "question": "질문 1", "expected_urls": ["https://hansung.ac.kr/1"], "expected_facts": "팩트1", "grounding_quotes": ["팩트1"], "negative_constraints": [], "should_abstain": False},
        {"id": "q2", "split": "test", "question": "질문 2", "expected_urls": ["https://hansung.ac.kr/2"], "expected_facts": "팩트2", "grounding_quotes": ["팩트2"], "negative_constraints": [], "should_abstain": False},
        {"id": "q3", "split": "test", "question": "질문 3", "expected_urls": ["https://hansung.ac.kr/3"], "expected_facts": "팩트3", "grounding_quotes": ["팩트3"], "negative_constraints": [], "should_abstain": False},
        {"id": "q4", "split": "test", "question": "질문 4", "expected_urls": ["https://hansung.ac.kr/4"], "expected_facts": "팩트4", "grounding_quotes": ["팩트4"], "negative_constraints": [], "should_abstain": False},
    ]
    dataset_file = tmp_path / "eval_dataset.json"
    dataset_file.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    ckpt_file = tmp_path / "eval_checkpoint.json"

    # ── 1차 실행: 1번 PASS, 2번 429 실패, 3~4번 NOT_RUN ──
    calls_run1 = []
    def mock_query_run1(q, top_k=3):
        calls_run1.append(q)
        if len(calls_run1) == 1:
            return {
                "answer": "팩트1 완료", "sources": [{"url": "https://hansung.ac.kr/1", "title": "1", "source": "1", "category": "1", "date": "2026-09-01"}],
                "status": "success", "api_called": True, "provider": "gemini", "model": "gemini-3.8-flash", "_mock_latency": 3.0,
            }
        else:
            return {
                "answer": "429 한도 초과 오류", "sources": [],
                "status": "api_error", "error": "429 RESOURCE_EXHAUSTED", "api_called": True, "provider": "gemini", "model": "gemini-3.8-flash", "_mock_latency": 0.3,
            }

    mock_rag = MagicMock()
    mock_rag.provider = "gemini"
    mock_rag.gemini_model_name = "gemini-3.8-flash"
    mock_rag.vectorstore._persist_directory = str((tmp_path / "chroma").resolve())
    mock_rag.query.side_effect = mock_query_run1
    mock_rag.retrieve.return_value = [Document(page_content="팩트", metadata={"url": "https://hansung.ac.kr/1", "title": "공지"})]

    res1 = run_evaluation_controlled(
        dataset_path=str(dataset_file),
        rag_instance=mock_rag,
        checkpoint_path=str(ckpt_file),
        stop_on_rate_limit=True,
        resume=False,
    )

    assert len(calls_run1) == 2
    assert res1["metrics"]["pass_count"] == 1
    assert res1["metrics"]["api_error_count"] == 1
    assert res1["metrics"]["not_run_count"] == 2
    assert ckpt_file.exists()

    # ── 2차 실행: resume=True로 재개 (한도 복구 가정) ──
    calls_run2 = []
    def mock_query_run2(q, top_k=3):
        calls_run2.append(q)
        q_idx = q.split()[-1]
        # 재시도된 2번 및 신규 실행 3, 4번 모두 성공 응답 (팩트N 포함)
        return {
            "answer": f"팩트{q_idx} 완료 안내입니다.",
            "sources": [{"url": f"https://hansung.ac.kr/{q_idx}", "title": "공지", "source": "공지", "category": "공지", "date": "2026-09-01"}],
            "status": "success", "api_called": True, "provider": "gemini", "model": "gemini-3.8-flash", "_mock_latency": 3.2,
        }

    mock_rag.query.side_effect = mock_query_run2

    res2 = run_evaluation_controlled(
        dataset_path=str(dataset_file),
        rag_instance=mock_rag,
        checkpoint_path=str(ckpt_file),
        stop_on_rate_limit=True,
        resume=True,
        retry_policy="failed_and_unrun",
    )

    # 1. 1번 문항(이미 성공)은 재호출되지 않고 2, 3, 4번만 호출되었는지 확인
    assert len(calls_run2) == 3
    assert "질문 1" not in calls_run2
    assert "질문 2" in calls_run2
    assert "질문 3" in calls_run2
    assert "질문 4" in calls_run2

    # 2. 2번 문항의 이전 실패 이력(previous_attempts) 보존 및 시도 횟수 확인
    details2 = res2["details"]
    assert len(details2) == 4
    item2 = next(d for d in details2 if d["id"] == "q2")
    assert item2["answer_eval"]["status"] == "PASS"
    assert item2["attempt_count"] == 2
    assert len(item2["previous_attempts"]) == 1
    assert item2["previous_attempts"][0]["api_status"] == "api_error"
    assert "429" in str(item2["previous_attempts"][0]["api_error"])

    # 3. 전체 4건 완주 확인
    assert res2["metrics"]["pass_count"] == 4
    assert res2["metrics"]["api_error_count"] == 0
    assert res2["metrics"]["not_run_count"] == 0


def test_atomic_checkpoint_preserves_previous_file_on_write_failure(tmp_path):
    """
    scripts/run_eval.py:
    save_atomic_checkpoint() 실행 중 예외(디스크 가득 참, I/O 에러 등)가 발생해도,
    기존에 정상 저장되어 있던 체크포인트 파일이 절대 손상되지 않고 100% 보존되는지 검증.
    """
    from scripts.run_eval import save_atomic_checkpoint

    ckpt_path = tmp_path / "protected_checkpoint.json"
    original_data = {
        "saved_at": "2026-09-15T09:00:00+09:00",
        "completed_count": 10,
        "details": [{"id": "original-01", "status": "PASS"}],
    }
    # 기존 유효 체크포인트 파일 생성
    save_atomic_checkpoint(str(ckpt_path), original_data)
    assert ckpt_path.exists()
    assert json.loads(ckpt_path.read_text(encoding="utf-8")) == original_data

    # 쓰기 도중 에러가 발생하는 상황 시뮬레이션
    corrupt_attempt_data = {
        "saved_at": "2026-09-15T12:00:00+09:00",
        "completed_count": 2,
    }
    with patch("json.dump", side_effect=OSError("Simulated Disk Full (No space left on device)")):
        with pytest.raises(OSError, match="Simulated Disk Full"):
            save_atomic_checkpoint(str(ckpt_path), corrupt_attempt_data)

    # 실패 후에도 원본 파일이 전혀 손상되지 않고 보존되었는지 검증
    assert ckpt_path.exists()
    assert json.loads(ckpt_path.read_text(encoding="utf-8")) == original_data

    # 임시 파일(.tmp) 잔존 여부 확인 -> 모두 정리되어 있어야 함
    tmp_files = list(tmp_path.glob(".*.tmp*"))
    assert len(tmp_files) == 0


def test_checkpoint_without_resume_flag_starts_fresh(tmp_path):
    """
    scripts/run_eval.py:
    기존 체크포인트 파일이 존재하더라도 resume=False(기본값)인 경우,
    기존 체크포인트의 문항들을 재사용하지 않고 처음부터 새로 실행하는지 검증.
    (A 실행 후 B 실행 시 결과가 오염되는 현상 원천 차단)
    """
    import hashlib
    from scripts.run_eval import run_evaluation_controlled, save_atomic_checkpoint

    dataset = [
        {"id": "fresh-01", "split": "test", "question": "신규 질문 1", "expected_urls": [], "expected_facts": "팩트"},
    ]
    dataset_file = tmp_path / "fresh_dataset.json"
    dataset_file.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    ckpt_file = tmp_path / "existing_checkpoint.json"

    # 기존 체크포인트에 이전 실행(A)의 잔여 문항이 남아있다고 가정
    old_ckpt_payload = {
        "saved_at": "2026-09-15T08:00:00+09:00",
        "execution_context": {
            "dataset_path": str(dataset_file.resolve()),
            "dataset_name": dataset_file.name,
            "dataset_sha256": hashlib.sha256(dataset_file.read_bytes()).hexdigest(),
            "split": "test",
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "chroma_persist_dir": str((tmp_path / "chroma").resolve()),
        },
        "completed_count": 1,
        "total_count": 1,
        "details": [
            {"id": "stale-item-from-run-a", "question": "이전 질의 A", "answer_eval": {"status": "PASS"}, "api_status": "success"}
        ],
    }
    save_atomic_checkpoint(str(ckpt_file), old_ckpt_payload)

    mock_rag = MagicMock()
    mock_rag.provider = "gemini"
    mock_rag.gemini_model_name = "gemini-3.8-flash"
    mock_rag.vectorstore._persist_directory = str((tmp_path / "chroma").resolve())
    mock_rag.query.return_value = {
        "answer": "신규 답변", "sources": [], "status": "success", "api_called": True, "provider": "gemini", "model": "gemini-3.8-flash", "_mock_latency": 1.5,
    }
    mock_rag.retrieve.return_value = []

    # resume=False로 실행
    res = run_evaluation_controlled(
        dataset_path=str(dataset_file),
        rag_instance=mock_rag,
        checkpoint_path=str(ckpt_file),
        resume=False,
    )

    # 신규 질문만 결과에 포함되고 이전 stale-item은 포함되지 않아야 함
    ids = [d["id"] for d in res["details"]]
    assert ids == ["fresh-01"]
    assert "stale-item-from-run-a" not in ids
