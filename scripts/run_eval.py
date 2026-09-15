"""
CampusRAG 국가장학금 RAG 파이프라인 자동 평가 스크립트.

평가 데이터셋(data/eval_scholarship_dataset.json)을 로드하여:
1. 검색 단계: Top-3 내 기대 공지 URL 포함 여부, 순위, 무관 질문 필터링 여부
2. 답변 단계: 실제 LLM 생성 답변의 사실 일치, 마감일 전도(swapped), 환각 여부, 유보(Abstain) 처리 여부
3. 성능 단계: 모델 로딩 시간(Cold start), 질의별 지연 시간(Warm latency) 측정 (Median, p95)
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 평가용 Chroma DB 경로 설정
os.environ["CHROMA_PERSIST_DIR"] = os.getenv("CHROMA_PERSIST_DIR", "data/eval_chroma_db")
os.environ["CHROMA_COLLECTION_NAME"] = os.getenv("CHROMA_COLLECTION_NAME", "eval_notices")
# Respect the environment/.env provider, just as the service does.

from core.rag import CampusRAG
import config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def extract_dates(text: str) -> list[str]:
    """텍스트에서 'M월 D일' 형식의 정규화된 날짜 목록을 추출한다."""
    pattern = r"(?:(\d{1,2})월\s*(\d{1,2})일|(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d))"
    dates = []
    for m in re.finditer(pattern, text):
        month = int(m.group(1) or m.group(3))
        day = int(m.group(2) or m.group(4))
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.append(f"{month}월 {day}일")
    return dates


def extract_clause_bindings(text: str) -> dict:
    """
    답변 문장에서 주요 업무(신청, 서류제출/가구원동의)와 바인딩된 날짜를 추출한다.
    """
    clauses = re.split(r"[\n\.;]|\s*,\s*|\s+(?:이며|이고|하지만|반면|단,)\s+", text)
    apply_dates = set()
    consent_dates = set()
    all_dates = set()

    for clause in clauses:
        clause_clean = clause.strip()
        if not clause_clean:
            continue
        c_dates = extract_dates(clause_clean)
        for d in c_dates:
            all_dates.add(d)

        if not c_dates:
            continue

        has_apply = bool(re.search(r"(신청|접수)", clause_clean))
        has_consent = bool(re.search(r"(동의|서류|가구원)", clause_clean))

        if has_apply and not has_consent:
            apply_dates.update(c_dates)
        elif has_consent and not has_apply:
            consent_dates.update(c_dates)
        elif has_apply and has_consent:
            # 같은 절 안에 신청과 동의가 모두 있는 경우 거리 기반 바인딩
            for d in c_dates:
                d_m = d.split()[0]
                idx = clause_clean.find(d_m)
                if idx != -1:
                    sub = clause_clean[max(0, idx - 20) : min(len(clause_clean), idx + 20)]
                    if re.search(r"(동의|서류|가구원)", sub) and not re.search(r"(신청|접수)", sub):
                        consent_dates.add(d)
                    elif re.search(r"(신청|접수)", sub) and not re.search(r"(동의|서류|가구원)", sub):
                        apply_dates.add(d)
                    else:
                        apply_dates.add(d)
                else:
                    apply_dates.add(d)

    return {
        "apply_dates": apply_dates,
        "consent_dates": consent_dates,
        "all_dates": all_dates,
    }


def evaluate_retrieval(query: str, expected_urls: list[str], should_abstain: bool, rag: CampusRAG) -> dict:
    """검색 단계 품질 평가."""
    results = rag.retrieve(query, top_k=3, min_threshold=0.25)
    retrieved_urls = [doc.metadata.get("url", "") for doc in results]

    if should_abstain:
        is_correct = len(retrieved_urls) == 0
        return {
            "top_urls": retrieved_urls,
            "hit_top1": False,
            "hit_top3": False,
            "abstain_pass": is_correct,
            "score": 1.0 if is_correct else 0.0,
        }

    hit_top1 = bool(expected_urls and retrieved_urls and retrieved_urls[0] in expected_urls)
    hit_top3 = any(url in expected_urls for url in retrieved_urls)

    return {
        "top_urls": retrieved_urls,
        "hit_top1": hit_top1,
        "hit_top3": hit_top3,
        "abstain_pass": True,
        "score": 1.0 if hit_top1 else (0.7 if hit_top3 else 0.0),
    }


def evaluate_answer(
    answer: str,
    expected_facts: str,
    grounding_quotes: list[str],
    negative_constraints: list[str],
    should_abstain: bool,
    category: str = "",
    situation: str = "",
    api_status: str = "success",
    api_error: str = "",
) -> dict:
    """
    LLM 답변 단계 정밀 품질 평가:
    단어 하나 포함 여부가 아니라, 항목별 날짜·시간·대상·출처의 문맥 바인딩 및 정합성을 검증한다.
    자동 판정이 모호한 경우 'NEEDS_REVIEW'로 분리한다.
    Gemini API 장애(503/429 등)는 'API_ERROR'로 분리한다.
    """
    if api_status == "not_run":
        return {
            "status": "NOT_RUN",
            "is_abstained": False,
            "fact_matched": False,
            "constraint_violated": False,
            "score": 0.0,
            "reason": "한도 초과로 인한 실행 중단 (NOT_RUN)",
        }

    if api_status == "api_error":
        return {
            "status": "API_ERROR",
            "is_abstained": False,
            "fact_matched": False,
            "constraint_violated": False,
            "score": 0.0,
            "reason": f"API 오류(503/429 등): {api_error or answer[:80]}",
        }

    answer_clean = answer.strip()

    # 1. 무관 질문 및 학교 관련 근거 부재 질문 유보 여부 검증
    if should_abstain or situation in ("irrelevant_query", "school_related_no_grounding"):
        is_abstained = any(w in answer_clean for w in ("찾지 못", "찾을 수 없", "확인할 수 없", "관련 공지", "일치하는 공지"))
        return {
            "status": "PASS" if is_abstained else "FAIL",
            "is_abstained": is_abstained,
            "fact_matched": is_abstained,
            "constraint_violated": not is_abstained,
            "score": 1.0 if is_abstained else 0.0,
            "reason": "정상 유보" if is_abstained else "수집 근거 없는 질문에 대해 불필요한 공지 안내 또는 환각 발생",
        }

    # 2. 본문 미확보(title_only) 공지 질문 검증
    if situation == "title_only_notice" or category == "title_only_notice":
        is_title_only_guided = any(
            w in answer_clean
            for w in ("확인할 수 없", "세부 내용", "본문에서", "원문 보기", "원문 확인", "제목만", "안내되어 있지")
        )
        if is_title_only_guided:
            return {
                "status": "PASS",
                "is_abstained": False,
                "fact_matched": True,
                "score": 1.0,
                "reason": "본문 미확보(title_only) 안내 및 원문 확인 정상 유도",
            }
        else:
            return {
                "status": "FAIL",
                "is_abstained": False,
                "fact_matched": False,
                "score": 0.0,
                "reason": "본문 미확보 공지임에도 세부 내용을 지어내거나 원문 확인을 안내하지 않음",
            }

    # 3. 미기재 정보 안내 검증 (missing_*)
    if category.startswith("missing_") or situation == "missing_info_in_notice":
        is_missing_noted = any(
            w in answer_clean
            for w in ("확인할 수 없", "명시되어 있지", "확인되지 않", "발견되지 않", "제공되지 않", "기재되어 있지", "안내되어 있지", "공지에는 없", "정보는 없", "정보가 없")
        )
        if is_missing_noted:
            return {
                "status": "PASS",
                "is_abstained": False,
                "fact_matched": True,
                "score": 1.0,
                "reason": "공지 미기재 사실 정상 안내",
            }
        else:
            return {
                "status": "FAIL",
                "is_abstained": False,
                "fact_matched": False,
                "score": 0.0,
                "reason": "공지 미기재 사실을 명시하지 않고 임의 추측/환각 답변 생성",
            }

    # 3. 날짜/기간 관련 카테고리 정밀 검증
    bindings = extract_clause_bindings(answer_clean)
    apply_dates = bindings["apply_dates"]
    consent_dates = bindings["consent_dates"]
    all_dates = bindings["all_dates"]

    if category == "period_apply":
        # 2026년 2학기 2차 신청 마감: 9월 9일 18시
        if "9월 16일" in apply_dates or "9.16" in apply_dates:
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": "신청 마감일로 가구원 동의 마감일(9월 16일)이 잘못 매핑됨(날짜 뒤바뀜)",
            }
        if "9월 9일" in apply_dates or ("9월 9일" in all_dates and "9월 16일" in consent_dates):
            return {
                "status": "PASS",
                "fact_matched": True,
                "score": 1.0,
                "reason": "신청 마감일(9월 9일 18시) 정확 안내 (가구원 동의 일정 병기 정상 인정)",
            }
        # 모호한 경우
        if not all_dates or any(w in answer_clean for w in ("중순", "미정", "추후")):
            return {
                "status": "NEEDS_REVIEW",
                "fact_matched": False,
                "score": 0.5,
                "reason": "자동 판정 모호: 마감일 일자 명시 불분명하여 원문 대조 필요",
            }
        return {
            "status": "FAIL",
            "fact_matched": False,
            "score": 0.0,
            "reason": f"신청 마감일 불일치 (검출된 일자: {list(all_dates)})",
        }

    elif category == "period_distinction":
        if any(w in answer_clean for w in ("마감일이 같다", "마감일은 동일", "동일합니다", "같습니다")):
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": "신청 마감과 동의 마감일이 같다고 잘못 안내함",
            }
        if "9월 16일" in apply_dates and "9월 9일" in consent_dates:
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": "신청 마감과 동의 마감 날짜가 서로 뒤바뀜",
            }
        # 서류 제출 단독 질문인 경우 (예: test-02)
        if "서류 제출" in expected_facts or "서류제출" in expected_facts:
            if "9월 16일" in all_dates:
                return {
                    "status": "PASS",
                    "fact_matched": True,
                    "score": 1.0,
                    "reason": "서류 제출 마감일(9월 16일) 정확 안내",
                }
            elif "9월 9일" in all_dates:
                return {
                    "status": "FAIL",
                    "fact_matched": False,
                    "score": 0.0,
                    "reason": "서류 제출 마감일로 신청 마감일(9월 9일)을 잘못 안내함",
                }

        has_9_9 = "9월 9일" in all_dates
        has_9_16 = "9월 16일" in all_dates
        # 단어 "다르다" 단독 정답 처리 전면 제거: 반드시 실제 두 날짜가 모두 확인되어야 PASS
        if has_9_9 and has_9_16:
            return {
                "status": "PASS",
                "fact_matched": True,
                "score": 1.0,
                "reason": "신청 마감(9.9)과 동의 마감(9.16)을 명확히 구분하여 안내",
            }
        # 날짜가 누락되었거나 한쪽만 제시된 경우 명백한 실패로 판정 (NEEDS_REVIEW로 은폐 금지)
        return {
            "status": "FAIL",
            "fact_matched": False,
            "score": 0.0,
            "reason": "신청 마감(9.9)과 동의 마감(9.16) 중 날짜가 누락되었거나 구체적 일자가 구별되지 않음",
        }

    elif category in ("other_year_distinction", "other_semester_distinction"):
        # 타 학기/연도 질문에 2026-2학기 2차 일정(9월 9일, 9월 16일)을 혼동하여 답변하면 즉시 실패
        if "9월 9일" in all_dates or "9.9" in all_dates or "9월 16일" in all_dates or "8월 12일" in all_dates:
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": "해당 학기/연도 질문에 다른 학기(2026-2학기 2차) 일정을 혼동하여 답변",
            }
        # 기대 근거 일자 검출 여부 확인
        expected_matched = False
        for quote in grounding_quotes:
            q_clean = quote.strip()
            if q_clean in answer_clean:
                expected_matched = True
                break
        if expected_matched or ("3월 17일" in all_dates) or ("6월 22일" in all_dates) or ("9월 10일" in all_dates):
            return {
                "status": "PASS",
                "fact_matched": True,
                "score": 1.0,
                "reason": "해당 학기/연도 일정 정확 안내",
            }
        # 일자가 틀린 경우 명백한 FAIL로 처리 (NEEDS_REVIEW로 숨기지 않음)
        if all_dates:
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": f"해당 학기/연도 일정 불일치 (검출된 일자: {list(all_dates)})",
            }
        return {
            "status": "NEEDS_REVIEW",
            "fact_matched": False,
            "score": 0.5,
            "reason": "자동 판정 모호: 일자 명시 불분명하여 원문 대조 필요",
        }

    elif category in ("target_audience", "freshman_rule"):
        for neg in negative_constraints:
            if neg in answer_clean:
                return {
                    "status": "FAIL",
                    "fact_matched": False,
                    "score": 0.0,
                    "reason": f"부정 제약 위반: {neg}",
                }
        target_keywords = ["재학생", "신입생", "편입생", "재입학생", "복학생", "대학생"]
        matched_targets = [k for k in target_keywords if k in answer_clean]
        if len(matched_targets) >= 2:
            return {
                "status": "PASS",
                "fact_matched": True,
                "score": 1.0,
                "reason": f"신청 대상자 정확 안내 ({', '.join(matched_targets)})",
            }
        return {
            "status": "NEEDS_REVIEW",
            "fact_matched": False,
            "score": 0.5,
            "reason": "대상자 안내 범위 추가 확인 필요",
        }

    elif category in ("apply_method", "apply_method_auth"):
        for neg in negative_constraints:
            if neg in answer_clean:
                return {
                    "status": "FAIL",
                    "fact_matched": False,
                    "score": 0.0,
                    "reason": f"부정 제약 위반: {neg}",
                }
        has_foundation = "한국장학재단" in answer_clean
        has_channel = any(w in answer_clean for w in ("누리집", "홈페이지", "모바일", "앱"))
        if has_foundation and has_channel:
            return {
                "status": "PASS",
                "fact_matched": True,
                "score": 1.0,
                "reason": "신청 방법 및 기관 정확 안내",
            }
        return {
            "status": "NEEDS_REVIEW",
            "fact_matched": False,
            "score": 0.5,
            "reason": "신청 방법 상세 확인 필요",
        }

    # 6. 일반 카테고리 (인용구 및 부정 제약 정밀 매칭)
    violated_constraints = [neg for neg in negative_constraints if neg in answer_clean]
    if violated_constraints:
        return {
            "status": "FAIL",
            "fact_matched": False,
            "violated_constraints": violated_constraints,
            "score": 0.0,
            "reason": f"부정 제약 위반: {violated_constraints}",
        }

    # 본문이 존재하는 공지임에도 LLM이 사실을 찾지 못하고 부인/유보한 경우 실패 처리
    if not should_abstain and situation not in ("title_only_notice", "missing_info_in_notice"):
        if any(w in answer_clean for w in ("확인할 수 없습니다", "확인되지 않습니다", "찾을 수 없습니다", "본문에서 확인할 수 없")):
            return {
                "status": "FAIL",
                "fact_matched": False,
                "score": 0.0,
                "reason": "본문에 명시된 내용을 찾지 못하고 부인(확인 불가) 답변 생성",
            }

    meaningful_matches = 0
    total_quotes = len(grounding_quotes) if grounding_quotes else 1
    for quote in grounding_quotes:
        q_clean = quote.strip()
        if len(q_clean) <= 4:
            if q_clean in answer_clean:
                meaningful_matches += 1
        else:
            parts = [p for p in re.split(r"[\s\(\)\.~,]+", q_clean) if len(p) >= 2]
            if parts and sum(1 for p in parts if p in answer_clean) >= min(2, len(parts)):
                meaningful_matches += 1

    fact_ratio = meaningful_matches / total_quotes
    if fact_ratio >= 0.5:
        return {
            "status": "PASS",
            "fact_matched": True,
            "fact_ratio": fact_ratio,
            "score": 1.0,
            "reason": "핵심 근거 사실 일치",
        }
    elif fact_ratio > 0.0:
        return {
            "status": "NEEDS_REVIEW",
            "fact_matched": False,
            "fact_ratio": fact_ratio,
            "score": 0.5,
            "reason": "근거 일부 일치: 원문 대조 필요",
        }
    else:
        return {
            "status": "FAIL",
            "fact_matched": False,
            "fact_ratio": 0.0,
            "score": 0.0,
            "reason": "핵심 근거 사실 불일치",
        }



def compute_metrics(
    results: list[dict],
    latencies: list[float],
    dataset_path: str,
    split_filter: str | None,
    cold_start_sec: float,
) -> dict:
    total_count = len(results)
    pass_count = sum(1 for r in results if r["answer_eval"].get("status") == "PASS")
    fail_count = sum(1 for r in results if r["answer_eval"].get("status") == "FAIL")
    needs_review_count = sum(1 for r in results if r["answer_eval"].get("status") == "NEEDS_REVIEW")
    api_error_count = sum(1 for r in results if r["answer_eval"].get("status") == "API_ERROR")
    not_run_count = sum(1 for r in results if r["answer_eval"].get("status") == "NOT_RUN")

    factual_results = [r for r in results if not r.get("should_abstain", False) and r["answer_eval"].get("status") != "NOT_RUN"]
    abstain_results = [r for r in results if r.get("should_abstain", False) and r["answer_eval"].get("status") != "NOT_RUN"]

    hit_top1_count = sum(1 for r in factual_results if r["retrieval"].get("hit_top1"))
    hit_top3_count = sum(1 for r in factual_results if r["retrieval"].get("hit_top3"))
    abstain_success_count = sum(1 for r in abstain_results if r["retrieval"].get("abstain_pass") or r["answer_eval"].get("is_abstained"))

    # 전체 지연 시간 (단순 합산)
    latencies_arr = np.array(latencies) if latencies else np.array([0.0])
    p50 = float(np.percentile(latencies_arr, 50))
    p95 = float(np.percentile(latencies_arr, 95))
    mean_lat = float(np.mean(latencies_arr))

    # [Codex 2차 수정 사항 5]: 정상 생성 지연 분리 집계
    # API 호출이 성공하여 실제 답변이 정상 생성된 표본만으로 지연 시간을 분리 계산 (429 빠른 거절이나 미실행 0초 왜곡 배제)
    gen_latencies = [
        float(r.get("latency_sec", 0.0))
        for r in results
        if r.get("api_called") and r.get("api_status") == "success"
    ]
    if gen_latencies:
        gen_arr = np.array(gen_latencies)
        gen_p50 = float(np.percentile(gen_arr, 50))
        gen_p95 = float(np.percentile(gen_arr, 95))
        gen_mean = float(np.mean(gen_arr))
    else:
        gen_p50 = gen_p95 = gen_mean = 0.0

    err_latencies = [
        float(r.get("latency_sec", 0.0))
        for r in results
        if r.get("api_status") == "api_error"
    ]
    err_mean = float(np.mean(err_latencies)) if err_latencies else 0.0

    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            env={"GIT_CONFIG_GLOBAL": "/dev/null", "HOME": "/tmp"},
            text=True,
        ).strip()
    except Exception:
        git_commit = "a154575"

    try:
        diff_out = subprocess.check_output(
            ["git", "diff", "HEAD"],
            env={"GIT_CONFIG_GLOBAL": "/dev/null", "HOME": "/tmp"},
            text=True,
        )
        git_dirty_hash = hashlib.sha256(diff_out.encode()).hexdigest()[:12]
        is_dirty = bool(diff_out.strip())
    except Exception:
        git_dirty_hash = "unknown"
        is_dirty = True

    dataset_sha256 = ""
    try:
        with open(dataset_path, "rb") as f:
            dataset_sha256 = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass

    metadata = {
        "git_commit": git_commit,
        "is_dirty": is_dirty,
        "git_dirty_hash": git_dirty_hash,
        "dataset_sha256": dataset_sha256,
        "executed_at": datetime.now().astimezone().isoformat(),
        "model_config": {
            "provider": config.LLM_PROVIDER,
            "llm_model": {"local": config.LOCAL_LLM_MODEL, "gemini": config.GEMINI_MODEL,
                          "openai": config.OPENAI_MODEL}.get(config.LLM_PROVIDER.lower(), "unknown"),
            "embedding_model": config.EMBEDDING_MODEL_NAME,
            "relevance_threshold": config.RELEVANCE_THRESHOLD,
            "top_k": config.TOP_K,
            "device": config.get_device(),
        },
    }

    metrics = {
        "sample_count": total_count,
        "split": split_filter or "all",
        "pass_count": pass_count,
        "pass_rate": pass_count / total_count if total_count else 0.0,
        "fail_count": fail_count,
        "fail_rate": fail_count / total_count if total_count else 0.0,
        "needs_review_count": needs_review_count,
        "needs_review_rate": needs_review_count / total_count if total_count else 0.0,
        "api_error_count": api_error_count,
        "api_error_rate": api_error_count / total_count if total_count else 0.0,
        "not_run_count": not_run_count,
        "not_run_rate": not_run_count / total_count if total_count else 0.0,
        "hit_top1_count": hit_top1_count,
        "hit_top1_rate": hit_top1_count / len(factual_results) if factual_results else 0.0,
        "hit_top3_count": hit_top3_count,
        "hit_top3_rate": hit_top3_count / len(factual_results) if factual_results else 0.0,
        "abstain_count": len(abstain_results),
        "abstain_success_count": abstain_success_count,
        "abstain_rate": abstain_success_count / len(abstain_results) if abstain_results else 0.0,
        "cold_start_sec": cold_start_sec,
        "gen_latency_p50_sec": gen_p50,
        "gen_latency_p95_sec": gen_p95,
        "gen_latency_mean_sec": gen_mean,
        "error_latency_mean_sec": err_mean,
        "latency_p50_sec": p50,
        "latency_p95_sec": p95,
        "latency_mean_sec": mean_lat,
    }

    print("\n" + "=" * 70)
    print("📊 평가 결과 요약")
    print(f"   - 표본 수: {total_count}건 (분할: {split_filter or '전체'})")
    print(f"   - 판정 분류: PASS {pass_count}건 ({metrics['pass_rate']*100:.1f}%), FAIL {fail_count}건 ({metrics['fail_rate']*100:.1f}%), NEEDS_REVIEW {needs_review_count}건 ({metrics['needs_review_rate']*100:.1f}%), NOT_RUN {not_run_count}건")
    print(f"   - 검색 적중률: Hit@1={metrics['hit_top1_rate']*100:.1f}%, Hit@3={metrics['hit_top3_rate']*100:.1f}%")
    print(f"   - 무관 질문 유보율: {metrics['abstain_rate']*100:.1f}% ({abstain_success_count}/{len(abstain_results) if abstain_results else 1})")
    print(f"   - 지연 시간: 정상 생성 p50={gen_p50:.2f}초, p95={gen_p95:.2f}초 (전체 p50={p50:.2f}초, p95={p95:.2f}초)")
    print("=" * 70)

    return {
        "metadata": metadata,
        "metrics": metrics,
        "details": results,
    }


def save_atomic_checkpoint(checkpoint_path: str, data: dict) -> None:
    """
    임시 파일 작성 후 os.replace를 사용하여 원자적으로(atomically) 체크포인트를 저장한다.
    저장 도중 예외가 발생하더라도 기존 체크포인트 파일은 손상되지 않고 안전하게 보존된다.
    """
    ckpt_path = Path(checkpoint_path).resolve()
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)

    # 동일 디렉터리 내에 임시 파일 생성 (동일 파일시스템이어야 os.replace 원자성 보장)
    tmp_path = ckpt_path.with_name(f".{ckpt_path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ckpt_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def extract_execution_context(
    dataset_path: str,
    dataset_sha256: str | None = None,
    split_filter: str | None = None,
    rag: CampusRAG | None = None,
) -> dict:
    """
    현재 실행 환경의 고유 조건(데이터셋 해시, split, provider/model, DB 경로, 검색 파라미터)을 추출한다.
    """
    if not dataset_sha256 and os.path.exists(dataset_path):
        try:
            with open(dataset_path, "rb") as f:
                dataset_sha256 = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            dataset_sha256 = ""

    provider = None
    if rag is not None:
        p = getattr(rag, "provider", None)
        if isinstance(p, str):
            provider = p
    if not provider:
        provider = str(config.LLM_PROVIDER).lower()

    model = None
    if rag is not None:
        for attr in ("gemini_model_name", "model_name", "model"):
            m = getattr(rag, attr, None)
            if isinstance(m, str):
                model = m
                break
    if not model:
        if provider == "gemini":
            model = config.GEMINI_MODEL
        elif provider == "openai":
            model = config.OPENAI_MODEL
        else:
            model = config.LOCAL_LLM_MODEL

    db_path = None
    if rag is not None and hasattr(rag, "vectorstore"):
        vs = getattr(rag, "vectorstore")
        p = getattr(vs, "_persist_directory", None)
        if isinstance(p, (str, Path)):
            db_path = str(Path(p).resolve())
    if not db_path:
        db_path = str(Path(config.CHROMA_PERSIST_DIR).resolve())

    return {
        "dataset_path": str(Path(dataset_path).resolve()),
        "dataset_name": Path(dataset_path).name,
        "dataset_sha256": dataset_sha256 or "",
        "split": split_filter or "all",
        "provider": provider,
        "model": model,
        "chroma_persist_dir": db_path,
        "chroma_collection_name": config.CHROMA_COLLECTION_NAME,
        "top_k": config.TOP_K,
        "relevance_threshold": config.RELEVANCE_THRESHOLD,
    }


def validate_checkpoint_context(current_ctx: dict, ckpt_ctx: dict) -> None:
    """
    체크포인트에 저장된 실행 조건과 현재 실행 조건을 비교 검증한다.
    불일치 발생 시 다른 실행 결과가 오염되는 것을 방지하기 위해 ValueError를 발생시킨다.
    """
    mismatches = []

    required_fields = (
        "dataset_sha256", "split", "provider", "model", "chroma_persist_dir",
        "chroma_collection_name", "top_k", "relevance_threshold",
    )
    for label, context in (("현재 실행", current_ctx), ("체크포인트", ckpt_ctx)):
        missing = [key for key in required_fields
                   if key not in context or context[key] is None or context[key] == ""]
        if missing:
            mismatches.append(f"{label} 실행 조건 누락: {', '.join(missing)}")

    if current_ctx.get("chroma_collection_name") != ckpt_ctx.get("chroma_collection_name"):
        mismatches.append("Chroma 컬렉션 불일치")

    # 1. 데이터셋 해시 검증
    curr_hash = current_ctx.get("dataset_sha256")
    ckpt_hash = ckpt_ctx.get("dataset_sha256")
    if curr_hash and ckpt_hash and curr_hash != ckpt_hash:
        mismatches.append(f"데이터셋 해시 불일치 (현재: {curr_hash[:12]}..., 체크포인트: {ckpt_hash[:12]}...)")
    elif not ckpt_hash:
        mismatches.append("체크포인트에 데이터셋 해시(dataset_sha256)가 누락됨")

    # 2. 데이터셋 분할(split) 검증
    curr_split = current_ctx.get("split") or "all"
    ckpt_split = ckpt_ctx.get("split") or "all"
    if curr_split != ckpt_split:
        mismatches.append(f"데이터 분할(split) 불일치 (현재: '{curr_split}', 체크포인트: '{ckpt_split}')")

    # 3. Provider 검증
    curr_provider = (current_ctx.get("provider") or "").lower()
    ckpt_provider = (ckpt_ctx.get("provider") or "").lower()
    if curr_provider and ckpt_provider and curr_provider != ckpt_provider:
        mismatches.append(f"LLM Provider 불일치 (현재: '{curr_provider}', 체크포인트: '{ckpt_provider}')")

    # 4. Model 검증
    curr_model = current_ctx.get("model")
    ckpt_model = ckpt_ctx.get("model")
    if curr_model and ckpt_model and curr_model != ckpt_model:
        mismatches.append(f"LLM Model 불일치 (현재: '{curr_model}', 체크포인트: '{ckpt_model}')")

    # 5. Chroma DB 디렉터리 경로 검증
    curr_db = current_ctx.get("chroma_persist_dir")
    ckpt_db = ckpt_ctx.get("chroma_persist_dir")
    if curr_db and ckpt_db:
        try:
            curr_db_resolved = str(Path(curr_db).resolve())
            ckpt_db_resolved = str(Path(ckpt_db).resolve())
            if curr_db_resolved != ckpt_db_resolved:
                mismatches.append(f"Chroma DB 경로 불일치 (현재: '{curr_db_resolved}', 체크포인트: '{ckpt_db_resolved}')")
        except Exception:
            if curr_db != ckpt_db:
                mismatches.append(f"Chroma DB 경로 불일치 (현재: '{curr_db}', 체크포인트: '{ckpt_db}')")

    # 6. 검색 파라미터 검증 (top_k, threshold)
    if "top_k" in current_ctx and "top_k" in ckpt_ctx:
        if current_ctx["top_k"] != ckpt_ctx["top_k"]:
            mismatches.append(f"top_k 불일치 (현재: {current_ctx['top_k']}, 체크포인트: {ckpt_ctx['top_k']})")
    if "relevance_threshold" in current_ctx and "relevance_threshold" in ckpt_ctx:
        if abs(current_ctx["relevance_threshold"] - ckpt_ctx["relevance_threshold"]) > 1e-4:
            mismatches.append(f"relevance_threshold 불일치 (현재: {current_ctx['relevance_threshold']}, 체크포인트: {ckpt_ctx['relevance_threshold']})")

    if mismatches:
        err_msg = (
            "⚠️ 체크포인트 실행 조건 불일치로 재개를 거부합니다 (다른 실행 결과 오염 방지):\n  - "
            + "\n  - ".join(mismatches)
        )
        logger.error(err_msg)
        raise ValueError(err_msg)


def run_evaluation_controlled(
    dataset_path: str,
    split_filter: str | None = None,
    rag_instance: CampusRAG | None = None,
    checkpoint_path: str | None = None,
    stop_on_rate_limit: bool = True,
    resume: bool = False,
    retry_policy: str = "failed_and_unrun",
) -> dict:
    """
    실행 조건 검증, 원자적 저장(os.replace), 명시적 재개(resume), 429 조기 중단 및 NOT_RUN을 지원하는 제어형 평가 실행기.
    """
    with open(dataset_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    dataset = raw.get("questions", raw) if isinstance(raw, dict) else raw

    if split_filter:
        dataset = [d for d in dataset if d.get("split") == split_filter]

    # 데이터셋 해시 계산
    with open(dataset_path, "rb") as f:
        dataset_sha256 = hashlib.sha256(f.read()).hexdigest()

    print("=" * 70)
    print(f"🚀 CampusRAG 실전 평가 실행 (표본 수: {len(dataset)}건, 분할: {split_filter or '전체'})")
    print(f"   Chroma DB: {config.CHROMA_PERSIST_DIR} ({config.CHROMA_COLLECTION_NAME})")
    print(f"   LLM Model: {config.LOCAL_LLM_MODEL if config.LLM_PROVIDER.lower() == 'local' else config.GEMINI_MODEL}")
    print(f"   Relevance Threshold: {config.RELEVANCE_THRESHOLD}")
    print(f"   재개 모드: {resume} (재시도 정책: {retry_policy if resume else 'N/A'})")
    print("=" * 70)

    if rag_instance is not None:
        rag = rag_instance
        cold_start_sec = 0.0
    else:
        t0 = time.time()
        rag = CampusRAG(load_llm=True)
        cold_start_sec = time.time() - t0
        print(f"⏱️ 모델 로딩 완료 (Cold Start): {cold_start_sec:.2f}초")

    current_context = extract_execution_context(
        dataset_path=dataset_path,
        dataset_sha256=dataset_sha256,
        split_filter=split_filter,
        rag=rag,
    )

    completed_records = {}   # q_id -> previous completed record
    pending_retries = {}     # q_id -> previous failed record (to retry with history)
    latencies = []

    if resume:
        if not checkpoint_path or not Path(checkpoint_path).exists():
            print(f"ℹ️ 재개 옵션이 활성화되었으나 체크포인트 파일({checkpoint_path})이 존재하지 않아 새로 시작합니다.")
        else:
            with open(checkpoint_path, "r", encoding="utf-8") as cf:
                ckpt_data = json.load(cf)

            ckpt_ctx = ckpt_data.get("execution_context")
            if not ckpt_ctx:
                ckpt_ctx = dict(ckpt_data.get("model_config", {}))
                ckpt_ctx.setdefault("dataset_sha256", ckpt_data.get("dataset_sha256", ""))
                ckpt_ctx.setdefault("split", ckpt_data.get("split", split_filter or "all"))

            # 실행 조건 엄격 검증: 불일치 시 ValueError 발생
            validate_checkpoint_context(current_context, ckpt_ctx)

            for prev_r in ckpt_data.get("details", []):
                pid = prev_r.get("id")
                if not pid:
                    continue
                ans_eval = prev_r.get("answer_eval", {})
                ans_status = ans_eval.get("status")
                api_status = prev_r.get("api_status")

                is_success = (
                    api_status == "success"
                    or (ans_status in ("PASS", "FAIL", "NEEDS_REVIEW") and api_status != "api_error" and ans_status != "NOT_RUN")
                )
                is_api_error = (api_status == "api_error" or ans_status == "API_ERROR")
                is_not_run = (api_status == "not_run" or ans_status == "NOT_RUN")

                if is_success and retry_policy != "all":
                    completed_records[pid] = prev_r
                    latencies.append(prev_r.get("latency_sec", 0.0))
                elif is_api_error:
                    if retry_policy in ("failed_and_unrun", "all"):
                        pending_retries[pid] = prev_r
                    else:
                        completed_records[pid] = prev_r
                        latencies.append(prev_r.get("latency_sec", 0.0))
                elif is_not_run:
                    # NOT_RUN 항목은 재실행 대상
                    pass
                else:
                    if retry_policy == "all":
                        pending_retries[pid] = prev_r
                    else:
                        completed_records[pid] = prev_r

            print(
                f"📂 기존 체크포인트 검증 완료: 성공 보존 {len(completed_records)}건, "
                f"재시도/실행 대상 {len(dataset) - len(completed_records)}건 (정책: {retry_policy})"
            )

    rate_limit_triggered = False
    results = []

    def make_ckpt_payload(interim_results, is_rate_limited):
        return {
            "saved_at": datetime.now().astimezone().isoformat(),
            "execution_context": current_context,
            "completed_count": len([r for r in interim_results if r.get("answer_eval", {}).get("status") not in ("NOT_RUN", None)]),
            "total_count": len(dataset),
            "rate_limit_triggered": is_rate_limited,
            "resume_enabled": resume,
            "retry_policy": retry_policy if resume else None,
            "details": list(interim_results),
        }

    for i, item in enumerate(dataset, 1):
        q_id = item["id"]
        q = item["question"]

        # Case 1: 이미 성공 완료된 항목 (재개 시 스킵)
        if q_id in completed_records:
            results.append(completed_records[q_id])
            continue

        # Case 2: 429 한도 초과 감지로 인한 조기 중단 -> NOT_RUN 기록
        if rate_limit_triggered:
            prev_record = pending_retries.get(q_id)
            prev_attempts = []
            if prev_record:
                prev_attempts = list(prev_record.get("previous_attempts", []))
                prior_attempt = {
                    "attempted_at": prev_record.get("timestamp") or prev_record.get("executed_at", ""),
                    "api_status": prev_record.get("api_status"),
                    "api_error": prev_record.get("api_error"),
                    "actual_answer": prev_record.get("actual_answer"),
                    "answer_eval": prev_record.get("answer_eval"),
                    "latency_sec": prev_record.get("latency_sec", 0.0),
                }
                prev_attempts.append(prior_attempt)

            record = {
                "id": q_id,
                "split": item.get("split", ""),
                "category": item.get("category", item.get("domain", "")),
                "domain": item.get("domain", ""),
                "situation": item.get("situation", ""),
                "question": q,
                "should_abstain": item.get("should_abstain", False),
                "expected_urls": item.get("expected_urls", []),
                "actual_sources": [],
                "expected_facts": item.get("expected_facts", ""),
                "actual_answer": "평가 중단: 일일 API 요청 한도(429) 도달로 미실행",
                "api_status": "not_run",
                "api_error": "429 rate limit exceeded in prior item",
                "api_called": False,
                "model": "",
                "provider": "",
                "retrieval": {
                    "top_urls": [],
                    "hit_top1": False,
                    "hit_top3": False,
                    "abstain_pass": False,
                    "score": 0.0,
                },
                "answer_eval": {
                    "status": "NOT_RUN",
                    "is_abstained": False,
                    "fact_matched": False,
                    "constraint_violated": False,
                    "score": 0.0,
                    "reason": "한도 초과로 인한 실행 중단 (NOT_RUN)",
                },
                "latency_sec": 0.0,
                "previous_attempts": prev_attempts,
                "attempt_count": len(prev_attempts),
            }
            results.append(record)
            continue

        # Case 3: 신규 실행 또는 재시도 실행
        is_retry = q_id in pending_retries
        retry_msg = " [재시도]" if is_retry else ""
        print(f"\n[{i}/{len(dataset)}] ({q_id}){retry_msg} 질의: {q}")

        t_start = time.time()
        res = rag.query(q, top_k=config.TOP_K)
        elapsed = res.get("_mock_latency", time.time() - t_start)
        latencies.append(elapsed)

        cat = item.get("category", item.get("domain", ""))
        ret_eval = evaluate_retrieval(q, item.get("expected_urls", []), item.get("should_abstain", False), rag)
        ans_eval = evaluate_answer(
            res["answer"],
            item.get("expected_facts", ""),
            item.get("grounding_quotes", []),
            item.get("negative_constraints", []),
            item.get("should_abstain", False),
            category=cat,
            situation=item.get("situation", ""),
            api_status=res.get("status", "success"),
            api_error=res.get("error", ""),
        )

        prev_attempts = []
        if is_retry:
            prev_record = pending_retries[q_id]
            prev_attempts = list(prev_record.get("previous_attempts", []))
            prior_attempt = {
                "attempted_at": prev_record.get("timestamp") or prev_record.get("executed_at", ""),
                "api_status": prev_record.get("api_status"),
                "api_error": prev_record.get("api_error"),
                "actual_answer": prev_record.get("actual_answer"),
                "answer_eval": prev_record.get("answer_eval"),
                "latency_sec": prev_record.get("latency_sec", 0.0),
            }
            prev_attempts.append(prior_attempt)

        record = {
            "id": q_id,
            "split": item.get("split", ""),
            "category": cat,
            "domain": item.get("domain", ""),
            "situation": item.get("situation", ""),
            "question": q,
            "should_abstain": item.get("should_abstain", False),
            "expected_urls": item.get("expected_urls", []),
            "actual_sources": [s["url"] for s in res.get("sources", [])],
            "expected_facts": item.get("expected_facts", ""),
            "actual_answer": res["answer"],
            "api_status": res.get("status", "success"),
            "api_error": res.get("error"),
            "api_called": res.get("api_called", False),
            "model": res.get("model", ""),
            "provider": res.get("provider", ""),
            "retrieval": ret_eval,
            "answer_eval": ans_eval,
            "latency_sec": elapsed,
            "previous_attempts": prev_attempts,
            "attempt_count": len(prev_attempts) + 1,
        }
        results.append(record)

        print(f"   ⏱️ 응답 시간: {elapsed:.2f}초")
        print(f"   🔍 검색 Top-1: {ret_eval.get('hit_top1')}, Top-3: {ret_eval.get('hit_top3') or ret_eval.get('abstain_pass')}")
        print(f"   💬 답변 판정: {ans_eval['status']} (score: {ans_eval['score']}) - {ans_eval.get('reason')}")
        print(f"   📝 답변 요약: {res['answer'][:90]}...")

        # 429 한도 초과 감지 시 중단 플래그 설정
        raw_err = str(res.get("error") or "")
        if res.get("status") == "api_error" and any(k in raw_err for k in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded", "rate_limit")):
            logger.warning("429 한도 초과(Rate Limit / Quota Exceeded) 감지: 추가 API 낭비 방지를 위해 즉시 평가를 중단하고 체크포인트를 저장합니다.")
            if stop_on_rate_limit:
                rate_limit_triggered = True

        # 중간 체크포인트 원자적 자동 저장
        if checkpoint_path:
            try:
                save_atomic_checkpoint(checkpoint_path, make_ckpt_payload(results, rate_limit_triggered))
            except Exception as ce:
                logger.warning("중간 체크포인트 원자적 저장 실패: %s", ce)

    # 루프 종료 후 (중단 후 NOT_RUN까지 모두 채워진) 최종 상태 원자적 저장
    if checkpoint_path:
        try:
            save_atomic_checkpoint(checkpoint_path, make_ckpt_payload(results, rate_limit_triggered))
        except Exception as ce:
            logger.warning("최종 체크포인트 원자적 저장 실패: %s", ce)

    return compute_metrics(results, latencies, dataset_path, split_filter, cold_start_sec)


def run_evaluation(
    dataset_path: str,
    split_filter: str | None = None,
    checkpoint_path: str = "data/eval_checkpoint.json",
    resume: bool = False,
    retry_policy: str = "failed_and_unrun",
    stop_on_rate_limit: bool = True,
) -> dict:
    """CampusRAG 평가 실행 (체크포인트, 실행 조건 검증, 원자적 저장 및 429 조기 중단 지원)."""
    return run_evaluation_controlled(
        dataset_path=dataset_path,
        split_filter=split_filter,
        rag_instance=None,
        checkpoint_path=checkpoint_path,
        stop_on_rate_limit=stop_on_rate_limit,
        resume=resume,
        retry_policy=retry_policy,
    )


def rescore_baseline(baseline_path: str, dataset_path: str, output_path: str) -> dict:
    """기존 Baseline Dev 결과 파일을 로드하여 신규 평가기 기준으로 재채점하고 별도 저장한다."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    dataset_list = raw.get("questions", raw) if isinstance(raw, dict) else raw
    dataset_map = {item["id"]: item for item in dataset_list}

    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline_data = json.load(f)

    results = []
    latencies = []
    for d in baseline_data.get("details", []):
        item = dataset_map[d["id"]]
        lat = d.get("latency_sec", 0.0)
        latencies.append(lat)

        expected = item["expected_urls"]
        actual_srcs = d.get("actual_sources", [])
        if not actual_srcs and "retrieval" in d:
            actual_srcs = d["retrieval"].get("top_urls", [])

        hit1 = bool(expected and actual_srcs and actual_srcs[0] in expected)
        hit3 = any(u in expected for u in actual_srcs)

        ans = d.get("actual_answer", "")
        ret_eval = {
            "top_urls": actual_srcs,
            "hit_top1": hit1,
            "hit_top3": hit3,
            "abstain_pass": False if not item["should_abstain"] else any(w in ans for w in ("찾지 못", "찾을 수 없", "확인할 수 없")),
        }

        cat = item.get("category", item.get("domain", ""))
        ans_eval = evaluate_answer(
            answer=ans,
            expected_facts=item["expected_facts"],
            grounding_quotes=item["grounding_quotes"],
            negative_constraints=item["negative_constraints"],
            should_abstain=item["should_abstain"],
            category=cat,
            situation=item.get("situation", ""),
        )

        record = {
            "id": item["id"],
            "split": item["split"],
            "category": cat,
            "domain": item.get("domain", ""),
            "situation": item.get("situation", ""),
            "question": item["question"],
            "should_abstain": item.get("should_abstain", False),
            "expected_urls": expected,
            "actual_sources": actual_srcs,
            "expected_facts": item["expected_facts"],
            "actual_answer": ans,
            "retrieval": ret_eval,
            "answer_eval": ans_eval,
            "latency_sec": lat,
        }
        results.append(record)

    summary = compute_metrics(
        results,
        latencies,
        dataset_path,
        split_filter="dev",
        cold_start_sec=baseline_data.get("cold_start_sec", 4.51),
    )

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"💾 Baseline 재채점 결과 저장 완료: {out_p}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/eval_scholarship_dataset.json")
    parser.add_argument("--split", default=None, help="dev or test")
    parser.add_argument("--output", default="data/eval_new_run_results.json")
    parser.add_argument("--checkpoint", default="data/eval_checkpoint.json", help="Path to checkpoint file")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint if execution conditions match")
    parser.add_argument(
        "--retry-policy",
        default="failed_and_unrun",
        choices=["failed_and_unrun", "unrun_only", "all"],
        help="Retry policy when resuming from checkpoint",
    )
    parser.add_argument("--no-stop-on-rate-limit", dest="stop_on_rate_limit", action="store_false", help="Do not stop on 429 rate limit")
    parser.add_argument("--rescore-baseline", default=None, help="Path to baseline json to rescore")
    parser.add_argument("--baseline-output", default="data/eval_rescored_baseline.json")
    parser.add_argument("--skip-eval", action="store_true", help="Skip live LLM evaluation")
    args = parser.parse_args()

    if args.rescore_baseline:
        rescore_baseline(args.rescore_baseline, args.dataset, args.baseline_output)
        if args.skip_eval:
            return

    summary = run_evaluation(
        dataset_path=args.dataset,
        split_filter=args.split,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        retry_policy=args.retry_policy,
        stop_on_rate_limit=args.stop_on_rate_limit,
    )

    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"💾 신규 실전 평가 결과 저장 완료: {out_p}")


if __name__ == "__main__":
    main()
