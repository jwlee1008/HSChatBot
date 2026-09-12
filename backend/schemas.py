"""
CampusRAG 백엔드 API 스키마 (Pydantic 모델)

요청/응답 데이터 구조를 정의한다.
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """RAG 질의 요청 스키마."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="학생의 자연어 질문",
        examples=["수강신청 일정이 언제야?"],
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="검색 결과 반환 개수",
    )


class SourceCard(BaseModel):
    """검색 결과 출처 카드 스키마."""

    title: str = Field(description="공지사항 제목")
    source: str = Field(description="출처 (학교본부, 공과대학 등)")
    category: str = Field(description="분류 (학사, 장학, 행사 등)")
    date: str = Field(description="등록일 (YYYY-MM-DD)")
    url: str = Field(description="원문 링크")


class QueryResponse(BaseModel):
    """RAG 질의 응답 스키마."""

    answer: str = Field(description="LLM이 생성한 요약 답변")
    sources: list[SourceCard] = Field(description="출처 카드 리스트")


class RetrieveResponse(BaseModel):
    """검색 전용 응답 스키마 (LLM 없이 유사도 검색만)."""

    results: list[SourceCard] = Field(description="검색 결과 리스트")
    contents: list[str] = Field(description="검색된 공지 본문 리스트")


class HealthResponse(BaseModel):
    """헬스 체크 응답."""

    status: str = "ok"
    version: str = "1.0.0"
    llm_provider: str = Field(description="현재 LLM 프로바이더")
    doc_count: int = Field(description="적재된 문서 수")
