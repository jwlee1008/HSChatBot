"""
backend/schedules/service.py

개인 일정(Personal Schedules) 비즈니스 로직, 유효성 검증 및 데이터베이스 접근 서비스.
5개 일정 유형(ScheduleKind)의 날짜/시각 계약, 서울 기준 달력 날짜 일치, BOLA 격리 및 부분 수정을 전담한다.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from backend.schemas import (
    Priority,
    ScheduleCreateRequest,
    ScheduleKind,
    ScheduleListResponse,
    SchedulePatchRequest,
    ScheduleResponse,
)

SEOUL_TZ = ZoneInfo("Asia/Seoul")
_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NON_NULLABLE_FIELDS = {
    "title",
    "schedule_kind",
    "timezone",
    "priority",
    "is_completed",
}


def validate_date_str(val: Any, field_name: str) -> str:
    """날짜 문자열(YYYY-MM-DD) 형식 및 실제 그레고리력 달력 날짜(윤년 포함)를 엄격히 검증한다."""
    if not isinstance(val, str):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 YYYY-MM-DD 형식의 문자열이어야 합니다.",
        )
    if not _DATE_REGEX.match(val):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 YYYY-MM-DD 형식이어야 합니다: '{val}'",
        )
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드의 날짜가 유효한 달력 날짜가 아닙니다 (윤년 등 확인): '{val}'",
        ) from e
    return val


def validate_and_normalize_datetime_str(val: Any, field_name: str) -> tuple[str, datetime]:
    """일시 문자열을 엄격히 검증하고 UTC 기준 ISO 8601 문자열 및 datetime 객체를 반환한다.

    - naive datetime 거부
    - 날짜 전용 문자열 거부
    - 숫자 epoch 거부
    """
    if not isinstance(val, str):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 ISO 8601 일시 문자열이어야 하며 숫자나 다른 형식을 허용하지 않습니다.",
        )
    if val.isdigit():
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 숫자 epoch 타임스탬프를 허용하지 않습니다.",
        )
    if _DATE_REGEX.match(val):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 날짜 전용 문자열을 허용하지 않습니다. 명시적 일시(ISO 8601)를 입력하세요.",
        )

    try:
        dt = datetime.fromisoformat(val)
    except (ValueError, OverflowError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드의 일시 형식이 올바른 ISO 8601이 아니거나 지원 범위를 벗어났습니다: '{val}'",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드의 일시 파싱 중 오류가 발생했습니다: '{val}'",
        ) from e

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드는 타임존/오프셋이 누락된 naive 일시를 허용하지 않습니다.",
        )

    try:
        dt_utc = dt.astimezone(timezone.utc)
    except OverflowError as e:
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드의 일시를 UTC로 변환하는 중 범위를 초과했습니다.",
        ) from e

    if not (1000 <= dt_utc.year <= 9999):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' 필드의 연도는 1000년부터 9999년 사이여야 합니다: {dt_utc.year}",
        )

    # 마이크로초(소수점 초) 정밀도 온전 보존
    if dt_utc.microsecond != 0:
        iso_utc = f"{dt_utc.strftime('%Y-%m-%dT%H:%M:%S')}.{dt_utc.microsecond:06d}Z"
    else:
        iso_utc = f"{dt_utc.strftime('%Y-%m-%dT%H:%M:%S')}Z"
    return iso_utc, dt_utc


def match_seoul_calendar_date(
    dt_utc: datetime,
    expected_date_str: str,
    dt_field: str,
    date_field: str,
) -> None:
    """UTC 일시를 Asia/Seoul로 변환한 달력 날짜가 대응 날짜 필드와 정확히 일치하는지 검증한다."""
    try:
        dt_seoul = dt_utc.astimezone(SEOUL_TZ)
    except OverflowError as e:
        raise HTTPException(
            status_code=422,
            detail=f"'{dt_field}' 필드를 서울 시간대로 변환하는 중 범위를 초과했습니다.",
        ) from e

    seoul_calendar_date = dt_seoul.strftime("%Y-%m-%d")
    if seoul_calendar_date != expected_date_str:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{dt_field}'의 서울 기준 날짜('{seoul_calendar_date}')가 "
                f"대응하는 '{date_field}'('{expected_date_str}')와 일치하지 않습니다."
            ),
        )


def validate_schedule_state(state: dict[str, Any]) -> dict[str, Any]:
    """일정 전체 상태(생성 시 입력값, 수정 시 병합된 최종 상태)를 5대 유형 계약에 따라 검증 및 정규화한다."""
    title = state.get("title")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 200):
        raise HTTPException(
            status_code=422,
            detail="제목은 앞뒤 공백 제외 1자 이상 200자 이하여야 합니다.",
        )
    normalized_state = dict(state)
    normalized_state["title"] = title.strip()

    kind = normalized_state.get("schedule_kind")
    if isinstance(kind, str):
        try:
            kind = ScheduleKind(kind)
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail=f"유효하지 않은 일정 유형입니다: {kind}",
            ) from e
    elif not isinstance(kind, ScheduleKind):
        raise HTTPException(
            status_code=422,
            detail="일정 유형(schedule_kind)이 올바르지 않습니다.",
        )
    normalized_state["schedule_kind"] = kind.value

    tz = normalized_state.get("timezone", "Asia/Seoul")
    if tz != "Asia/Seoul":
        raise HTTPException(
            status_code=422,
            detail="현재 지원되는 시간대는 'Asia/Seoul'만 가능합니다.",
        )
    normalized_state["timezone"] = tz

    # 날짜 및 일시 파싱/정규화
    s_date = normalized_state.get("start_date")
    e_date = normalized_state.get("end_date")
    s_dt = normalized_state.get("start_datetime")
    e_dt = normalized_state.get("end_datetime")

    parsed_s_date = validate_date_str(s_date, "start_date") if s_date is not None else None
    parsed_e_date = validate_date_str(e_date, "end_date") if e_date is not None else None

    norm_s_dt_str = None
    obj_s_dt = None
    if s_dt is not None:
        norm_s_dt_str, obj_s_dt = validate_and_normalize_datetime_str(s_dt, "start_datetime")

    norm_e_dt_str = None
    obj_e_dt = None
    if e_dt is not None:
        norm_e_dt_str, obj_e_dt = validate_and_normalize_datetime_str(e_dt, "end_datetime")

    normalized_state["start_date"] = parsed_s_date
    normalized_state["end_date"] = parsed_e_date
    normalized_state["start_datetime"] = norm_s_dt_str
    normalized_state["end_datetime"] = norm_e_dt_str

    # 5대 유형별 필수 및 금지 필드 검증
    if kind == ScheduleKind.ALL_DAY_EVENT:
        if parsed_s_date is None or parsed_e_date is None:
            raise HTTPException(
                status_code=422,
                detail="ALL_DAY_EVENT 유형은 start_date와 end_date가 필수입니다.",
            )
        if norm_s_dt_str is not None or norm_e_dt_str is not None:
            raise HTTPException(
                status_code=422,
                detail="ALL_DAY_EVENT 유형은 start_datetime과 end_datetime이 null이어야 합니다.",
            )
        if parsed_s_date > parsed_e_date:
            raise HTTPException(
                status_code=422,
                detail=f"종일 일정의 시작 날짜('{parsed_s_date}')는 종료 날짜('{parsed_e_date}')보다 앞서거나 같아야 합니다.",
            )
        normalized_state["is_all_day"] = 1
        normalized_state["is_time_confirmed"] = 0

    elif kind == ScheduleKind.DATE_ONLY_DEADLINE:
        if parsed_e_date is None:
            raise HTTPException(
                status_code=422,
                detail="DATE_ONLY_DEADLINE 유형은 end_date가 필수입니다.",
            )
        if (
            parsed_s_date is not None
            or norm_s_dt_str is not None
            or norm_e_dt_str is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="DATE_ONLY_DEADLINE 유형은 start_date, start_datetime, end_datetime이 null이어야 합니다.",
            )
        normalized_state["is_all_day"] = 0
        normalized_state["is_time_confirmed"] = 0

    elif kind == ScheduleKind.TIME_CONFIRMED_DEADLINE:
        if parsed_e_date is None or norm_e_dt_str is None or obj_e_dt is None:
            raise HTTPException(
                status_code=422,
                detail="TIME_CONFIRMED_DEADLINE 유형은 end_date와 end_datetime이 필수입니다.",
            )
        if parsed_s_date is not None or norm_s_dt_str is not None:
            raise HTTPException(
                status_code=422,
                detail="TIME_CONFIRMED_DEADLINE 유형은 start_date와 start_datetime이 null이어야 합니다.",
            )
        match_seoul_calendar_date(obj_e_dt, parsed_e_date, "end_datetime", "end_date")
        normalized_state["is_all_day"] = 0
        normalized_state["is_time_confirmed"] = 1

    elif kind == ScheduleKind.TIME_CONFIRMED_EVENT:
        if (
            parsed_s_date is None
            or parsed_e_date is None
            or norm_s_dt_str is None
            or norm_e_dt_str is None
            or obj_s_dt is None
            or obj_e_dt is None
        ):
            raise HTTPException(
                status_code=422,
                detail="TIME_CONFIRMED_EVENT 유형은 start_date, end_date, start_datetime, end_datetime 4개 필드가 모두 필수입니다.",
            )
        match_seoul_calendar_date(obj_s_dt, parsed_s_date, "start_datetime", "start_date")
        match_seoul_calendar_date(obj_e_dt, parsed_e_date, "end_datetime", "end_date")
        if obj_s_dt >= obj_e_dt:
            raise HTTPException(
                status_code=422,
                detail=f"시간 확정 행사의 시작 일시('{norm_s_dt_str}')는 종료 일시('{norm_e_dt_str}')보다 엄격히 앞서야 합니다.",
            )
        if parsed_s_date > parsed_e_date:
            raise HTTPException(
                status_code=422,
                detail=f"시간 확정 행사의 시작 날짜('{parsed_s_date}')는 종료 날짜('{parsed_e_date}')보다 앞서거나 같아야 합니다.",
            )
        normalized_state["is_all_day"] = 0
        normalized_state["is_time_confirmed"] = 1

    elif kind == ScheduleKind.SINGLE_POINT_APPOINTMENT:
        if parsed_s_date is None or norm_s_dt_str is None or obj_s_dt is None:
            raise HTTPException(
                status_code=422,
                detail="SINGLE_POINT_APPOINTMENT 유형은 start_date와 start_datetime이 필수입니다.",
            )
        if parsed_e_date is not None or norm_e_dt_str is not None:
            raise HTTPException(
                status_code=422,
                detail="SINGLE_POINT_APPOINTMENT 유형은 end_date와 end_datetime이 null이어야 합니다.",
            )
        match_seoul_calendar_date(obj_s_dt, parsed_s_date, "start_datetime", "start_date")
        normalized_state["is_all_day"] = 0
        normalized_state["is_time_confirmed"] = 1

    # 우선순위 및 완료 여부 검증
    prio = normalized_state.get("priority", Priority.MEDIUM)
    if isinstance(prio, Priority):
        normalized_state["priority"] = prio.value
    elif isinstance(prio, str) and prio in ("HIGH", "MEDIUM", "LOW"):
        normalized_state["priority"] = prio
    else:
        raise HTTPException(
            status_code=422,
            detail="priority는 'HIGH', 'MEDIUM', 'LOW' 중 하나여야 합니다.",
        )

    is_comp = normalized_state.get("is_completed", False)
    if not isinstance(is_comp, bool):
        raise HTTPException(
            status_code=422,
            detail="is_completed는 불리언(boolean) 값이어야 합니다.",
        )
    normalized_state["is_completed"] = 1 if is_comp else 0

    return normalized_state


def _row_to_response(row: sqlite3.Row) -> ScheduleResponse:
    """SQLite Row 객체를 ScheduleResponse Pydantic 모델로 변환한다."""
    return ScheduleResponse(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"],
        course_name=row["course_name"],
        schedule_kind=ScheduleKind(row["schedule_kind"]),
        is_all_day=bool(row["is_all_day"]),
        is_time_confirmed=bool(row["is_time_confirmed"]),
        start_date=row["start_date"],
        end_date=row["end_date"],
        start_datetime=row["start_datetime"],
        end_datetime=row["end_datetime"],
        timezone=row["timezone"],
        source_url=row["source_url"],
        source_title=row["source_title"],
        extracted_quote=row["extracted_quote"],
        is_completed=bool(row["is_completed"]),
        priority=Priority(row["priority"]),
        user_confirmed_at=row["user_confirmed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ScheduleService:
    """개인 일정 영속 CRUD 및 사용자 격리 서비스."""

    @staticmethod
    def create_schedule(
        db: sqlite3.Connection,
        user_id: str,
        request: ScheduleCreateRequest,
    ) -> ScheduleResponse:
        """새로운 개인 일정을 생성하고 DB에 저장한다."""
        if request.confirmed is not True:
            raise HTTPException(
                status_code=422,
                detail="일정을 저장하려면 confirmed=true가 필수입니다.",
            )

        payload = request.model_dump(exclude={"confirmed"})
        norm_state = validate_schedule_state(payload)

        schedule_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = db
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute(
                """
                INSERT INTO personal_schedules (
                    id, user_id, title, description, course_name,
                    schedule_kind, is_all_day, is_time_confirmed,
                    start_date, end_date, start_datetime, end_datetime,
                    timezone, source_url, source_title, extracted_quote,
                    is_completed, priority, user_confirmed_at,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?
                );
                """,
                (
                    schedule_id,
                    user_id,
                    norm_state["title"],
                    norm_state.get("description"),
                    norm_state.get("course_name"),
                    norm_state["schedule_kind"],
                    norm_state["is_all_day"],
                    norm_state["is_time_confirmed"],
                    norm_state.get("start_date"),
                    norm_state.get("end_date"),
                    norm_state.get("start_datetime"),
                    norm_state.get("end_datetime"),
                    norm_state["timezone"],
                    norm_state.get("source_url"),
                    norm_state.get("source_title"),
                    norm_state.get("extracted_quote"),
                    norm_state["is_completed"],
                    norm_state["priority"],
                    now_iso,  # user_confirmed_at
                    now_iso,  # created_at
                    now_iso,  # updated_at
                ),
            )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        row = conn.execute(
            "SELECT * FROM personal_schedules WHERE id = ? AND user_id = ?;",
            (schedule_id, user_id),
        ).fetchone()
        return _row_to_response(row)

    @staticmethod
    def get_schedule(
        db: sqlite3.Connection,
        user_id: str,
        schedule_id: str,
    ) -> ScheduleResponse:
        """단건 일정을 조회한다 (BOLA 격리: 타인 UUID 또는 미존재 UUID는 404)."""
        row = db.execute(
            "SELECT * FROM personal_schedules WHERE id = ? AND user_id = ?;",
            (schedule_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="일정을 찾을 수 없습니다.",
            )
        return _row_to_response(row)

    @staticmethod
    def list_schedules(
        db: sqlite3.Connection,
        user_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        is_completed: bool | None = None,
        priority: Priority | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ScheduleListResponse:
        """일정 목록을 조회한다 (기간 겹침, 완료 여부, 중요도 필터 및 정렬)."""
        has_from = date_from is not None
        has_to = date_to is not None
        if has_from != has_to:
            raise HTTPException(
                status_code=422,
                detail="date_from과 date_to는 둘 다 제공되거나 둘 다 생략되어야 합니다.",
            )

        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]

        if has_from and has_to:
            assert date_from is not None and date_to is not None
            v_from = validate_date_str(date_from, "date_from")
            v_to = validate_date_str(date_to, "date_to")
            if v_from > v_to:
                raise HTTPException(
                    status_code=422,
                    detail=f"date_from('{v_from}')은 date_to('{v_to}')보다 앞서거나 같아야 합니다.",
                )
            # 기간 겹침 조건: 일정의 시작<=조회종료 AND 일정의 종료>=조회시작
            clauses.append(
                "(COALESCE(start_date, end_date) <= ? AND COALESCE(end_date, start_date) >= ?)"
            )
            params.extend([v_to, v_from])

        if is_completed is not None:
            clauses.append("is_completed = ?")
            params.append(1 if is_completed else 0)

        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority.value)

        where_clause = " AND ".join(clauses)

        # 전체 카운트 조회
        count_sql = f"SELECT COUNT(*) AS total FROM personal_schedules WHERE {where_clause};"
        total = db.execute(count_sql, params).fetchone()["total"]

        # 페이지네이션 및 정렬 쿼리 (기준 날짜 오름차순, id 오름차순)
        items_sql = f"""
            SELECT * FROM personal_schedules
            WHERE {where_clause}
            ORDER BY COALESCE(start_date, end_date) ASC, id ASC
            LIMIT ? OFFSET ?;
        """
        rows = db.execute(items_sql, params + [limit, offset]).fetchall()

        items = [_row_to_response(r) for r in rows]
        return ScheduleListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def patch_schedule(
        db: sqlite3.Connection,
        user_id: str,
        schedule_id: str,
        request: SchedulePatchRequest,
    ) -> ScheduleResponse:
        """일정을 부분 수정한다.

        - confirmed=true 필수
        - confirmed 외에 변경 필드가 0개이면 422
        - non-nullable 필드에 명시적 null 전달 시 422
        - 병합된 최종 상태 전체에 대해 5대 유형 계약 검증 (새 필수 필드 및 이전 금지 필드 null 처리)
        - 실패 시 원자적 롤백 (DB 부분 변경 방지)
        """
        if request.confirmed is not True:
            raise HTTPException(
                status_code=422,
                detail="일정을 수정하려면 confirmed=true가 필수입니다.",
            )

        fields_set = request.model_fields_set - {"confirmed"}
        if not fields_set:
            raise HTTPException(
                status_code=422,
                detail="수정할 필드가 제공되지 않았습니다 (confirmed 외에 최소 1개 이상의 필드가 필요합니다).",
            )

        # non-nullable 필드에 명시적 null 전달 차단
        for field in fields_set:
            if field in _NON_NULLABLE_FIELDS and getattr(request, field) is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{field}' 필드는 null로 설정할 수 없습니다.",
                )

        conn = db
        conn.execute("BEGIN IMMEDIATE;")
        in_tx = True
        try:
            row = conn.execute(
                "SELECT * FROM personal_schedules WHERE id = ? AND user_id = ?;",
                (schedule_id, user_id),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK;")
                in_tx = False
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일정을 찾을 수 없습니다.",
                )

            # 기존 레코드 값으로 초기화한 뒤 전송된 필드만 병합
            candidate_state = {
                "title": row["title"],
                "description": row["description"],
                "course_name": row["course_name"],
                "schedule_kind": row["schedule_kind"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "start_datetime": row["start_datetime"],
                "end_datetime": row["end_datetime"],
                "timezone": row["timezone"],
                "source_url": row["source_url"],
                "source_title": row["source_title"],
                "extracted_quote": row["extracted_quote"],
                "is_completed": bool(row["is_completed"]),
                "priority": row["priority"],
            }

            for field in fields_set:
                candidate_state[field] = getattr(request, field)

            # 최종 상태 전체 검증 및 정규화
            norm_state = validate_schedule_state(candidate_state)

            now_iso = datetime.now(timezone.utc).isoformat()

            cursor = conn.execute(
                """
                UPDATE personal_schedules
                SET title = ?,
                    description = ?,
                    course_name = ?,
                    schedule_kind = ?,
                    is_all_day = ?,
                    is_time_confirmed = ?,
                    start_date = ?,
                    end_date = ?,
                    start_datetime = ?,
                    end_datetime = ?,
                    timezone = ?,
                    source_url = ?,
                    source_title = ?,
                    extracted_quote = ?,
                    is_completed = ?,
                    priority = ?,
                    user_confirmed_at = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?;
                """,
                (
                    norm_state["title"],
                    norm_state.get("description"),
                    norm_state.get("course_name"),
                    norm_state["schedule_kind"],
                    norm_state["is_all_day"],
                    norm_state["is_time_confirmed"],
                    norm_state.get("start_date"),
                    norm_state.get("end_date"),
                    norm_state.get("start_datetime"),
                    norm_state.get("end_datetime"),
                    norm_state["timezone"],
                    norm_state.get("source_url"),
                    norm_state.get("source_title"),
                    norm_state.get("extracted_quote"),
                    norm_state["is_completed"],
                    norm_state["priority"],
                    now_iso,  # user_confirmed_at
                    now_iso,  # updated_at
                    schedule_id,
                    user_id,
                ),
            )
            if cursor.rowcount == 0:
                conn.execute("ROLLBACK;")
                in_tx = False
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일정을 찾을 수 없습니다.",
                )

            updated_row = conn.execute(
                "SELECT * FROM personal_schedules WHERE id = ? AND user_id = ?;",
                (schedule_id, user_id),
            ).fetchone()
            if updated_row is None:
                conn.execute("ROLLBACK;")
                in_tx = False
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일정을 찾을 수 없습니다.",
                )

            conn.execute("COMMIT;")
            in_tx = False
            return _row_to_response(updated_row)
        except Exception:
            if in_tx:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
            raise

    @staticmethod
    def delete_schedule(
        db: sqlite3.Connection,
        user_id: str,
        schedule_id: str,
    ) -> None:
        """일정을 삭제한다 (BOLA 격리: 타인 UUID 또는 미존재 UUID는 404)."""
        conn = db
        conn.execute("BEGIN IMMEDIATE;")
        in_tx = True
        try:
            cursor = conn.execute(
                "DELETE FROM personal_schedules WHERE id = ? AND user_id = ?;",
                (schedule_id, user_id),
            )
            if cursor.rowcount == 0:
                conn.execute("ROLLBACK;")
                in_tx = False
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="일정을 찾을 수 없습니다.",
                )
            conn.execute("COMMIT;")
            in_tx = False
        except Exception:
            if in_tx:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
            raise
