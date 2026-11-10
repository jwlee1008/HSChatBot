"""Official facts must survive notice recency and long attachment chunk noise."""
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from core.rag import CampusRAG


def chunk(parent, title, body, *, source_type="notice", date="2031-10-01", index=0):
    return Document(
        page_content=f"[학사] {title} (등록일: {date}, 출처: 한성대학교)\n\n{body}",
        metadata={"id": parent, "parent_id": parent, "chunk_id": f"{parent}_c{index}",
                  "url": f"https://www.hansung.ac.kr/{parent}", "title": title,
                  "source_type": source_type, "date": date, "chunk_index": index,
                  "content_status": "text"},
    )


def retrieval(rows, question, top_k=3):
    rag = CampusRAG.__new__(CampusRAG)
    rag.vectorstore = MagicMock()
    rag.vectorstore.similarity_search_with_relevance_scores.return_value = rows
    return rag.retrieve(question, top_k=top_k)


@pytest.mark.parametrize("graduate", [False, True])
def test_named_calendar_and_requested_month_beat_same_year_notices(graduate):
    title = "대학원학사일정" if graduate else "학부학사일정"
    october = chunk("calendar", title,
                    "10월\n2031.10.20(월) ~ 2031.10.25(토)\n중간고사\n"
                    "2031.10.27(월) ~ 2031.10.31(금) 수업평가 중간조사",
                    source_type="guidance", date="", index=5)
    spring = chunk("calendar", title,
                   "4월\n2031.04.21(월) ~ 2031.04.26(토) 중간고사\n"
                   "2031.04.28(월) ~ 2031.05.02(금) 수업평가 중간조사",
                   source_type="guidance", date="", index=2)
    other = chunk("track", "2031학년도 2학기 트랙선택 안내",
                  "2031학년도 2학기 트랙선택 신청기간은 2031.05.01부터 2031.05.20까지입니다. "
                  "학생은 종합정보시스템에서 해당 기간 중 신청해야 하며 기간 이후 변경할 수 없습니다.")
    docs = retrieval([(other, 0.65), (spring, 0.63), (october, 0.45)],
                     f"2031학년도 2학기 {title}에서 10월 중간고사 기간은 언제인가요?")
    assert docs[0].metadata["chunk_id"] == "calendar_c5"
    assert "2031.10.25" in docs[0].page_content
    assert not any(d.metadata["parent_id"] == "track" for d in docs)


def test_dining_menu_and_operating_time_remain_together_over_old_announcement():
    hours = chunk("breakfast", "천원의 아침밥",
                  "위치: 창의관 지하1층\n운영시간: 화~목 09:30~10:30\n"
                  "식단기간: 2031.10.06 ~ 2031.10.12\n"
                  "식단구분 | 2031.10.06 | 2031.10.07 | 2031.10.08 | 2031.10.09",
                  source_type="guidance", date="")
    menu = chunk("breakfast", "천원의 아침밥",
                 "조식 | 등록된 메뉴 없음 | 현미밥 미역국 생선까스 김치 | "
                 "카레라이스 계란국 감자고로케 샐러드 | 제육덮밥 된장국 채소볶음 깍두기",
                 source_type="guidance", date="", index=1)
    announcement = chunk("old-notice", "2031학년도 천원의 아침밥 시행 안내",
                         "재학생에게 아침 식사를 지원하는 사업을 2031.03.10부터 시행합니다. "
                         "화요일부터 목요일까지 선착순으로 운영하니 학생들은 사업 내용과 주의 사항을 확인하세요.",
                         date="2031-03-01")
    docs = retrieval([(announcement, 0.55), (hours, 0.42), (menu, 0.26)],
                     "2031년 10월 8일 천원의 아침밥 메뉴와 운영시간은?")
    assert {d.metadata["chunk_id"] for d in docs} == {"breakfast_c0", "breakfast_c1"}
    assert "09:30~10:30" in "\n".join(d.page_content for d in docs)
    assert "카레라이스" in "\n".join(d.page_content for d in docs)


def test_explicitly_named_form_keeps_current_submission_facts_over_faq_and_ocr():
    form = chunk("leave-form", "일반휴학원",
                 "일반휴학원 작성 시 보호자 확인이 필요합니다. 신청양식은 첨부자료를 참조하세요. "
                 "제출처: 학사운영팀(우촌관 301호). 질병휴학은 진단서를 첨부해야 합니다.",
                 source_type="form", date="2029-02-01")
    faq = chunk("faq", "휴학 신청 방법이 궁금합니다.",
                "휴학하려면 일반휴학원을 작성하여 본인과 보호자 서명을 받고 학사운영팀에 제출합니다. "
                "휴학 사유와 기간을 확인하고 신청하세요. 세부 사항은 해당 양식의 안내를 확인하세요.",
                source_type="faq", date="")
    noisy = chunk("scholarship", "2031학년도 장학금 신청 안내",
                  "서류제출대상자는 가족관계 확인을 위한 필수서류를 제출해야 합니다. "
                  "학생 본인 명의로 신청하고 부모님의 주민등록번호를 확인하여 기재하세요.")
    docs = retrieval([(faq, 0.75), (form, 0.59), (noisy, 0.55)],
                     "일반휴학원 제출처와 보호자 확인 절차를 알려주세요.")
    assert docs[0].metadata["source_type"] == "form"
    assert "학사운영팀(우촌관 301호)" in docs[0].page_content
    assert not any(d.metadata["parent_id"] == "scholarship" for d in docs)


def test_named_scholarship_and_deadline_chunk_beat_other_program_and_consent():
    title = "교외장학금 새빛재단 2031년 꿈나무 장학생 모집 안내"
    deadline = chunk("new-scholarship", title,
                     "[자료: 장학 포스터]\n신청기간: ~ 2031.10.18.(토)\n"
                     "신청서 작성 및 필수서류 구비 후 새빛재단 홈페이지의 온라인 신청폼으로 제출하세요.")
    consent = chunk("new-scholarship", title,
                    "개인정보 수집 및 이용 동의서\n장학 신청 접수, 선발, 지급, 회계 및 법정 의무를 이행하기 위해 "
                    "신청자의 이름, 주소, 학적사항과 가족정보를 수집합니다.", index=10)
    older = chunk("other-scholarship", "새빛재단 2031년 생활지원 장학생 모집 안내",
                  "신청기간: 2031.04.01 ~ 2031.04.09까지. 신청자는 필요한 서류를 홈페이지로 제출하세요. "
                  "지원자격은 소득구간 및 재학 상태를 기준으로 확인하며 자세한 내용은 공고문을 참조하세요.",
                  date="2031-03-30")
    docs = retrieval([(older, 0.63), (consent, 0.61), (deadline, 0.59)],
                     "새빛재단 2031년 꿈나무 장학생은 언제까지 신청하고 어디에 제출하나요?")
    assert docs[0].metadata["parent_id"] == "new-scholarship"
    assert any("2031.10.18" in d.page_content and "신청폼" in d.page_content for d in docs)
    assert not any(d.metadata["parent_id"] == "other-scholarship" for d in docs)


def test_body_date_is_evidence_but_repeated_publication_header_is_not():
    title = "새빛재단 꿈나무 장학생 모집"
    deadline = chunk("notice", title,
                     "신청서는 2031.10.18.(토)에 제출합니다. 제출 경로는 재단 홈페이지의 신청폼입니다. "
                     "신청 전에 지원자격과 필요서류를 확인하고 지정 양식에 따라 작성하세요.", index=1)
    consent = chunk("notice", title,
                    "개인정보 수집 및 이용 동의서. 수집한 개인정보는 장학금 선발과 지급 업무에 사용되며 "
                    "관련 법령에 따라 보관합니다. 수집 목적과 개인정보의 종류를 확인해 주세요.", index=2)
    docs = retrieval([(deadline, 0.55), (consent, 0.55)],
                     "새빛재단 꿈나무 장학생 신청은 언제까지인가요?", top_k=1)
    assert docs[0].metadata["chunk_id"] == "notice_c1"


def test_named_official_source_below_similarity_threshold_is_not_rescued():
    guide = chunk("calendar", "학부학사일정", "2031.10.20 ~ 2031.10.25 중간고사",
                  source_type="guidance", date="")
    assert retrieval([(guide, 0.20)], "2031년 10월 학부학사일정 중간고사 기간") == []


def test_notice_year_policy_remains_when_official_guide_is_not_a_valid_candidate():
    current = chunk("current-notice", "2031학년도 학사일정 안내",
                    "2031학년도 학사일정은 학교 홈페이지의 연간 달력을 확인하세요. "
                    "중간고사와 기말고사는 학기별 일정에 따라 진행되며 세부사항은 별도 안내합니다.")
    past = chunk("past-notice", "2030학년도 학사일정 안내",
                 "2030학년도 학사일정은 학교 홈페이지의 연간 달력을 확인하세요. "
                 "중간고사와 기말고사는 학기별 일정에 따라 진행되며 세부사항은 별도 안내합니다.",
                 date="2030-10-01")
    docs = retrieval([(past, 0.70), (current, 0.45)], "2031학년도 학사일정은?")
    assert docs[0].metadata["parent_id"] == "current-notice"


def test_explicit_historical_notice_request_keeps_notice_policy():
    notice = chunk("historical-notice", "2031년 천원의 아침밥 사업 중단 공지",
                   "2031.06.16부터 하계방학 기간 동안 아침밥 사업을 잠시 중단합니다. "
                   "2031년 2학기에 다시 시행할 예정이며 자세한 재개 일정은 별도 공지를 확인하세요.",
                   date="2031-06-01")
    guide = chunk("breakfast", "천원의 아침밥",
                  "현재 식단 및 식당 위치 안내. 창의관 지하1층에 있으며 화요일부터 목요일에 운영합니다. "
                  "주간 메뉴가 매주 갱신되니 이번 주 식단표를 확인하세요.",
                  source_type="guidance", date="")
    docs = retrieval([(guide, 0.61), (notice, 0.52)],
                     "2031년 천원의 아침밥 사업 중단 공지 내용은?")
    assert docs[0].metadata["parent_id"] == "historical-notice"


def test_date_question_does_not_add_subject_boost_to_off_topic_code_request():
    guide = chunk("calendar", "학부학사일정", "2031.10.20 ~ 2031.10.25 중간고사",
                  source_type="guidance", date="")
    assert retrieval([(guide, 0.32)], "2031년 학사일정 관리하는 파이썬 코드 짜줘") == []


@pytest.mark.parametrize("requested_year", [2029, 2031])
def test_historical_calendar_change_notice_does_not_prefer_current_calendar(requested_year):
    guide = chunk("current-calendar", "학부학사일정",
                  "2031.10.20 ~ 2031.10.25 중간고사. 현재 학부의 연간 학사일정과 "
                  "수업 일정은 이 달력에서 확인할 수 있습니다.", source_type="guidance", date="")
    historical = chunk("historical-calendar", f"{requested_year}년 학사일정 변경 공지",
                       f"{requested_year}.10.14 ~ {requested_year}.10.19 중간고사로 학사일정이 변경되었습니다. "
                       "기존 학사일정과 변경 내용을 확인해주시기 바랍니다.", date=f"{requested_year}-09-30")
    docs = retrieval([(historical, 0.65), (guide, 0.50)], f"{requested_year}년 학사일정 변경 공지 내용은?")
    assert docs[0].metadata["parent_id"] == "historical-calendar"
    assert not any(d.metadata["parent_id"] == "current-calendar" for d in docs)


def test_requested_calendar_year_requires_actual_body_dates():
    current = chunk("current-calendar", "학부학사일정",
                    "2031.10.20 ~ 2031.10.25 중간고사. 학부의 연간 학사일정은 달력에서 확인하세요.",
                    source_type="guidance", date="2029-10-01")
    assert retrieval([(current, 0.65)], "2029년 학부 학사일정 중간고사 기간은?") == []


def test_dining_menu_change_notice_retains_requested_notice_policy():
    guide = chunk("current-dining", "천원의 아침밥",
                  "현재 식단 및 운영시간 안내. 창의관 지하1층에 있으며 화요일부터 목요일에 운영합니다. "
                  "주간 메뉴가 매주 갱신되니 이번 주 식단표를 확인하세요.", source_type="guidance", date="")
    notice = chunk("dining-change", "2029년 천원의 아침밥 식단 변경 공지",
                   "2029.10.08 아침밥 메뉴가 변경되었습니다. 식당 운영시간은 오전 9시부터 10시이며 "
                   "등록된 주간 식단 대신 변경된 메뉴를 제공합니다.", date="2029-10-07")
    docs = retrieval([(guide, 0.61), (notice, 0.52)], "2029년 천원의 아침밥 식단 변경 공지 메뉴는?")
    assert docs[0].metadata["parent_id"] == "dining-change"


def test_term_and_corrected_notice_exclude_stale_sources():
    body = "지원하려는 학생은 신청 기간에 종합정보시스템에서 신청하고 필요서류를 제출해야 합니다."
    corrected = chunk("corrected", "장학금 (정정) 2031년 2학기 우수장학 선발기준", body)
    original = chunk("original", "장학금 2031년 2학기 우수장학 선발기준", body, date="2031-09-01")
    spring = chunk("spring", "장학금 2031년 1학기 우수장학 선발기준", body)
    docs = retrieval([(spring, 0.85), (original, 0.70), (corrected, 0.58)],
                     "2031년 2학기 우수장학 선발기준 알려줘")
    assert [doc.metadata["parent_id"] for doc in docs] == ["corrected"]


def test_compound_policy_query_keeps_one_chunk_per_matched_guide():
    leave = chunk("leave", "휴학", "일반휴학은 평생지도교수 상담과 승인이 필요합니다.", source_type="guidance")
    extension = chunk("leave", "휴학", "일반휴학은 통산 6학기 가능합니다.", source_type="guidance", index=1)
    returning = chunk("return", "복학", "복학 신청 후 등록과 수강신청을 해야 합니다.", source_type="guidance")
    docs = retrieval([(leave, 0.8), (extension, 0.7), (returning, 0.4)],
                     "일반휴학하려면 교수 상담이 필요해? 복학 신청하면 등록도 해야 돼?", top_k=2)
    assert [doc.metadata["parent_id"] for doc in docs] == ["leave", "return"]


def test_query_keeps_full_trace_but_links_only_cited_chunks(monkeypatch):
    rag = CampusRAG.__new__(CampusRAG)
    rag.llm = object()
    wrong = chunk("wrong", "관련 없는 공지", "일부 청크", index=0)
    cited = chunk("correct", "수강신청", "종합정보시스템 > 교무 > 수강신청", source_type="guidance")
    retrieve = MagicMock(return_value=[wrong, cited])
    monkeypatch.setattr(rag, "retrieve", retrieve)
    monkeypatch.setattr(rag, "_invoke_llm_with_error_handling",
                        lambda _: ("교무 메뉴에서 신청하세요.\n[근거 2]", {"status": "success"}))
    result = rag.query("수강신청 어디서 해?", include_retrieved=True)
    retrieve.assert_called_once()
    assert result["answer"] == "교무 메뉴에서 신청하세요."
    assert [item["url"] for item in result["sources"]] == [cited.metadata["url"]]
    assert [item["metadata"]["parent_id"] for item in result["retrieved"]] == ["wrong", "correct"]


@pytest.mark.parametrize("question", [
    "장바구니 과목 지금 잔여석 몇 개야?",
    "내 휴학 신청 승인됐어?",
    "내 성적표 보고 졸업 여부 판정해줘",
])
def test_personal_status_never_uses_public_notices_as_evidence(monkeypatch, question):
    rag = CampusRAG.__new__(CampusRAG)
    retrieve = MagicMock()
    monkeypatch.setattr(rag, "retrieve", retrieve)
    result = rag.query(question, include_retrieved=True)
    retrieve.assert_not_called()
    assert result["status"] == "no_context"
    assert result["sources"] == result["retrieved"] == []
    assert "조회할 수 없습니다" in result["answer"]
