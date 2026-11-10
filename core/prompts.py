"""
CampusRAG 프롬프트 템플릿 모듈

RAG 파이프라인에서 LLM에 전달할 프롬프트 템플릿을 정의한다.
"""

import re

from langchain_core.prompts import PromptTemplate

# ──────────────────────────────────────────────
# RAG 질의응답 프롬프트
# ──────────────────────────────────────────────
RAG_PROMPT_TEMPLATE = """한성대학교 학생 질문에 아래 자료만 사용해 한국어로 답하세요.

## 필수 답변 규칙
1. 바로 답을 쓰세요. 질문이 여러 부분이면 각 부분에 답하세요. 메뉴 경로는 하위 메뉴까지, 마감은 명시된 시각까지 쓰세요.
2. 질문과 연도, 학기, 차수, 대상이 맞는 자료를 사용하세요. 등록일을 행사 날짜로 쓰지 마세요. 제목과 본문 일정이 다르면 본문을 따르고 차이를 밝히세요. 정정 공지를 우선하세요.
3. 질문에 해당하는 자격과 제외 조건을 함께 쓰세요. 신청과 서류 제출 등 서로 다른 절차와 마감을 구분하세요.
4. 본문에 없는 숫자나 조건을 추측하지 마세요. 일부만 확인되면 그 부분을 답하고 나머지는 확인할 수 없다고 밝히세요. 개인 신청 상태, 계정 정보, 실시간 잔여석을 확인한 것처럼 답하지 마세요.
5. 뒷받침하는 자료가 하나도 없으면 "관련 공지를 찾지 못했습니다"라고만 답하세요.
6. 답변에 사용한 자료 번호만 마지막 줄에 [근거 1] 또는 [근거 1, 2] 형식으로 적으세요. 번호는 아래 [공지 N]의 N입니다.

## 검색된 공지사항
{context}

## 학생 질문
{question}

## 답변"""

RAG_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=RAG_PROMPT_TEMPLATE,
)


def format_retrieved_docs(docs, max_chars_per_doc: int | None = None) -> str:
    """검색된 Document 리스트를 프롬프트에 삽입할 텍스트로 포매팅한다."""
    if not docs:
        return "검색 결과가 없습니다."

    formatted = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        content = doc.page_content or ""
        if meta.get("source_type") == "guidance" and meta.get("title") in {"학부학사일정", "대학원학사일정"}:
            date = r"\d{4}\.\d{1,2}\.\d{1,2}\([^\n)]+\)"
            content = re.sub(rf"(?m)^({date})(?:\n~\n({date}))?\n([^~\n][^\n]*)",
                             lambda m: f"{m[1]} ~ {m[2]} {m[3]}" if m[2] else f"{m[1]} {m[3]}", content)
        if max_chars_per_doc and len(content) > max_chars_per_doc:
            content = content[:max_chars_per_doc] + "..."
        entry = (
            f"[공지 {i}]\n"
            f"제목: {meta.get('title', '제목 없음')}\n"
            f"출처: {meta.get('source', '출처 없음')}\n"
            f"등록일: {meta.get('date', '날짜 없음')}\n"
            f"링크: {meta.get('url', '링크 없음')}\n"
            f"본문 상태: {meta.get('content_status', 'text')}\n"
            f"내용: {content}\n"
        )
        formatted.append(entry)

    return "\n---\n".join(formatted)
