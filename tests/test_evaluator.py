"""
CampusRAG 평가기(scripts/run_eval.py) 자체 회귀 테스트.

검증 항목:
1. 잘못된 날짜 제시 시 실패(FAIL) 처리
2. 신청 마감과 동의 마감 날짜가 뒤바뀐 경우(swapped) 실패 처리
3. 신청 마감과 가구원 동의 마감을 각각 올바르게 설명한 답변은 정상 통과(PASS)
4. 두 마감일이 동일하다고 안내한 경우 실패 처리
5. 자동 판정이 어려운 모호한 답변은 'NEEDS_REVIEW'(원문 대조 필요)로 분류
6. 미기재 정보 및 무관 질문 유보 판정 검증
"""

import pytest
from scripts.run_eval import evaluate_answer, extract_clause_bindings


def test_evaluator_import_preserves_selected_provider():
    import os
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, '-c',
         'import scripts.run_eval as evaluation; assert evaluation.config.LLM_PROVIDER == "gemini"'],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'LLM_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'unused-test-key'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


class TestEvaluator:
    """평가기의 판정 로직 정밀도 및 회귀 검증."""

    def test_both_dates_correct_passes(self):
        """신청 마감(9.9)과 가구원 동의(9.16)를 각각 올바르게 설명한 답변은 통과한다."""
        answer = (
            "2026년 2학기 국가장학금 2차 신청 기간은 2026년 8월 12일(수) 09:00부터 "
            "9월 9일(수) 18:00까지입니다. 참고로 가구원 정보제공 동의 및 서류제출은 "
            "9월 16일(수) 18:00까지 완료해야 합니다."
        )
        res = evaluate_answer(
            answer=answer,
            expected_facts="2026년 8월 12일부터 9월 9일 18시까지",
            grounding_quotes=["'26.8.12.(수) 09시~9.9.(수) 18시"],
            negative_constraints=["9.16", "9월 16일", "2025년"],
            should_abstain=False,
            category="period_apply",
        )
        assert res["status"] == "PASS"
        assert res["score"] == 1.0
        assert res["fact_matched"] is True

    def test_swapped_dates_fails(self):
        """신청 마감일로 가구원 동의 마감일(9.16)을 제시한 경우 실패 처리된다."""
        answer = (
            "2026년 2학기 국가장학금 2차 신청 마감일은 9월 16일 18:00까지입니다. "
            "가구원 동의는 9월 9일까지 해야 합니다."
        )
        res = evaluate_answer(
            answer=answer,
            expected_facts="9월 9일 18시 마감",
            grounding_quotes=["9.9.(수) 18시"],
            negative_constraints=["9.16", "9월 16일"],
            should_abstain=False,
            category="period_apply",
        )
        assert res["status"] == "FAIL"
        assert res["score"] == 0.0
        assert "뒤바뀜" in res["reason"] or "9월 16일" in res["reason"]

    def test_wrong_date_fails(self):
        """전혀 잘못된 날짜(예: 9월 30일)를 제시한 경우 실패 처리된다."""
        answer = "2026년 2학기 국가장학금 2차 신청은 9월 30일 18시까지 신청 가능합니다."
        res = evaluate_answer(
            answer=answer,
            expected_facts="9월 9일 18시 마감",
            grounding_quotes=["9.9.(수) 18시"],
            negative_constraints=["9.16"],
            should_abstain=False,
            category="period_apply",
        )
        assert res["status"] == "FAIL"
        assert res["score"] == 0.0
        assert res["fact_matched"] is False

    def test_period_distinction_identical_fails(self):
        """신청 마감일과 가구원 동의 마감일이 동일하다고 안내하면 실패 처리된다."""
        answer = "국가장학금 신청 마감일과 가구원 동의 마감일은 9월 9일로 동일합니다."
        res = evaluate_answer(
            answer=answer,
            expected_facts="신청 마감은 9월 9일, 동의 마감은 9월 16일로 다름",
            grounding_quotes=["9.9", "9.16"],
            negative_constraints=["마감일이 같다"],
            should_abstain=False,
            category="period_distinction",
        )
        assert res["status"] == "FAIL"
        assert res["score"] == 0.0

    def test_period_distinction_passes(self):
        """신청 마감(9.9)과 가구원 동의 마감(9.16)이 서로 다름을 올바르게 안내하면 통과한다."""
        answer = (
            "아닙니다, 두 마감일은 서로 다릅니다. 국가장학금 신청 마감은 9월 9일 18시까지이며, "
            "가구원 정보제공 동의 및 서류제출 마감은 9월 16일 18시까지입니다."
        )
        res = evaluate_answer(
            answer=answer,
            expected_facts="신청 마감은 9월 9일, 동의 마감은 9월 16일로 다름",
            grounding_quotes=["9.9", "9.16"],
            negative_constraints=["마감일이 같다"],
            should_abstain=False,
            category="period_distinction",
        )
        assert res["status"] == "PASS"
        assert res["score"] == 1.0

    def test_ambiguous_answer_needs_review(self):
        """마감 일자가 명확하지 않고 '중순경' 등으로 모호한 경우 NEEDS_REVIEW로 분류된다."""
        answer = "2026년 2학기 국가장학금 2차 신청은 9월 중순경에 마감될 예정입니다."
        res = evaluate_answer(
            answer=answer,
            expected_facts="9월 9일 18시 마감",
            grounding_quotes=["9.9.(수) 18시"],
            negative_constraints=["9.16"],
            should_abstain=False,
            category="period_apply",
        )
        assert res["status"] == "NEEDS_REVIEW"
        assert res["score"] == 0.5
        assert "원문 대조 필요" in res["reason"]

    def test_missing_info_passes_when_noted(self):
        """공지에 없는 미기재 정보임을 정상 안내하면 통과한다."""
        answer = "해당 공지사항에서는 구체적인 지원 금액에 대해 명시되어 있지 않아 확인할 수 없습니다."
        res = evaluate_answer(
            answer=answer,
            expected_facts="공지에 금액 정보 미기재",
            grounding_quotes=[],
            negative_constraints=["300만원", "500만원"],
            should_abstain=False,
            category="missing_amount",
        )
        assert res["status"] == "PASS"
        assert res["score"] == 1.0

    def test_missing_info_fails_when_hallucinated(self):
        """공지에 없는 정보를 임의 추측하여 단언하면 실패한다."""
        answer = "국가장학금 지원 금액은 최대 500만원까지 지급됩니다."
        res = evaluate_answer(
            answer=answer,
            expected_facts="공지에 금액 정보 미기재",
            grounding_quotes=[],
            negative_constraints=["500만원"],
            should_abstain=False,
            category="missing_amount",
        )
        assert res["status"] == "FAIL"
        assert res["score"] == 0.0

    def test_irrelevant_query_abstain(self):
        """무관 질문에 대해 관련 공지를 찾지 못했다고 유보하면 통과, 환각 답변 시 실패한다."""
        # 1. 정상 유보
        pass_res = evaluate_answer(
            answer="죄송합니다. 질문과 관련된 학내 공지사항을 찾을 수 없습니다.",
            expected_facts="",
            grounding_quotes=[],
            negative_constraints=[],
            should_abstain=True,
            category="irrelevant_query",
        )
        assert pass_res["status"] == "PASS"
        assert pass_res["score"] == 1.0

        # 2. 환각 답변
        fail_res = evaluate_answer(
            answer="내일 서울 날씨는 맑고 최고 기온 25도입니다.",
            expected_facts="",
            grounding_quotes=[],
            negative_constraints=[],
            should_abstain=True,
            category="irrelevant_query",
        )
        assert fail_res["status"] == "FAIL"
        assert fail_res["score"] == 0.0

    def test_api_error_handling(self):
        """Gemini API 장애 발생 시 유보나 임의 실패로 숨기지 않고 API_ERROR로 판정한다."""
        res = evaluate_answer(
            answer="AI 서비스 요청 한도(Rate Limit)에 도달했습니다.",
            expected_facts="신청 마감 9월 9일",
            grounding_quotes=["9월 9일"],
            negative_constraints=[],
            should_abstain=False,
            category="period_apply",
            api_status="api_error",
            api_error="429 RESOURCE_EXHAUSTED",
        )
        assert res["status"] == "API_ERROR"
        assert res["score"] == 0.0
        assert res["fact_matched"] is False
        assert "API 오류" in res["reason"]
