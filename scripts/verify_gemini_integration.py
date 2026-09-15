#!/usr/bin/env python3
"""
CampusRAG 통합 DB 기반 Gemini API 실전 답변 검증 스크립트

새 격리 DB(data/integrated_eval_chroma_db)에서 필수 6대 핵심 질문 및 상시안내를
실제 Gemini API로 호출하여 답변과 검색 근거를 기록한다.
API 키는 절대 기록하거나 출력하지 않는다.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

VERIFY_QUESTIONS = [
    {
        "id": "probe-mentoring",
        "question": "2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간이 언제야?",
        "expected_check": "본문 상세 마감일(9월 17일 15:00) 포함, 제목 오타(6.11) 확정 안내 배제",
    },
    {
        "id": "probe-transfer",
        "question": "편입생 전적대학 학점 재인정 신청 대상자가 누구야?",
        "expected_check": "일반편입생 및 '외국인 유학생 제외' 조건 명시",
    },
    {
        "id": "probe-scholarship-dates",
        "question": "2026년 2학기 국가장학금 2차 신청 마감과 가구원 동의 마감은 각각 언제야?",
        "expected_check": "신청 마감(9월 9일 18시)과 서류제출/가구원 동의 마감(9월 16일 18시) 각각 구분 안내",
    },
    {
        "id": "probe-topcit-ext",
        "question": "제26회 TOPCIT 정기평가 한성대 단체접수 마감일이 언제까지로 연장됐어?",
        "expected_check": "1단계 구글 설문 온라인 접수 연장(~9.9)과 3단계 보증금 납부(~9.11 13:00) 등 단계별 일정 구분",
    },
    {
        "id": "probe-short-topcit",
        "question": "TOPCIT 평가",
        "expected_check": "단축 검색어 정상 검색 및 TOPCIT 정기평가 안내 응답",
    },
    {
        "id": "probe-faq-grade-round",
        "question": "성적 평점평균 반올림 여부가 어떻게 돼?",
        "expected_check": "소수점 셋째 자리 이하 절사(버림) 처리 사실 안내 (반올림 아님)",
    },
    {
        "id": "probe-faq-grade-appeal",
        "question": "성적 이의신청 방법 알려줘",
        "expected_check": "성적 이의신청 절차 및 담당교수 문의 등 안내",
    },
    {
        "id": "probe-form-leave",
        "question": "자퇴원 서식은 어디서 받아?",
        "expected_check": "자퇴원 양식 및 학사서식/신청 절차 안내",
    },
    {
        "id": "probe-irrelevant",
        "question": "파이썬으로 이진 탐색 트리 구현하는 코드 짜줘",
        "expected_check": "관련 공지를 찾지 못했습니다 정상 유보",
    },
]


def run_gemini_probes(
    persist_dir: Path = ROOT / "data/integrated_eval_chroma_db",
    collection_name: str = "campus_knowledge",
    output_path: Path = ROOT / "data/gemini_integration_results.json",
    resume: bool = False,
    retry_errors: bool = False,
):
    """실제 Gemini RAG 호출 검증을 수행하고 결과를 저장한다."""
    os.environ["CHROMA_PERSIST_DIR"] = str(persist_dir)
    os.environ["CHROMA_COLLECTION_NAME"] = collection_name

    import config
    from core.rag import CampusRAG

    if config.LLM_PROVIDER.lower() != "gemini" or not config.GEMINI_API_KEY:
        raise RuntimeError("LLM_PROVIDER=gemini 및 GEMINI_API_KEY가 설정되어 있어야 합니다.")

    sqlite_file = persist_dir / "chroma.sqlite3"
    sqlite_sha = hashlib.sha256(sqlite_file.read_bytes()).hexdigest() if sqlite_file.exists() else ""

    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "provider": config.LLM_PROVIDER,
        "model": config.GEMINI_MODEL,
        "db_dir": str(persist_dir.relative_to(ROOT)),
        "db_sqlite_sha256": sqlite_sha,
        "results": [],
    }

    if (resume or retry_errors) and output_path.exists():
        try:
            prev = json.loads(output_path.read_text(encoding="utf-8"))
            if prev.get("model") == config.GEMINI_MODEL and prev.get("db_sqlite_sha256") == sqlite_sha:
                report = prev
                logger.info("기존 결과에서 재개합니다. (기존 항목: %d개)", len(report["results"]))
        except Exception as e:
            logger.warning("Resume 로드 실패, 새로 시작: %s", e)

    if retry_errors:
        # success인 항목만 유지하고 api_error인 항목은 재시도
        report["results"] = [r for r in report["results"] if r.get("status") == "success"]
        logger.info("API 에러 항목 재시도 모드: 성공 유지 %d건, 나머지 재시도", len(report["results"]))

    done_ids = {r["id"] for r in report["results"]}

    logger.info("CampusRAG 초기화 (Gemini API 로드)...")
    rag = CampusRAG(load_llm=True)
    report["total_chunks_in_db"] = rag.vectorstore._collection.count()

    for item in VERIFY_QUESTIONS:
        qid = item["id"]
        q = item["question"]
        expected = item["expected_check"]

        if qid in done_ids:
            logger.info("이미 완료된 항목 건너뜀: %s", qid)
            continue

        logger.info("질의 실행 중: [%s] '%s'", qid, q)
        t_start = time.monotonic()
        try:
            # retrieve와 query를 각각 확인하여 근거와 답변 모두 기록
            evidence_docs = rag.retrieve(q)
            resp = rag.query(q)
            elapsed = round(time.monotonic() - t_start, 3)

            entry = {
                "id": qid,
                "question": q,
                "expected_check": expected,
                "answer": resp.get("answer", ""),
                "status": resp.get("status", "success"),
                "api_called": resp.get("api_called", True),
                "error": resp.get("error"),
                "latency_seconds": resp.get("latency_seconds", elapsed),
                "sources": resp.get("sources", []),
                "evidence_chunks": [
                    {
                        "chunk_id": d.metadata.get("chunk_id"),
                        "title": d.metadata.get("title"),
                        "score": round(d.metadata.get("_score", 0.0), 4),
                        "source_type": d.metadata.get("source_type"),
                        "content_preview": d.page_content[:250].replace("\n", " "),
                    }
                    for d in evidence_docs
                ],
            }
        except Exception as exc:
            elapsed = round(time.monotonic() - t_start, 3)
            err_msg = str(exc)
            if config.GEMINI_API_KEY:
                err_msg = err_msg.replace(config.GEMINI_API_KEY, "[REDACTED]")
            entry = {
                "id": qid,
                "question": q,
                "expected_check": expected,
                "answer": "",
                "status": "api_error",
                "api_called": True,
                "error": err_msg[:500],
                "latency_seconds": elapsed,
                "sources": [],
                "evidence_chunks": [],
            }

        report["results"].append(entry)
        # 매 문항마다 즉시 체크포인트 저장
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("  -> 완료: status=%s, latency=%.2fs", entry["status"], entry["latency_seconds"])

        # Rate Limit 방지를 위한 호출 간격 페이싱
        time.sleep(2.5)

    logger.info("모든 프로브 실행 완료! 결과 파일: %s", output_path)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CampusRAG Gemini Probes")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()

    run_gemini_probes(resume=args.resume, retry_errors=args.retry_errors)
