"""
CampusRAG 프롬프트 템플릿 모듈

RAG 파이프라인에서 LLM에 전달할 프롬프트 템플릿을 정의한다.
"""

from langchain_core.prompts import PromptTemplate

# ──────────────────────────────────────────────
# RAG 질의응답 프롬프트
# ──────────────────────────────────────────────
RAG_PROMPT_TEMPLATE = """당신은 한성대학교 학내 공지사항 안내 AI 어시스턴트입니다.
아래에 제공된 공지사항 검색 결과를 바탕으로 학생의 질문에 답변하세요.

## 답변 규칙
1. 검색 결과에 기반하여 2~3문장으로 핵심 내용을 요약하세요.
2. 반드시 관련 공지사항의 제목, 등록일, 출처를 함께 안내하세요.
3. 검색 결과에 없는 내용은 추측하지 말고, "관련 공지를 찾지 못했습니다"라고 답하세요.
4. 친절하고 정확하게 답변하세요.

## 검색된 공지사항
{context}

## 학생 질문
{question}

## 답변"""

RAG_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=RAG_PROMPT_TEMPLATE,
)


def format_retrieved_docs(docs) -> str:
    """검색된 Document 리스트를 프롬프트에 삽입할 텍스트로 포매팅한다."""
    if not docs:
        return "검색 결과가 없습니다."

    formatted = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        entry = (
            f"[공지 {i}]\n"
            f"제목: {meta.get('title', '제목 없음')}\n"
            f"출처: {meta.get('source', '출처 없음')}\n"
            f"등록일: {meta.get('date', '날짜 없음')}\n"
            f"링크: {meta.get('url', '링크 없음')}\n"
            f"내용: {doc.page_content}\n"
        )
        formatted.append(entry)

    return "\n---\n".join(formatted)
