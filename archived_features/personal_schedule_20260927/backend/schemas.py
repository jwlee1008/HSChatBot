"""
CampusRAG 백엔드 API 스키마 (Pydantic 모델)

요청/응답 데이터 구조를 정의한다.
"""

import re
import unicodedata
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


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
    content: str | None = Field(default=None, description="공지 본문 내용 발췌")


class QueryResponse(BaseModel):
    """RAG 질의 응답 스키마."""

    answer: str = Field(description="LLM이 생성한 요약 답변 또는 사용자 안내문")
    sources: list[SourceCard] = Field(description="출처 카드 리스트")
    status: str = Field(
        default="success",
        description="응답 상태: 'success', 'no_context', 'title_only_notice', 'api_error'",
    )
    api_called: bool = Field(default=False, description="실제 LLM API 호출 여부")
    provider: str = Field(default="", description="사용된 LLM 프로바이더")
    model: str = Field(default="", description="사용된 LLM 모델명")
    error_type: str | None = Field(
        default=None,
        description="오류 유형: 'rate_limit', 'service_unavailable', 'auth_error', None (비밀정보/원시 예외 제외)",
    )


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


# ── 계정 및 인증 스키마 (R1-A) ─────────────────


class UserRegisterRequest(BaseModel):
    """회원가입 요청 스키마 (외부 필드 주입 차단)."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="로그인 사용자명 (3~50자)",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="비밀번호 (8~128자)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        s = v.strip()
        if not (3 <= len(s) <= 50):
            raise ValueError("사용자명은 앞뒤 공백 제외 3자 이상 50자 이하여야 합니다.")
        if not _USERNAME_PATTERN.match(s):
            raise ValueError("사용자명은 영문, 숫자, '_', '.', '-' 문자만 사용할 수 있습니다.")
        return s.lower()


class UserLoginRequest(BaseModel):
    """로그인 요청 스키마 (외부 필드 주입 차단)."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="로그인 아이디",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="비밀번호",
    )

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    """공개 사용자 정보 응답 스키마."""

    id: str = Field(description="사용자 고유 UUID")
    username: str = Field(description="사용자명")
    created_at: str = Field(description="가입 일시 (UTC ISO-8601)")


class TokenResponse(BaseModel):
    """세션 토큰 발급 응답 스키마."""

    access_token: str = Field(description="서버 저장형 불투명 세션 토큰")
    token_type: str = Field(default="bearer", description="토큰 타입")
    expires_at: str = Field(description="세션 만료 일시 (UTC ISO-8601)")


# ── 개인 일정 스키마 (R1-B) ─────────────────────────


class ScheduleKind(str, Enum):
    """5대 개인 일정 유형."""

    ALL_DAY_EVENT = "ALL_DAY_EVENT"
    DATE_ONLY_DEADLINE = "DATE_ONLY_DEADLINE"
    TIME_CONFIRMED_DEADLINE = "TIME_CONFIRMED_DEADLINE"
    TIME_CONFIRMED_EVENT = "TIME_CONFIRMED_EVENT"
    SINGLE_POINT_APPOINTMENT = "SINGLE_POINT_APPOINTMENT"


class Priority(str, Enum):
    """일정 중요도."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _validate_title(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if not (1 <= len(s) <= 200):
        raise ValueError("제목은 앞뒤 공백 제외 1자 이상 200자 이하여야 합니다.")
    return s


def _validate_timezone(v: str | None) -> str | None:
    if v is None:
        return None
    if v != "Asia/Seoul":
        raise ValueError("현재 지원되는 시간대는 'Asia/Seoul'만 가능합니다.")
    return v


_HOST_LABEL_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


def _validate_source_url(v: str | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("source_url은 문자열이어야 합니다.")
    if v == "":
        return None
    if len(v) > 2048:
        raise ValueError("source_url은 최대 2,048자까지 허용됩니다.")

    # 파서 정규화/제거 전 원본 문자열의 공백 및 제어문자(탭, CR, LF 등) 차단
    if any(c.isspace() for c in v) or any(unicodedata.category(c).startswith("C") for c in v):
        raise ValueError("source_url에 공백이나 제어문자가 포함될 수 없습니다.")

    try:
        parsed = urlsplit(v)
    except Exception as e:
        raise ValueError(f"유효하지 않은 URL 형식입니다: {e}")

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("source_url은 http 또는 https 프로토콜만 허용됩니다.")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("source_url에 유효한 호스트(host)가 포함되어야 합니다.")

    # 포트 검증 (localhost, IP 분기 조기 return 전에 공통 수행)
    try:
        if ":" in parsed.netloc and not parsed.netloc.endswith("]"):
            port_str = parsed.netloc.rsplit(":", 1)[1]
            if not port_str:
                raise ValueError("포트 번호가 비어있습니다.")
        port = parsed.port
    except ValueError as e:
        raise ValueError(f"source_url의 포트 번호가 올바르지 않습니다: {e}")

    if port is not None and not (1 <= port <= 65535):
        raise ValueError(f"source_url의 포트 번호는 1부터 65535 사이여야 합니다: {port}")

    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return v

    labels = hostname.split(".")
    if len(labels) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in labels):
        return v

    if len(labels) < 2:
        raise ValueError(f"source_url 호스트가 올바르지 않습니다: '{hostname}'")

    for label in labels:
        if not label or not _HOST_LABEL_REGEX.match(label):
            raise ValueError(f"source_url 호스트가 올바르지 않습니다: '{hostname}'")

    return v


class ScheduleCreateRequest(BaseModel):
    """일정 생성 요청 스키마 (외부 필드 주입 차단, confirmed 필수)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="일정 제목 (1~200자)")
    description: str | None = Field(default=None, max_length=5000, description="상세 설명")
    course_name: str | None = Field(default=None, max_length=100, description="관련 교과목명")
    schedule_kind: ScheduleKind = Field(..., description="5개 일정 유형 중 하나")
    start_date: str | None = Field(default=None, description="시작 날짜 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="종료 날짜 (YYYY-MM-DD)")
    start_datetime: str | None = Field(default=None, description="시작 일시 (ISO 8601 with tz/offset)")
    end_datetime: str | None = Field(default=None, description="종료 일시 (ISO 8601 with tz/offset)")
    timezone: str = Field(default="Asia/Seoul", description="시간대 (기본 및 유일 지원: Asia/Seoul)")
    source_url: str | None = Field(default=None, description="출처 URL")
    source_title: str | None = Field(default=None, max_length=500, description="출처 공지 제목")
    extracted_quote: str | None = Field(default=None, max_length=5000, description="근거 원문 발췌문")
    is_completed: StrictBool = Field(default=False, description="완료 여부")
    priority: Priority = Field(default=Priority.MEDIUM, description="중요도")
    confirmed: StrictBool = Field(..., description="사용자 확인 여부 (반드시 true)")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        res = _validate_title(v)
        if res is None:
            raise ValueError("제목은 비어 있을 수 없습니다.")
        return res

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        res = _validate_timezone(v)
        if res is None:
            raise ValueError("시간대는 비어 있을 수 없습니다.")
        return res

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        return _validate_source_url(v)

    @field_validator("confirmed")
    @classmethod
    def validate_confirmed(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("일정 저장을 위해서는 confirmed 필드가 명시적으로 true여야 합니다.")
        return True


class SchedulePatchRequest(BaseModel):
    """일정 부분 수정 요청 스키마 (외부 필드 주입 차단, confirmed 필수)."""

    model_config = ConfigDict(extra="forbid")

    confirmed: StrictBool = Field(..., description="사용자 확인 여부 (반드시 true)")
    title: str | None = Field(default=None, description="일정 제목 (1~200자)")
    description: str | None = Field(default=None, max_length=5000, description="상세 설명")
    course_name: str | None = Field(default=None, max_length=100, description="관련 교과목명")
    schedule_kind: ScheduleKind | None = Field(default=None, description="일정 유형")
    start_date: str | None = Field(default=None, description="시작 날짜 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="종료 날짜 (YYYY-MM-DD)")
    start_datetime: str | None = Field(default=None, description="시작 일시 (ISO 8601 with tz/offset)")
    end_datetime: str | None = Field(default=None, description="종료 일시 (ISO 8601 with tz/offset)")
    timezone: str | None = Field(default=None, description="시간대 (Asia/Seoul)")
    source_url: str | None = Field(default=None, description="출처 URL")
    source_title: str | None = Field(default=None, max_length=500, description="출처 공지 제목")
    extracted_quote: str | None = Field(default=None, max_length=5000, description="근거 원문 발췌문")
    is_completed: StrictBool | None = Field(default=None, description="완료 여부")
    priority: Priority | None = Field(default=None, description="중요도")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        return _validate_title(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        return _validate_timezone(v)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        return _validate_source_url(v)

    @field_validator("confirmed")
    @classmethod
    def validate_confirmed(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("일정 수정을 위해서는 confirmed 필드가 명시적으로 true여야 합니다.")
        return True


class ScheduleResponse(BaseModel):
    """일정 단건 응답 스키마."""

    id: str = Field(description="일정 고유 UUID")
    user_id: str = Field(description="소유자 사용자 ID")
    title: str = Field(description="일정 제목")
    description: str | None = Field(default=None, description="일정 상세 설명")
    course_name: str | None = Field(default=None, description="관련 교과목명")
    schedule_kind: ScheduleKind = Field(description="일정 세부 유형")
    is_all_day: bool = Field(description="종일 일정 여부")
    is_time_confirmed: bool = Field(description="시간 확정 일정 여부")
    start_date: str | None = Field(default=None, description="시작 날짜 (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="종료 날짜 (YYYY-MM-DD)")
    start_datetime: str | None = Field(default=None, description="시작 일시 (UTC ISO-8601)")
    end_datetime: str | None = Field(default=None, description="종료 일시 (UTC ISO-8601)")
    timezone: str = Field(default="Asia/Seoul", description="기준 시간대")
    source_url: str | None = Field(default=None, description="출처 공지 URL")
    source_title: str | None = Field(default=None, description="출처 공지 제목")
    extracted_quote: str | None = Field(default=None, description="근거 원문 발췌문")
    is_completed: bool = Field(default=False, description="완료 여부")
    priority: Priority = Field(default=Priority.MEDIUM, description="중요도 (HIGH, MEDIUM, LOW)")
    user_confirmed_at: str = Field(description="사용자 확인 일시 (UTC ISO-8601)")
    created_at: str = Field(description="생성 일시 (UTC ISO-8601)")
    updated_at: str = Field(description="수정 일시 (UTC ISO-8601)")


class ScheduleListResponse(BaseModel):
    """일정 목록 응답 스키마."""

    items: list[ScheduleResponse] = Field(description="일정 목록")
    total: int = Field(description="조건에 맞는 전체 일정 개수")
    limit: int = Field(description="페이지 크기")
    offset: int = Field(description="오프셋")


# ── 일정 추출 스키마 (R2: Zero-Auto-Save) ─────────────────

ScheduleCandidateKind = Literal[
    "TIME_CONFIRMED_EVENT",
    "ALL_DAY_EVENT",
    "DEADLINE_WITH_TIME",
    "DATE_ONLY_DEADLINE",
    "PERIOD_SCHEDULE",
]


class ScheduleCandidate(BaseModel):
    """자연어/공지에서 추출된 일정 후보 (저장 전 사용자 확인 필수)."""

    title: str = Field(description="추출된 일정 제목")
    schedule_kind: ScheduleCandidateKind = Field(
        default="TIME_CONFIRMED_EVENT",
        description="추출된 일정 유형",
    )
    start_date: str | None = Field(default=None, description="시작 날짜 (YYYY-MM-DD 또는 ISO 문자열)")
    end_date: str | None = Field(default=None, description="종료 날짜 (YYYY-MM-DD 또는 ISO 문자열)")
    start_datetime: str | None = Field(default=None, description="시작 일시 (ISO 8601 with tz)")
    end_datetime: str | None = Field(default=None, description="종료 일시 (ISO 8601 with tz)")
    extracted_date: str | None = Field(default=None, description="자정 등 경계 모호 시 추출된 기준 날짜")
    is_all_day: bool = Field(default=False, description="종일 일정 여부")
    is_time_confirmed: bool = Field(default=True, description="시간 확정 여부")
    unconfirmed_fields: list[str] = Field(default_factory=list, description="미확정 필드 목록")
    is_ambiguous: bool = Field(default=False, description="정보 모호성 여부")
    ambiguity_reason: str | None = Field(default=None, description="모호성 사유")
    requires_user_confirmation: StrictBool = Field(
        default=True,
        description="사용자 확인 필수 여부 (반드시 True)",
    )
    source_quote: str = Field(description="일정 추출 근거 원문 발췌문")
    source_quotes: list[str] | None = Field(default=None, description="복수 문장 원문 발췌문 리스트")
    interpretation_options: list[str] | None = Field(default=None, description="모호 시 해석 가능한 타임스탬프 선택지")
    action: Literal["create", "cancel"] = Field(default="create", description="일정 생성 또는 취소 제안")
    is_cancellation: bool = Field(default=False, description="취소 공지 여부")

    @field_validator("requires_user_confirmation")
    @classmethod
    def validate_confirmation(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("모든 일정 후보는 반드시 requires_user_confirmation이 true여야 합니다.")
        return True


class ScheduleExtractionRequest(BaseModel):
    """자연어/공지 일정 추출 요청 스키마."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="추출 대상 자연어 텍스트 또는 공지 본문")
    source_title: str | None = Field(default=None, description="출처 공지 제목")
    reference_time: str | None = Field(
        default=None,
        description="기준 일시 (ISO-8601 문자열, 기본값: 2026-09-23T15:00:00+09:00)",
    )
    source_url: str | None = Field(default=None, description="출처 URL")

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("텍스트는 공백 제외 최소 1자 이상이어야 합니다.")
        return s

    @field_validator("source_title")
    @classmethod
    def validate_source_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        return _validate_source_url(v)

    @field_validator("reference_time")
    @classmethod
    def validate_reference_time(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        try:
            from datetime import datetime

            datetime.fromisoformat(s)
        except Exception as e:
            raise ValueError(f"reference_time은 올바른 ISO 8601 형식이어야 합니다: {e}")
        return s


class ScheduleExtractionResponse(BaseModel):
    """자연어/공지 일정 추출 응답 스키마 (비영속/Zero-Auto-Save)."""

    candidates: list[ScheduleCandidate] = Field(
        default_factory=list,
        description="추출된 일정 후보 목록",
    )
    requires_user_confirmation: bool = Field(
        default=True,
        description="사용자 확인 필요 여부 (후보가 0건인 경우 false)",
    )
    total_candidates: int = Field(
        default=0,
        description="추출된 후보 수",
    )

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            candidates = data.get("candidates", [])
            if "total_candidates" not in data:
                data["total_candidates"] = len(candidates)
            if "requires_user_confirmation" not in data:
                data["requires_user_confirmation"] = len(candidates) > 0
        return data

