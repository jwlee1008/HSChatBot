"""
backend/routers/schedules.py

CampusMate 개인 일정 CRUD RESTful API 라우터.
모든 엔드포인트는 유효한 Opaque Bearer 세션 토큰을 필요로 하며,
소유자 격리(BOLA/IDOR 방어)를 엄격히 적용한다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status

from backend.auth.dependencies import get_current_user
from backend.db.database import get_db
from backend.schemas import (
    Priority,
    ScheduleCreateRequest,
    ScheduleExtractionRequest,
    ScheduleExtractionResponse,
    ScheduleListResponse,
    SchedulePatchRequest,
    ScheduleResponse,
)
from backend.schedules.extraction import extract_schedule_candidates
from backend.schedules.service import ScheduleService

router = APIRouter(prefix="/api/v1/schedules", tags=["개인 일정"])


@router.post(
    "/extract",
    response_model=ScheduleExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="자연어/공지 일정 후보 추출 (Zero-Auto-Save)",
)
def extract_schedules(
    request: ScheduleExtractionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ScheduleExtractionResponse:
    """자연어 텍스트 또는 공지 본문에서 일정 후보를 추출한다.

    - 세션 인증 필수 (미인증 시 401 반환)
    - Zero-Auto-Save: DB에 직접 저장하지 않는 비영속(Stateless) 분석 엔드포인트
    - 모든 반환 후보는 requires_user_confirmation: True 강제
    """
    return extract_schedule_candidates(
        text=request.text,
        reference_time=request.reference_time,
        source_url=request.source_url,
        source_title=request.source_title,
    )



@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="개인 일정 생성 (사용자 확인 필수)",
)
def create_schedule(
    request: ScheduleCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> ScheduleResponse:
    """새로운 개인 일정을 생성한다.

    - `confirmed: true`가 필수이며 누락 또는 false 시 422 반환
    - 5개 일정 유형별 날짜·일시 계약 및 서울 기준 달력 날짜 일치 검증
    """
    return ScheduleService.create_schedule(db, current_user["id"], request)


@router.get(
    "",
    response_model=ScheduleListResponse,
    status_code=status.HTTP_200_OK,
    summary="개인 일정 목록 및 캘린더 조회 (필터링 및 페이지네이션)",
)
def list_schedules(
    date_from: str | None = Query(default=None, description="조회 시작일 (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="조회 종료일 (YYYY-MM-DD)"),
    is_completed: bool | None = Query(default=None, description="완료 여부 필터"),
    priority: Priority | None = Query(default=None, description="중요도 필터 (HIGH, MEDIUM, LOW)"),
    limit: int = Query(default=50, ge=1, le=100, description="반환 개수 (1~100)"),
    offset: int = Query(default=0, ge=0, description="조회 오프셋"),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> ScheduleListResponse:
    """현재 사용자의 개인 일정 목록을 조회한다.

    - `date_from`과 `date_to`는 둘 다 제공되거나 둘 다 생략되어야 함 (불일치 시 422)
    - 기간 일정 겹침, 마감일, 단일 약속일 모두 정확히 필터링
    - 일정 기준 날짜 오름차순, id 오름차순 정렬
    """
    return ScheduleService.list_schedules(
        db=db,
        user_id=current_user["id"],
        date_from=date_from,
        date_to=date_to,
        is_completed=is_completed,
        priority=priority,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="개인 일정 단건 상세 조회",
)
def get_schedule(
    schedule_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> ScheduleResponse:
    """단건 개인 일정을 조회한다.

    - 타인의 UUID 또는 존재하지 않는 UUID는 동일하게 안전한 404 반환
    """
    return ScheduleService.get_schedule(db, current_user["id"], schedule_id)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="개인 일정 부분 수정 (사용자 확인 필수)",
)
def patch_schedule(
    schedule_id: str,
    request: SchedulePatchRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> ScheduleResponse:
    """개인 일정의 일부 필드를 수정한다.

    - `confirmed: true` 필수
    - 미전송 필드는 기존 값 보존, 명시적 null은 nullable 필드 비우기
    - 필수 기본 필드(title, schedule_kind 등)의 null은 422 거부
    - 최종 병합 상태 전체에 대한 시간 모델 검증 적용
    - 실패 시 DB 변경 없음 (원자적 롤백)
    """
    return ScheduleService.patch_schedule(db, current_user["id"], schedule_id, request)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="개인 일정 삭제",
)
def delete_schedule(
    schedule_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    """개인 일정을 삭제한다.

    - 성공 시 204 No Content 반환
    - 타인의 UUID 또는 존재하지 않는 UUID는 동일하게 안전한 404 반환
    """
    ScheduleService.delete_schedule(db, current_user["id"], schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
