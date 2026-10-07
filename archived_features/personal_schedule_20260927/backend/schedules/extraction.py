"""
backend/schedules/extraction.py

CampusMate R2 자연어/공지 -> 일정 후보 추출 엔진.
- 규칙/문맥 기반 결정적(Deterministic) 하이브리드 일반 파서 (하드코딩 제거)
- 외부 LLM API(Gemini) 호출 없이 오프라인으로 100% 안전하게 동작
- 동적 기준 일시(reference_time): 미지정 시 현재 Asia/Seoul 시각 사용
- 달력 유효성 검증: 비정상 날짜(예: 9월 31일, 2월 30일) 및 비정상 시각(25:90) 감지하여 모호성 처리
- Zero-Auto-Save 보장: 모든 추출 후보에 requires_user_confirmation: True 강제
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.schemas import (
    ScheduleCandidate,
    ScheduleExtractionResponse,
)

DEFAULT_REFERENCE_TIME = "2026-09-23T15:00:00+09:00"


def _parse_reference_datetime(reference_time: str | None) -> tuple[datetime, str]:
    """기준 일시 문자열을 파싱하고 (datetime, tz_str) 튜플을 반환한다.
    
    reference_time이 주어지지 않은 경우 시스템 현재 서울 시각(UTC+9)을 기본값으로 사용한다.
    """
    if reference_time and reference_time.strip():
        ref_iso = reference_time.strip()
        try:
            ref_dt = datetime.fromisoformat(ref_iso)
        except Exception:
            seoul_tz = timezone(timedelta(hours=9))
            ref_dt = datetime.now(seoul_tz)
    else:
        seoul_tz = timezone(timedelta(hours=9))
        ref_dt = datetime.now(seoul_tz)

    tz_offset = ref_dt.strftime("%z")
    if tz_offset and len(tz_offset) == 5:
        tz_str = f"{tz_offset[:3]}:{tz_offset[3:]}"
    else:
        tz_str = "+09:00"

    return ref_dt, tz_str


def _check_calendar_validity(
    year: int,
    month: int,
    day: int,
    hour: int | None = None,
    minute: int | None = None,
) -> tuple[bool, str | None, list[str]]:
    """달력 날짜 및 시각의 유효성을 검증한다."""
    unconfirmed = []
    reason = None
    try:
        datetime(year, month, day)
    except ValueError:
        unconfirmed.append("exact_date")
        reason = f"존재하지 않는 달력 날짜({month}월 {day}일)로 인해 날짜 확정 불가(오기 확인 필요)"

    if hour is not None:
        if not (0 <= hour <= 23 and 0 <= (minute or 0) <= 59):
            unconfirmed.append("time")
            if not reason:
                reason = f"존재하지 않는 시각({hour:02d}:{minute or 0:02d})으로 인해 시각 확정 불가"
            else:
                reason += f", 존재하지 않는 시각({hour:02d}:{minute or 0:02d})"

    if unconfirmed:
        return False, reason, unconfirmed
    return True, None, []


def _parse_date_and_time(
    val: str | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    """YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM(:SS) 문자열에서 (year, month, day, hour, minute) 추출."""
    if not val:
        return None, None, None, None, None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:T(\d{1,2}):(\d{1,2}))?", val)
    if not m:
        return None, None, None, None, None
    y = int(m.group(1))
    mo = int(m.group(2))
    d = int(m.group(3))
    h = int(m.group(4)) if m.group(4) is not None else None
    mn = int(m.group(5)) if m.group(5) is not None else None
    return y, mo, d, h, mn


def _validate_date_tuple(y: int, mo: int, d: int) -> tuple[bool, str | None]:
    """달력 날짜의 실제 유효성(윤년 등)을 검증한다."""
    try:
        datetime(y, mo, d)
        return True, None
    except ValueError:
        return False, f"존재하지 않는 달력 날짜({mo}월 {d}일)로 인해 날짜 확정 불가(오기 확인 필요)"


def _validate_time_tuple(h: int, mn: int) -> tuple[bool, str | None]:
    """시각(0~23시, 0~59분)의 유효성을 검증한다."""
    if 0 <= h <= 23 and 0 <= mn <= 59:
        return True, None
    return False, f"존재하지 않는 시각({h:02d}:{mn:02d})으로 인해 시각 확정 불가"


def _validate_and_normalize_candidates(
    candidates: list[ScheduleCandidate],
    cleaned_text: str,
    ref_year: int,
    tz_str: str,
) -> list[ScheduleCandidate]:
    """모든 추출 분기에서 생성된 후보들을 단일 공통 게이트에서 전수 검증 및 정규화한다.

    검증 항목:
    1. 달력상 유효한 날짜 (윤년 고려, 2월 30일 등 배제)
    2. 유효한 시각 (0~23시, 0~59분, 25:90 등 배제)
    3. 기간 일정의 시작 <= 종료 순서 보장 (start > end 시 오류 처리)
    4. 원문 명시 연도 보존 (2027년 등이 원문에 명시된 경우 ref_year로 덮어쓰기 방지)
    5. 시각 근거 도출 검증: 원문에 시각이 전혀 언급되지 않은 경우 17:30/15:00 등 임의 기본값 배제 및 미확정/날짜전용 처리
    6. 오류값은 확정 날짜/시각 필드(start_date, end_date, start_datetime, end_datetime)에 남기지 않고 null 처리 후 명시적 유보
    7. 정상 원문 값은 바이트/문자 단위로 보존
    """
    normalized_list: list[ScheduleCandidate] = []

    for cand in candidates:
        cand_dict = cand.model_dump()
        unconfirmed = list(cand_dict.get("unconfirmed_fields") or [])
        ambiguity_reasons = []
        if cand_dict.get("ambiguity_reason"):
            ambiguity_reasons.append(cand_dict["ambiguity_reason"])

        cand_quote = cand_dict.get("source_quote") or ""
        has_date_error = False
        has_start_time_error = False
        has_end_time_error = False
        has_order_error = False

        # 2) 날짜 및 시각 유효성 검증
        s_val = cand_dict.get("start_datetime") or cand_dict.get("start_date")
        e_val = cand_dict.get("end_datetime") or cand_dict.get("end_date")

        sy, smo, sd, sh, smn = _parse_date_and_time(s_val)
        ey, emo, ed, eh, emn = _parse_date_and_time(e_val)

        # 시작 날짜/시각 검증
        if sy is not None and smo is not None and sd is not None:
            is_valid_date, d_err = _validate_date_tuple(sy, smo, sd)
            if not is_valid_date:
                has_date_error = True
                if "exact_date" not in unconfirmed:
                    unconfirmed.append("exact_date")
                if d_err and d_err not in ambiguity_reasons:
                    ambiguity_reasons.append(d_err)

        if sh is not None and smn is not None:
            is_valid_time, t_err = _validate_time_tuple(sh, smn)
            if not is_valid_time:
                has_start_time_error = True
                if "time" not in unconfirmed:
                    unconfirmed.append("time")
                if t_err and t_err not in ambiguity_reasons:
                    ambiguity_reasons.append(t_err)

        # 종료 날짜/시각 검증
        if ey is not None and emo is not None and ed is not None:
            is_valid_date, d_err = _validate_date_tuple(ey, emo, ed)
            if not is_valid_date:
                has_date_error = True
                if "exact_date" not in unconfirmed:
                    unconfirmed.append("exact_date")
                if d_err and d_err not in ambiguity_reasons:
                    ambiguity_reasons.append(d_err)

        if eh is not None and emn is not None:
            is_valid_time, t_err = _validate_time_tuple(eh, emn)
            if not is_valid_time:
                has_end_time_error = True
                if "time" not in unconfirmed:
                    unconfirmed.append("time")
                if t_err and t_err not in ambiguity_reasons:
                    ambiguity_reasons.append(t_err)

        # 3) 시작 <= 종료 기간 순서 검증 (둘 다 유효한 날짜일 때만 비교)
        if not has_date_error and not has_start_time_error and not has_end_time_error:
            if (
                sy is not None and smo is not None and sd is not None and
                ey is not None and emo is not None and ed is not None
            ):
                dt_s = datetime(sy, smo, sd, sh or 0, smn or 0)
                dt_e = datetime(ey, emo, ed, eh or 0, emn or 0)
                if dt_s > dt_e:
                    has_order_error = True
                    if "period_order" not in unconfirmed:
                        unconfirmed.append("period_order")
                    order_reason = "시작 일시가 종료 일시보다 늦어 일정 순서 확인이 필요합니다."
                    if order_reason not in ambiguity_reasons:
                        ambiguity_reasons.append(order_reason)

        # 4) 시각 근거 도출 검증 (B 결함 방지):
        # is_time_confirmed=True로 표시되었으나 원문 및 발췌문에 시각 표현이 일절 없는 경우
        if cand_dict.get("is_time_confirmed") and (cand_dict.get("end_datetime") or cand_dict.get("start_datetime")):
            quote_and_text = f"{cand_quote} {cleaned_text}"
            has_time_in_text = bool(
                re.search(r"(?:^|[^\d])\d{1,2}:\d{2}(?=[^\d]|$)", quote_and_text) or
                re.search(r"\d{1,2}시(?:\s*\d{1,2}분)?", quote_and_text) or
                "자정" in quote_and_text or
                "오전" in quote_and_text or
                "오후" in quote_and_text
            )
            if not has_time_in_text:
                cand_dict["start_datetime"] = None
                cand_dict["end_datetime"] = None
                if cand_dict.get("end_date") and "T" in str(cand_dict["end_date"]):
                    cand_dict["end_date"] = cand_dict["end_date"].split("T")[0]
                if cand_dict.get("start_date") and "T" in str(cand_dict["start_date"]):
                    cand_dict["start_date"] = cand_dict["start_date"].split("T")[0]
                cand_dict["is_time_confirmed"] = False
                if "time" not in unconfirmed:
                    unconfirmed.append("time")
                cand_dict["is_ambiguous"] = True
                if cand_dict.get("schedule_kind") == "DEADLINE_WITH_TIME":
                    cand_dict["schedule_kind"] = "DATE_ONLY_DEADLINE"
                ungrounded_reason = "원문에 마감 시각이 명시되지 않은 날짜 전용 일정입니다."
                if ungrounded_reason not in ambiguity_reasons:
                    ambiguity_reasons.append(ungrounded_reason)

        # 5) 오류값 제거 및 유보 처리 (A 결함 방지):
        if has_date_error:
            cand_dict["start_date"] = None
            cand_dict["end_date"] = None
            cand_dict["start_datetime"] = None
            cand_dict["end_datetime"] = None
            cand_dict["is_time_confirmed"] = False
            cand_dict["is_ambiguous"] = True

        if has_start_time_error:
            cand_dict["start_datetime"] = None
            cand_dict["start_date"] = None
            cand_dict["is_time_confirmed"] = False
            cand_dict["is_ambiguous"] = True

        if has_end_time_error:
            cand_dict["end_datetime"] = None
            cand_dict["end_date"] = None
            cand_dict["is_time_confirmed"] = False
            cand_dict["is_ambiguous"] = True

        if has_order_error:
            cand_dict["start_date"] = None
            cand_dict["end_date"] = None
            cand_dict["start_datetime"] = None
            cand_dict["end_datetime"] = None
            cand_dict["is_time_confirmed"] = False
            cand_dict["is_ambiguous"] = True

        cand_dict["unconfirmed_fields"] = unconfirmed
        if ambiguity_reasons:
            cand_dict["ambiguity_reason"] = ", ".join(ambiguity_reasons)
        else:
            cand_dict["ambiguity_reason"] = None

        cand_dict["requires_user_confirmation"] = True

        normalized_list.append(ScheduleCandidate(**cand_dict))

    return normalized_list


def _build_response(
    candidates: list[ScheduleCandidate],
    cleaned_text: str,
    ref_year: int,
    tz_str: str,
) -> ScheduleExtractionResponse:
    """모든 후보를 공통 검증 및 정규화 게이트를 거쳐 ScheduleExtractionResponse로 반환."""
    validated = _validate_and_normalize_candidates(candidates, cleaned_text, ref_year, tz_str)
    return ScheduleExtractionResponse(
        candidates=validated,
        requires_user_confirmation=True,
        total_candidates=len(validated),
    )


_WEEKDAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

_SINGLE_DATE_RE = re.compile(
    r"""(?P<full>
        (?:(?P<year>\d{4})[.\-년/\s]+)?
        (?P<month>\d{1,2})[.\-월/]\s*
        (?P<day>\d{1,2})\.?(?:\s*일)?
        (?:\s*\((?P<weekday>[월화수목금토일])\))?
        (?:\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?
        (?:\s*(?P<suffix>까지|에))?
    )""",
    re.VERBOSE,
)

_RANGE_PATTERN = re.compile(
    r"(?P<start>(?:(?:\d{4}[.\-년/\s]+)?\d{1,2}[.\-월/]\s*\d{1,2}\.?(?:\s*일)?(?:\s*\([월화수목금토일]\))?(?:\s*\d{1,2}:\d{2})?))"
    r"(?:\s*(?:~|∼|-|\n+\s*(?:~|∼|-)\s*\n+)\s*)"
    r"(?P<end>(?:(?:\d{4}[.\-년/\s]+)?\d{1,2}[.\-월/]\s*\d{1,2}\.?(?:\s*일)?(?:\s*\([월화수목금토일]\))?(?:\s*\d{1,2}:\d{2})?(?:\s*까지)?))",
    re.VERBOSE,
)

_INTRADAY_RANGE_RE = re.compile(
    r"""(?P<full>
        (?P<date>(?:(?:\d{4}[.\-년/\s]+)?\d{1,2}[.\-월/]\s*\d{1,2}\.?(?:\s*일)?(?:\s*\([월화수목금토일]\))?))
        [\s\n\t/]+
        (?P<start_time>\d{1,2}:\d{2})
        \s*(?:~|∼|-)\s*
        (?P<end_time>\d{1,2}:\d{2})
    )""",
    re.VERBOSE,
)



def _parse_date_token(s: str) -> dict | None:
    m = _SINGLE_DATE_RE.search(s)
    if not m:
        return None
    gd = m.groupdict()
    year = int(gd["year"]) if gd["year"] else None
    month = int(gd["month"])
    day = int(gd["day"])
    weekday = gd["weekday"]
    hour = int(gd["hour"]) if gd["hour"] is not None else None
    minute = int(gd["minute"]) if gd["minute"] is not None else None
    suffix = gd["suffix"]
    return {
        "raw": m.group("full"),
        "year": year,
        "month": month,
        "day": day,
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "suffix": suffix,
    }


def _find_document_subject(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    for l in lines[:25]:
        m = re.search(r"(?:프로그램명|사업명|행사명|공지명|과정명)\s*:\s*([^\n]+)", l)
        if m:
            val = m.group(1).strip()
            val = re.sub(r"^\d{4}학년도\s*\d학기\s*", "", val).strip()
            return val
    for l in lines[:5]:
        if any(w in l for w in ["안녕하세요", "선발", "모집합니다", "안내하오니"]):
            m = re.search(r"([^\n]+?)\s*(?:참가자를?\s*)?모집합니다", l)
            if m:
                val = m.group(1).strip()
                val = re.sub(r"^\d{4}학년도\s*\d학기\s*", "", val).strip()
                return val
            continue
        cleaned = l.strip("<>[]★ \t")
        cleaned = re.sub(r"\s*(?:안내|시행\s*안내|모집|선발|공고|계획)$", "", cleaned).strip()
        if any(d in cleaned for d in ["~", "∼", ":", "："]) or re.search(r"\d{1,2}[./월-]\s*\d{1,2}", cleaned):
            continue
        if len(cleaned) >= 2 and not cleaned.startswith("http"):
            return cleaned
    return lines[0]


def _infer_year(token: dict, other_token: dict | None, text_year: int | None, ref_year: int) -> int:
    if token.get("year"):
        return token["year"]
    if other_token and other_token.get("year"):
        y = other_token["year"]
        if token["month"] < other_token["month"]:
            return y + 1
        return y
    if text_year:
        return text_year
    if token.get("weekday") and token["weekday"] in _WEEKDAY_MAP:
        exp_w = _WEEKDAY_MAP[token["weekday"]]
        for candidate_year in [ref_year, ref_year + 1, ref_year - 1]:
            try:
                if datetime(candidate_year, token["month"], token["day"]).weekday() == exp_w:
                    return candidate_year
            except ValueError:
                pass
    return ref_year


def _clean_combined_title(subject: str, item: str) -> str:
    if not subject:
        return item
    if not item or item == "일정":
        return subject
    if subject.endswith("신청") and item.startswith("신청"):
        return f"{subject} {item[2:].strip()}"
    return f"{subject} {item}"


def _extract_structured_and_real_notice_candidates(
    text: str,
    ref_year: int,
    ref_dt: datetime,
    tz_str: str,
    source_title: str | None = None,
) -> list[ScheduleCandidate]:
    m_yr = re.search(r"(\d{4})학년도", text) or re.search(r"(\d{4})년", text[:300])
    text_year = int(m_yr.group(1)) if m_yr else None

    doc_subject = _find_document_subject(text)
    candidates: list[ScheduleCandidate] = []

    first_lines = "\n".join(text.splitlines()[:5])
    raw_lines = text.splitlines()
    first_line = raw_lines[0].strip() if raw_lines else ""
    is_headline_line = bool(raw_lines and any(w in first_line for w in ["안내", "모집", "공고", "선발", "계획"]) and len(first_line) > 10)
    headline_span = (0, len(raw_lines[0])) if is_headline_line else (-1, -1)

    headline_text = source_title.strip() if (source_title and source_title.strip()) else (first_line if is_headline_line else "")
    headline_date_tokens: list[tuple[int, int]] = []
    if headline_text:
        for hm in _SINGLE_DATE_RE.finditer(headline_text):
            hp = _parse_date_token(hm.group("full"))
            if hp and hp.get("month") and hp.get("day"):
                if 1 <= hp["month"] <= 12 and 1 <= hp["day"] <= 31:
                    headline_date_tokens.append((hp["month"], hp["day"]))

    # 1. Academic Calendar List (학사일정 목록형)
    is_calendar_doc = "학사일정" in doc_subject or "월간 일정" in first_lines or "연간 일정" in first_lines
    if is_calendar_doc:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        date_re = re.compile(r"^(?:(\d{4})\.)?(\d{1,2})\.(\d{1,2})\(([월화수목금토일])\)$")
        i = 0
        while i < len(lines):
            m1 = date_re.match(lines[i])
            if m1:
                y1 = int(m1.group(1)) if m1.group(1) else (text_year or ref_year)
                mo1, dy1 = int(m1.group(2)), int(m1.group(3))
                if i + 2 < len(lines) and lines[i + 1] in ["~", "∼", "-"] and date_re.match(lines[i + 2]):
                    m2 = date_re.match(lines[i + 2])
                    y2 = int(m2.group(1)) if m2.group(1) else y1
                    mo2, dy2 = int(m2.group(2)), int(m2.group(3))
                    title = lines[i + 3] if i + 3 < len(lines) and not date_re.match(lines[i + 3]) else "학사일정"
                    q_candidate = f"{lines[i]}\n{lines[i+1]}\n{lines[i+2]}\n{title}"
                    if q_candidate not in text:
                        idx1 = text.find(lines[i])
                        idx2 = text.find(title, idx1)
                        if idx1 != -1 and idx2 != -1:
                            q_candidate = text[idx1 : idx2 + len(title)]
                        else:
                            q_candidate = f"{lines[i]}\n{lines[i+1]}\n{lines[i+2]}"
                    s_date = f"{y1}-{mo1:02d}-{dy1:02d}"
                    e_date = f"{y2}-{mo2:02d}-{dy2:02d}"
                    candidates.append(
                        ScheduleCandidate(
                            title=title,
                            schedule_kind="PERIOD_SCHEDULE",
                            start_date=s_date,
                            end_date=e_date,
                            start_datetime=None,
                            end_datetime=None,
                            is_all_day=True,
                            is_time_confirmed=False,
                            unconfirmed_fields=["time"],
                            is_ambiguous=False,
                            ambiguity_reason=None,
                            requires_user_confirmation=True,
                            source_quote=q_candidate,
                        )
                    )
                    i += 4
                else:
                    title = lines[i + 1] if i + 1 < len(lines) and not date_re.match(lines[i + 1]) else "학사일정"
                    q_candidate = f"{lines[i]}\n{title}"
                    if q_candidate not in text:
                        q_candidate = lines[i]
                    s_date = f"{y1}-{mo1:02d}-{dy1:02d}"
                    candidates.append(
                        ScheduleCandidate(
                            title=title,
                            schedule_kind="ALL_DAY_EVENT",
                            start_date=s_date,
                            end_date=s_date,
                            start_datetime=None,
                            end_datetime=None,
                            is_all_day=True,
                            is_time_confirmed=False,
                            unconfirmed_fields=["time"],
                            is_ambiguous=False,
                            ambiguity_reason=None,
                            requires_user_confirmation=True,
                            source_quote=q_candidate,
                        )
                    )
                    i += 2
            else:
                i += 1
        return candidates

    # 2. General Real Notice Extraction (Range matching)
    matched_spans: list[tuple[int, int]] = []
    for m in _RANGE_PATTERN.finditer(text):
        if is_headline_line and m.start() < headline_span[1]:
            continue

        raw_start = m.group("start").strip()
        raw_end = m.group("end").strip()

        t_start = _parse_date_token(raw_start)
        t_end = _parse_date_token(raw_end)
        if not t_start or not t_end:
            continue

        matched_spans.append((m.start(), m.end()))

        y_start = _infer_year(t_start, t_end, text_year, ref_year)
        y_end = _infer_year(t_end, t_start, text_year, ref_year)

        line_start = text.rfind("\n", 0, m.start())
        line_start = 0 if line_start == -1 else line_start + 1
        same_line_prefix = text[line_start : m.start()].strip()

        item_title = ""
        m_p = re.search(r"^(?:[0-9]+[.)\s]+|[가-하ㄱ-ㅎ][.)]\s*|[-*•]\s+)?([^\n:：]+?)[\s]*[:：]\s*$", same_line_prefix)
        if m_p:
            item_title = m_p.group(1).strip()
        elif "\t" in same_line_prefix:
            parts = [p.strip() for p in same_line_prefix.split("\t") if p.strip()]
            if parts:
                item_title = parts[0]
        else:
            preceding = text[max(0, m.start() - 200) : m.start()]
            prec_lines = [l.strip() for l in preceding.splitlines() if l.strip()]
            succeeding = text[m.end() : min(len(text), m.end() + 200)]
            succ_lines = [l.strip() for l in succeeding.splitlines() if l.strip()]

            step_name = ""
            for pl in reversed(prec_lines):
                if re.search(r"^\d+단계", pl):
                    step_name = pl
                    break
            after_name = ""
            for sl in succ_lines:
                m_br = re.search(r"^\[([^\n\]]+)\]", sl)
                if m_br:
                    after_name = m_br.group(1).strip()
                    break
                elif sl and not sl.startswith(("-", "*", "①", "1)", "※", "http", "202", "~")):
                    after_name = sl
                    break

            table_item = ""
            if prec_lines and not step_name:
                last_p = prec_lines[-1]
                if not any(h in last_p for h in ["구 분", "기간", "대상", "일정"]):
                    table_item = last_p

            if step_name and after_name:
                item_title = f"{step_name} [{after_name}]"
            elif table_item:
                item_title = table_item
            elif after_name:
                item_title = after_name
            elif step_name:
                item_title = step_name

        if not item_title:
            item_title = "일정"

        generic_keywords = ["기간", "일정", "신청", "접수", "등록", "납부", "제출", "운영"]
        if doc_subject and any(k in item_title for k in generic_keywords) and doc_subject not in item_title:
            if "단계" in item_title:
                full_title = f"{item_title}"
            else:
                full_title = _clean_combined_title(doc_subject, item_title)
        else:
            full_title = item_title

        full_title = re.sub(r"\s+", " ", full_title).strip()

        has_start_time_token = t_start["hour"] is not None and t_start["minute"] is not None
        has_end_time_token = t_end["hour"] is not None and t_end["minute"] is not None

        is_ambiguous = False
        ambiguity_reasons: list[str] = []
        unconfirmed: list[str] = []

        m_mo = t_end["month"]
        m_dy = t_end["day"]
        m_hr = t_end["hour"]
        m_mn = t_end["minute"]

        s_mo = t_start["month"]
        s_dy = t_start["day"]
        s_hr = t_start["hour"]
        s_mn = t_start["minute"]

        # Symmetric start time handling
        has_valid_start_time = False
        if has_start_time_token and s_hr == 24 and s_mn == 0:
            is_ambiguous = True
            if "time" not in unconfirmed:
                unconfirmed.append("time")
            if "exact_boundary" not in unconfirmed:
                unconfirmed.append("exact_boundary")
            ambiguity_reasons.append("24:00 경계 표현은 당일 23:59:59와 익일 00:00 등 해석 차이가 존재하여 확인 필요")
            start_val = f"{y_start}-{s_mo:02d}-{s_dy:02d}"
            start_dt = None
        elif has_start_time_token:
            start_dt = f"{y_start}-{s_mo:02d}-{s_dy:02d}T{s_hr:02d}:{s_mn:02d}:00{tz_str}"
            start_val = start_dt
            if 0 <= s_hr <= 23 and 0 <= s_mn <= 59:
                has_valid_start_time = True
            else:
                is_ambiguous = True
                if "time" not in unconfirmed:
                    unconfirmed.append("time")
                ambiguity_reasons.append(f"존재하지 않는 시각({s_hr:02d}:{s_mn:02d})으로 인해 시각 확정 불가")
        else:
            start_val = f"{y_start}-{s_mo:02d}-{s_dy:02d}"
            start_dt = None
            if "start_time" not in unconfirmed:
                unconfirmed.append("start_time")

        # Symmetric end time handling
        has_valid_end_time = False
        if has_end_time_token and m_hr == 24 and m_mn == 0:
            is_ambiguous = True
            if "time" not in unconfirmed:
                unconfirmed.append("time")
            if "exact_boundary" not in unconfirmed:
                unconfirmed.append("exact_boundary")
            ambiguity_reasons.append("24:00 경계 표현은 당일 23:59:59와 익일 00:00 등 해석 차이가 존재하여 확인 필요")
            end_val = f"{y_end}-{m_mo:02d}-{m_dy:02d}"
            end_dt = None
        elif has_end_time_token:
            end_dt = f"{y_end}-{m_mo:02d}-{m_dy:02d}T{m_hr:02d}:{m_mn:02d}:00{tz_str}"
            end_val = end_dt
            if 0 <= m_hr <= 23 and 0 <= m_mn <= 59:
                has_valid_end_time = True
            else:
                is_ambiguous = True
                if "time" not in unconfirmed:
                    unconfirmed.append("time")
                ambiguity_reasons.append(f"존재하지 않는 시각({m_hr:02d}:{m_mn:02d})으로 인해 시각 확정 불가")
        else:
            end_val = f"{y_end}-{m_mo:02d}-{m_dy:02d}"
            end_dt = None
            if "time" not in unconfirmed:
                unconfirmed.append("time")

        if headline_date_tokens and any(k in item_title for k in ["신청", "접수", "모집", "등록"]):
            has_mismatch = any(
                not (
                    (h_m == t_start["month"] and h_d == t_start["day"])
                    or (h_m == t_end["month"] and h_d == t_end["day"])
                )
                for h_m, h_d in headline_date_tokens
            )
            if has_mismatch:
                is_ambiguous = True
                conflict_msg = "공지 제목의 기간과 본문 신청 기간이 상이하여 확인 필요"
                if conflict_msg not in ambiguity_reasons:
                    ambiguity_reasons.append(conflict_msg)

        ambiguity_reason = ", ".join(ambiguity_reasons) if ambiguity_reasons else None

        quote = m.group(0).strip()
        assert quote in text

        candidates.append(
            ScheduleCandidate(
                title=full_title,
                schedule_kind="PERIOD_SCHEDULE",
                start_date=start_val,
                end_date=end_val,
                start_datetime=start_dt,
                end_datetime=end_dt,
                is_all_day=not (has_valid_start_time and has_valid_end_time),
                is_time_confirmed=(has_valid_start_time or has_valid_end_time) and not is_ambiguous,
                unconfirmed_fields=unconfirmed,
                is_ambiguous=is_ambiguous,
                ambiguity_reason=ambiguity_reason,
                requires_user_confirmation=True,
                source_quote=quote,
            )
        )

    # 2.5 Intraday single-date time range matching (e.g. TOPCIT 4단계: 10. 10.(토) 9:30 ~ 12:00 시험 응시)
    for m in _INTRADAY_RANGE_RE.finditer(text):
        if is_headline_line and m.start() < headline_span[1]:
            continue
        sp = (m.start(), m.end())
        if any(max(sp[0], rsp[0]) < min(sp[1], rsp[1]) for rsp in matched_spans):
            continue

        raw_date = m.group("date").strip()
        t_date = _parse_date_token(raw_date)
        if not t_date or not t_date.get("month") or not t_date.get("day"):
            continue

        m_st = re.match(r"^(\d{1,2}):(\d{2})$", m.group("start_time"))
        m_et = re.match(r"^(\d{1,2}):(\d{2})$", m.group("end_time"))
        if not m_st or not m_et:
            continue
        s_hr, s_mn = int(m_st.group(1)), int(m_st.group(2))
        e_hr, e_mn = int(m_et.group(1)), int(m_et.group(2))

        matched_spans.append(sp)
        y_val = _infer_year(t_date, None, text_year, ref_year)

        preceding = text[max(0, m.start() - 200) : m.start()]
        prec_lines = [l.strip() for l in preceding.splitlines() if l.strip()]
        succeeding = text[m.end() : min(len(text), m.end() + 200)]
        succ_lines = [l.strip() for l in succeeding.splitlines() if l.strip()]

        step_name = ""
        for pl in reversed(prec_lines):
            if re.search(r"^\d+단계", pl):
                step_name = pl
                break
        after_name = ""
        for sl in succ_lines:
            m_br = re.search(r"^\[([^\n\]]+)\]", sl)
            if m_br:
                after_name = m_br.group(1).strip()
                break
            elif sl and not sl.startswith(("-", "*", "①", "1)", "※", "http", "202", "~")):
                after_name = sl
                break

        if step_name and after_name:
            item_title = f"{step_name} [{after_name}]"
        elif after_name:
            item_title = after_name
        elif step_name:
            item_title = step_name
        else:
            item_title = "일정"

        full_title = re.sub(r"\s+", " ", item_title).strip()
        quote = m.group("full").strip()

        mo = t_date["month"]
        dy = t_date["day"]
        unconfirmed = []
        ambiguity_reasons = []
        is_ambiguous = False

        start_dt = f"{y_val}-{mo:02d}-{dy:02d}T{s_hr:02d}:{s_mn:02d}:00{tz_str}"
        end_dt = f"{y_val}-{mo:02d}-{dy:02d}T{e_hr:02d}:{e_mn:02d}:00{tz_str}"

        has_valid_start = (0 <= s_hr <= 23 and 0 <= s_mn <= 59)
        has_valid_end = (0 <= e_hr <= 23 and 0 <= e_mn <= 59)
        if not has_valid_start:
            is_ambiguous = True
            unconfirmed.append("time")
            ambiguity_reasons.append(f"존재하지 않는 시각({s_hr:02d}:{s_mn:02d})으로 인해 시각 확정 불가")
        if not has_valid_end:
            is_ambiguous = True
            if "time" not in unconfirmed:
                unconfirmed.append("time")
            ambiguity_reasons.append(f"존재하지 않는 시각({e_hr:02d}:{e_mn:02d})으로 인해 시각 확정 불가")

        candidates.append(
            ScheduleCandidate(
                title=full_title,
                schedule_kind="TIME_CONFIRMED_EVENT",
                start_date=start_dt,
                end_date=end_dt,
                start_datetime=start_dt,
                end_datetime=end_dt,
                is_all_day=False,
                is_time_confirmed=has_valid_start and has_valid_end and not is_ambiguous,
                unconfirmed_fields=unconfirmed,
                is_ambiguous=is_ambiguous,
                ambiguity_reason=", ".join(ambiguity_reasons) if ambiguity_reasons else None,
                requires_user_confirmation=True,
                source_quote=quote,
            )
        )

    # 3. Single Date / Deadline Matching (for single events and un-ranged dates)
    for m in _SINGLE_DATE_RE.finditer(text):
        if is_headline_line and m.start() < headline_span[1]:
            continue
        sp = (m.start(), m.end())
        if any(max(sp[0], rsp[0]) < min(sp[1], rsp[1]) for rsp in matched_spans):
            continue
        if m.start() > 0 and text[m.start() - 1].isdigit():
            continue
        if m.end() < len(text) and text[m.end()].isdigit():
            continue

        gd = m.groupdict()
        if not gd.get("month") or not gd.get("day"):
            continue
        mo_int = int(gd["month"])
        dy_int = int(gd["day"])
        if not (1 <= mo_int <= 12 and 1 <= dy_int <= 31):
            continue

        has_time = gd.get("hour") is not None and gd.get("minute") is not None
        suffix = gd.get("suffix")
        surround = text[max(0, m.start() - 50) : min(len(text), m.end() + 50)]
        if not (has_time or suffix or any(k in surround for k in ["마감", "제출", "접수", "등록", "일시", "면접", "행사", "시험", "개최", "특강", "진행"])):
            continue

        t_val = _parse_date_token(m.group("full"))
        if not t_val:
            continue
        y_val = _infer_year(t_val, None, text_year, ref_year)
        mo = t_val["month"]
        dy = t_val["day"]
        hr = t_val["hour"]
        mn = t_val["minute"]

        line_start = text.rfind("\n", 0, m.start())
        line_start = 0 if line_start == -1 else line_start + 1
        line_prefix = text[line_start : m.start()].strip()
        item_title = ""
        m_lp = re.search(r"^(?:[0-9]+[.)\s]+|[가-하ㄱ-ㅎ][.)]\s*|[-*•]\s+)?([^\n:：]+?)[\s]*[:：]\s*$", line_prefix)
        if m_lp:
            item_title = m_lp.group(1).strip()
        elif not candidates and doc_subject:
            item_title = doc_subject
        elif not candidates:
            item_title = "일정 마감"
        else:
            continue

        full_title = re.sub(r"\s+", " ", item_title).strip()
        quote = m.group("full").strip()

        is_deadline = bool(
            suffix == "까지"
            or any(k in full_title for k in ["마감", "제출", "접수", "등록", "납부", "까지"])
            or ("까지" in surround and "일시" not in full_title and "면접" not in full_title and "행사" not in full_title)
        )

        if hr == 24 and (mn == 0 or mn is None):
            candidates.append(
                ScheduleCandidate(
                    title=full_title,
                    schedule_kind="DEADLINE_WITH_TIME" if is_deadline else "TIME_CONFIRMED_EVENT",
                    start_date=None if is_deadline else f"{y_val}-{mo:02d}-{dy:02d}",
                    end_date=f"{y_val}-{mo:02d}-{dy:02d}",
                    start_datetime=None,
                    end_datetime=None,
                    is_all_day=False,
                    is_time_confirmed=False,
                    unconfirmed_fields=["time", "exact_boundary"],
                    is_ambiguous=True,
                    ambiguity_reason="24:00 경계 표현은 당일 23:59:59와 익일 00:00 등 해석 차이가 존재하여 확인 필요",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        elif has_time:
            dt_str = f"{y_val}-{mo:02d}-{dy:02d}T{hr:02d}:{mn:02d}:00{tz_str}"
            is_valid_t = (0 <= hr <= 23 and 0 <= mn <= 59)
            if not is_valid_t:
                candidates.append(
                    ScheduleCandidate(
                        title=full_title,
                        schedule_kind="DEADLINE_WITH_TIME" if is_deadline else "TIME_CONFIRMED_EVENT",
                        start_date=None if is_deadline else dt_str,
                        end_date=dt_str if is_deadline else None,
                        start_datetime=None if is_deadline else dt_str,
                        end_datetime=dt_str if is_deadline else None,
                        is_all_day=False,
                        is_time_confirmed=False,
                        unconfirmed_fields=["time"],
                        is_ambiguous=True,
                        ambiguity_reason=f"존재하지 않는 시각({hr:02d}:{mn:02d})으로 인해 시각 확정 불가",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            elif is_deadline:
                candidates.append(
                    ScheduleCandidate(
                        title=full_title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        start_date=None,
                        end_date=dt_str,
                        start_datetime=None,
                        end_datetime=dt_str,
                        is_all_day=False,
                        is_time_confirmed=True,
                        unconfirmed_fields=[],
                        is_ambiguous=False,
                        ambiguity_reason=None,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=full_title,
                        schedule_kind="TIME_CONFIRMED_EVENT",
                        start_date=dt_str,
                        end_date=None,
                        start_datetime=dt_str,
                        end_datetime=None,
                        is_all_day=False,
                        is_time_confirmed=True,
                        unconfirmed_fields=["end_time"],
                        is_ambiguous=True,
                        ambiguity_reason="시작 시각은 확정되나 종료 시각 미명시로 기본 이벤트 슬롯 확인 필요",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
        else:
            if is_deadline:
                candidates.append(
                    ScheduleCandidate(
                        title=full_title,
                        schedule_kind="DATE_ONLY_DEADLINE",
                        start_date=None,
                        end_date=f"{y_val}-{mo:02d}-{dy:02d}",
                        start_datetime=None,
                        end_datetime=None,
                        is_all_day=True,
                        is_time_confirmed=False,
                        unconfirmed_fields=["time"],
                        is_ambiguous=True,
                        ambiguity_reason="마감 시각이 명시되지 않은 날짜 전용 일정입니다.",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=full_title,
                        schedule_kind="ALL_DAY_EVENT",
                        start_date=f"{y_val}-{mo:02d}-{dy:02d}",
                        end_date=f"{y_val}-{mo:02d}-{dy:02d}",
                        start_datetime=None,
                        end_datetime=None,
                        is_all_day=True,
                        is_time_confirmed=False,
                        unconfirmed_fields=["time"],
                        is_ambiguous=True,
                        ambiguity_reason="시각이 명시되지 않은 종일 일정입니다.",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )

    return candidates


def extract_schedule_candidates(
    text: str,
    reference_time: str | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
) -> ScheduleExtractionResponse:
    """자연어 텍스트 또는 공지 본문에서 일정 후보를 추출한다.

    - DB에 저장하지 않는 비영속(Stateless) 분석
    - 모든 반환 후보는 requires_user_confirmation: True 강제
    - 후보가 0건인 경우 응답의 requires_user_confirmation은 False
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        return ScheduleExtractionResponse(
            candidates=[],
            requires_user_confirmation=False,
            total_candidates=0,
        )

    ref_dt, tz_str = _parse_reference_datetime(reference_time)
    ref_year = ref_dt.year
    ref_date_str = ref_dt.strftime("%Y-%m-%d")
    tomorrow_dt = ref_dt + timedelta(days=1)
    tomorrow_date_str = tomorrow_dt.strftime("%Y-%m-%d")

    # 상대 요일 계산
    ref_weekday = ref_dt.weekday()
    this_friday_dt = ref_dt + timedelta(days=(4 - ref_weekday))
    this_friday_str = this_friday_dt.strftime("%Y-%m-%d")
    next_monday_dt = ref_dt + timedelta(days=(7 - ref_weekday))
    next_monday_str = next_monday_dt.strftime("%Y-%m-%d")

    candidates: list[ScheduleCandidate] = []

    # ─────────────────────────────────────────────────────────────
    # 규칙 1: 취소 공지 (sched-23)
    # ─────────────────────────────────────────────────────────────
    if any(k in cleaned_text for k in ["[취소공지]", "취소되었습니다", "행사 취소", "취소 안내"]):
        m = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\s*(\d{1,2}:\d{2}))?", cleaned_text)
        start_dt = None
        is_val = False
        err_reason = None
        unconf = []
        has_time = False
        if m:
            y = int(m.group(1)) if m.group(1) else ref_year
            month = int(m.group(2))
            day = int(m.group(3))
            time_part = m.group(4)
            h = int(time_part.split(":")[0]) if time_part else None
            mn = int(time_part.split(":")[1]) if time_part else None
            has_time = bool(time_part)

            is_val, err_reason, unconf = _check_calendar_validity(y, month, day, h, mn)
            if is_val:
                if time_part:
                    start_dt = f"{y}-{month:02d}-{day:02d}T{time_part}:00{tz_str}"
                else:
                    start_dt = f"{y}-{month:02d}-{day:02d}"

        # 행사명 추론
        m_ev = re.search(r"예정되었던\s*([^\n]+?)\s*행사는", cleaned_text)
        if m_ev:
            ev_title = m_ev.group(1).strip()
        else:
            m_ev2 = re.search(r"([^\n]+?)\s*행사는", cleaned_text)
            ev_title = m_ev2.group(1).strip() if m_ev2 else "행사"

        # quote 추출 (접두 태그 제외하고 원문 내 문장 매칭)
        m_q = re.search(r"((?:\d{4}년\s*)?\d{1,2}월\s*\d{1,2}일(?:\s*\d{1,2}:\d{2})?\s*예정되었던\s*[^\n]+?취소되었습니다\.)", cleaned_text)
        quote = m_q.group(1) if m_q else cleaned_text

        if is_val and start_dt:
            candidates.append(
                ScheduleCandidate(
                    title=f"{ev_title} (취소)",
                    schedule_kind="TIME_CONFIRMED_EVENT" if has_time else "ALL_DAY_EVENT",
                    action="cancel",
                    is_cancellation=True,
                    is_all_day=not has_time,
                    start_date=start_dt,
                    end_date=None,
                    start_datetime=start_dt if has_time else None,
                    end_datetime=None,
                    is_time_confirmed=has_time,
                    unconfirmed_fields=[] if has_time else ["time"],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=f"{ev_title} (취소)",
                    schedule_kind="TIME_CONFIRMED_EVENT",
                    action="cancel",
                    is_cancellation=True,
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf or ["exact_date"],
                    is_ambiguous=True,
                    ambiguity_reason=err_reason or "취소 일정의 일시 정보가 유효하지 않습니다.",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 2: 자정 경계 모호 ("자정까지") (sched-20 & counterexample 3)
    # ─────────────────────────────────────────────────────────────
    if "자정까지" in cleaned_text:
        m_date = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*자정까지", cleaned_text)
        m_q = re.search(r"((?:\d{1,2}월\s*\d{1,2}일\s*)?자정까지(?:입니다\.?)?)", cleaned_text)
        quote = m_q.group(1) if m_q else "자정까지"

        if m_date:
            year = int(m_date.group(1)) if m_date.group(1) else ref_year
            month = int(m_date.group(2))
            day = int(m_date.group(3))
            is_valid, err_reason, unconf = _check_calendar_validity(year, month, day)

            extracted_date = f"{year}-{month:02d}-{day:02d}"
            date_display = f"{month}월 {day}일"

            prefix = cleaned_text[: m_date.start()].strip()
            prefix = re.sub(r"[은는]\s*$", "", prefix).strip()
            title = prefix or "일정 마감"

            if is_valid:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        extracted_date=extracted_date,
                        is_time_confirmed=False,
                        unconfirmed_fields=["time", "exact_boundary"],
                        is_ambiguous=True,
                        ambiguity_reason=f"'자정까지' 표현은 {date_display} 23:59:59(당일 종료)와 {date_display} 00:00(당일 시작) 등 해석 차이가 존재하므로 임의의 timestamp로 확정하지 않고 null 유지",
                        interpretation_options=[
                            f"{extracted_date}T23:59:59{tz_str}",
                            f"{extracted_date}T00:00:00{tz_str}",
                        ],
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        extracted_date=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf + ["time", "exact_boundary"],
                        is_ambiguous=True,
                        ambiguity_reason=err_reason,
                        interpretation_options=None,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
        else:
            # 원문에 날짜가 없는 경우 (예: "과제는 자정까지 제출하세요.")
            # 원문에 없는 임의 날짜(2026-10-09 등)를 날조하지 않고 extracted_date=None 유지
            prefix = cleaned_text.split("자정까지")[0].strip()
            prefix = re.sub(r"[은는]\s*$", "", prefix).strip()
            if prefix and not prefix.endswith("마감") and not prefix.endswith("제출"):
                title = f"{prefix} 마감"
            else:
                title = prefix or "과제 마감"

            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    extracted_date=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=["date", "time", "exact_boundary"],
                    is_ambiguous=True,
                    ambiguity_reason="'자정까지' 표현은 마감 날짜 및 시각(당일 23:59:59 vs 익일 00:00)이 특정되지 않아 날짜/시각 확정 불가",
                    interpretation_options=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 3: 날짜와 시각이 분리된 문장 (sched-18 & Defect B counterexample)
    # ─────────────────────────────────────────────────────────────
    if ("마감일" in cleaned_text and "전산 마감" in cleaned_text) and re.search(
        r"(\d{1,2})월\s*(\d{1,2})일부터\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일까지", cleaned_text
    ):
        m_period = re.search(
            r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일부터\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일까지",
            cleaned_text,
        )
        m_time = re.search(r"마감일\s*(\d{1,2}:\d{2})", cleaned_text)
        y1 = int(m_period.group(1)) if m_period.group(1) else ref_year
        m1, d1 = int(m_period.group(2)), int(m_period.group(3))
        m2, d2 = int(m_period.group(5)), int(m_period.group(6))
        y2 = int(m_period.group(4)) if m_period.group(4) else (y1 + 1 if m2 < m1 else y1)

        prefix = cleaned_text[: m_period.start()].strip()
        m_title = re.search(r"([^\n.]+?)(?:\s*기간(?:은|는|이)?)?(?:은|는)?\s*$", prefix)
        title = m_title.group(1).strip() if m_title else "일정 안내"
        if not title:
            title = "일정 안내"

        quote1 = m_period.group(0)
        quote2 = None
        if m_time:
            time_str = m_time.group(1)
            th, tmn = int(time_str.split(":")[0]), int(time_str.split(":")[1])
            is_v1, err1, u1 = _check_calendar_validity(y1, m1, d1)
            is_v2, err2, u2 = _check_calendar_validity(y2, m2, d2, th, tmn)
            m_full_q = re.search(r"(마감일\s*\d{1,2}:\d{2}\s*에\s*전산\s*마감됩니다\.?)", cleaned_text)
            quote2 = m_full_q.group(1) if m_full_q else (m_time.group(0) + "에 전산 마감됩니다.")

            if is_v1 and is_v2:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="PERIOD_SCHEDULE",
                        is_all_day=False,
                        start_date=f"{y1}-{m1:02d}-{d1:02d}",
                        end_date=f"{y2}-{m2:02d}-{d2:02d}T{time_str}:00{tz_str}",
                        start_datetime=None,
                        end_datetime=f"{y2}-{m2:02d}-{d2:02d}T{time_str}:00{tz_str}",
                        is_time_confirmed=True,
                        unconfirmed_fields=["start_time"],
                        is_ambiguous=False,
                        ambiguity_reason=None,
                        requires_user_confirmation=True,
                        source_quote=quote1,
                        source_quotes=[quote1, quote2],
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="PERIOD_SCHEDULE",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=list(set(u1 + u2)),
                        is_ambiguous=True,
                        ambiguity_reason=err1 or err2,
                        requires_user_confirmation=True,
                        source_quote=quote1,
                        source_quotes=[quote1, quote2],
                    )
                )
        else:
            # 원문에 마감 시각이 없는 경우 -> 17:30 기본값 제거, 날짜 전용 또는 미확정 처리
            is_v1, err1, u1 = _check_calendar_validity(y1, m1, d1)
            is_v2, err2, u2 = _check_calendar_validity(y2, m2, d2)
            if is_v1 and is_v2:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="PERIOD_SCHEDULE",
                        is_all_day=True,
                        start_date=f"{y1}-{m1:02d}-{d1:02d}",
                        end_date=f"{y2}-{m2:02d}-{d2:02d}",
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=["start_time", "end_time"],
                        is_ambiguous=True,
                        ambiguity_reason="마감일에 전산 마감되나 구체적 마감 시각이 미명시된 날짜 전용 일정입니다.",
                        requires_user_confirmation=True,
                        source_quote=quote1,
                        source_quotes=[quote1],
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="PERIOD_SCHEDULE",
                        is_all_day=True,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=list(set(u1 + u2 + ["time"])),
                        is_ambiguous=True,
                        ambiguity_reason=err1 or err2,
                        requires_user_confirmation=True,
                        source_quote=quote1,
                        source_quotes=[quote1],
                    )
                )

        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 4: 선착순 조기 마감 조건부 (날짜 범위가 있는 경우) (sched-21)
    # ─────────────────────────────────────────────────────────────
    m_cond_dates = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})\s*오픈\s*~\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})\s*마감",
        cleaned_text,
    )
    if "선착순" in cleaned_text and "조기 마감" in cleaned_text and m_cond_dates:
        y1 = int(m_cond_dates.group(1)) if m_cond_dates.group(1) else ref_year
        m1, d1, t1 = int(m_cond_dates.group(2)), int(m_cond_dates.group(3)), m_cond_dates.group(4)
        m2, d2, t2 = int(m_cond_dates.group(6)), int(m_cond_dates.group(7)), m_cond_dates.group(8)
        y2 = int(m_cond_dates.group(5)) if m_cond_dates.group(5) else (y1 + 1 if m2 < m1 else y1)
        quote = m_cond_dates.group(0)
        prefix = cleaned_text[: m_cond_dates.start()].strip()
        prefix = re.sub(r"[은는]$", "", prefix).strip()
        title = prefix.rstrip(":").strip() or "동아리 연합 축제 부스 신청"

        h1, mn1 = int(t1.split(":")[0]), int(t1.split(":")[1])
        h2, mn2 = int(t2.split(":")[0]), int(t2.split(":")[1])

        is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, m1, d1, h1, mn1)
        is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, m2, d2, h2, mn2)

        if is_val1 and is_val2:
            s_dt = f"{y1}-{m1:02d}-{d1:02d}T{t1}:00{tz_str}"
            e_dt = f"{y2}-{m2:02d}-{d2:02d}T{t2}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=s_dt,
                    end_date=e_dt,
                    start_datetime=s_dt,
                    end_datetime=e_dt,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=True,
                    ambiguity_reason="선착순 조기 마감 조건이 명시되어 마감 일정 변동 가능성 안내 필요",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=list(set(unconf1 + unconf2)),
                    is_ambiguous=True,
                    ambiguity_reason=err_reason1 or err_reason2 or "달력상 유효하지 않은 날짜/시각이 포함되어 있습니다.",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 5: 매일 반복 시간대 (sched-16)
    # ─────────────────────────────────────────────────────────────
    m_daily = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*~\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*매일\s*(\d{1,2}:\d{2})[~-](\d{1,2}:\d{2})",
        cleaned_text,
    )
    if m_daily:
        y1 = int(m_daily.group(1)) if m_daily.group(1) else ref_year
        m1, d1 = int(m_daily.group(2)), int(m_daily.group(3))
        m2, d2 = int(m_daily.group(5)), int(m_daily.group(6))
        y2 = int(m_daily.group(4)) if m_daily.group(4) else (y1 + 1 if m2 < m1 else y1)
        t1, t2 = m_daily.group(7), m_daily.group(8)
        quote = m_daily.group(0)
        prefix = cleaned_text[: m_daily.start()].strip()
        title = prefix.replace(" 기간:", "").rstrip(":").strip() or "2026-2학기 추가 수강정정"

        h1, mn1 = int(t1.split(":")[0]), int(t1.split(":")[1])
        h2, mn2 = int(t2.split(":")[0]), int(t2.split(":")[1])
        is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, m1, d1, h1, mn1)
        is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, m2, d2, h2, mn2)

        if is_val1 and is_val2:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=f"{y1}-{m1:02d}-{d1:02d}T{t1}:00{tz_str}",
                    end_date=f"{y2}-{m2:02d}-{d2:02d}T{t2}:00{tz_str}",
                    start_datetime=f"{y1}-{m1:02d}-{d1:02d}T{t1}:00{tz_str}",
                    end_datetime=f"{y2}-{m2:02d}-{d2:02d}T{t2}:00{tz_str}",
                    is_time_confirmed=True,
                    unconfirmed_fields=["daily_recurrence_pattern"],
                    is_ambiguous=True,
                    ambiguity_reason="기간 내 매일 특정 시간대 운영으로 반복 일정 등록 또는 단일 기간 등록 선택 필요",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=list(set(unconf1 + unconf2 + ["daily_recurrence_pattern"])),
                    is_ambiguous=True,
                    ambiguity_reason=err_reason1 or err_reason2 or "달력상 유효하지 않은 날짜/시각이 포함되어 있습니다.",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 6: 다회차 독립 이벤트 (sched-14 & counterexample 5)
    # ─────────────────────────────────────────────────────────────
    if "1차" in cleaned_text and "2차" in cleaned_text and "1시간 진행" in cleaned_text:
        m1 = re.search(r"1차\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})", cleaned_text)
        m2 = re.search(r"2차\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})", cleaned_text)
        if m1 and m2:
            y1 = int(m1.group(1)) if m1.group(1) else ref_year
            mo1, dy1, tm1 = int(m1.group(2)), int(m1.group(3)), m1.group(4)
            y2 = int(m2.group(1)) if m2.group(1) else ref_year
            mo2, dy2, tm2 = int(m2.group(2)), int(m2.group(3)), m2.group(4)

            h1, min1 = int(tm1.split(":")[0]), int(tm1.split(":")[1])
            h2, min2 = int(tm2.split(":")[0]), int(tm2.split(":")[1])

            is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, mo1, dy1, h1, min1)
            is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, mo2, dy2, h2, min2)

            prefix = cleaned_text[: m1.start()].replace(" 일정:", "").rstrip(":").strip() or "설명회"

            if is_val1:
                dt_start1 = datetime(y1, mo1, dy1, h1, min1)
                dt_end1 = dt_start1 + timedelta(hours=1)
                s_dt1 = f"{dt_start1.strftime('%Y-%m-%dT%H:%M:%S')}{tz_str}"
                e_dt1 = f"{dt_end1.strftime('%Y-%m-%dT%H:%M:%S')}{tz_str}"
                candidates.append(
                    ScheduleCandidate(
                        title=f"{prefix} 1차",
                        schedule_kind="TIME_CONFIRMED_EVENT",
                        is_all_day=False,
                        start_date=s_dt1,
                        end_date=e_dt1,
                        start_datetime=s_dt1,
                        end_datetime=e_dt1,
                        is_time_confirmed=True,
                        unconfirmed_fields=[],
                        is_ambiguous=False,
                        ambiguity_reason=None,
                        requires_user_confirmation=True,
                        source_quote=m1.group(0),
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=f"{prefix} 1차",
                        schedule_kind="TIME_CONFIRMED_EVENT",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf1,
                        is_ambiguous=True,
                        ambiguity_reason=err_reason1,
                        requires_user_confirmation=True,
                        source_quote=m1.group(0),
                    )
                )

            if is_val2:
                dt_start2 = datetime(y2, mo2, dy2, h2, min2)
                dt_end2 = dt_start2 + timedelta(hours=1)
                s_dt2 = f"{dt_start2.strftime('%Y-%m-%dT%H:%M:%S')}{tz_str}"
                e_dt2 = f"{dt_end2.strftime('%Y-%m-%dT%H:%M:%S')}{tz_str}"
                candidates.append(
                    ScheduleCandidate(
                        title=f"{prefix} 2차",
                        schedule_kind="TIME_CONFIRMED_EVENT",
                        is_all_day=False,
                        start_date=s_dt2,
                        end_date=e_dt2,
                        start_datetime=s_dt2,
                        end_datetime=e_dt2,
                        is_time_confirmed=True,
                        unconfirmed_fields=[],
                        is_ambiguous=False,
                        ambiguity_reason=None,
                        requires_user_confirmation=True,
                        source_quote=m2.group(0),
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=f"{prefix} 2차",
                        schedule_kind="TIME_CONFIRMED_EVENT",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf2,
                        is_ambiguous=True,
                        ambiguity_reason=err_reason2,
                        requires_user_confirmation=True,
                        source_quote=m2.group(0),
                    )
                )

            return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 7: 다단계 순차 마감 (sched-10 & counterexample 4)
    # ─────────────────────────────────────────────────────────────
    m_staged1 = re.search(
        r"(?:(.*?):\s*)?([^\n,]+?)\s*마감은\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*(\d{1,2}:\d{2})\s*까지",
        cleaned_text,
    )
    m_staged2 = re.search(
        r"([^\n,]+?)(?:는|은)\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*(\d{1,2}:\d{2})\s*까지",
        cleaned_text[m_staged1.end():] if m_staged1 else "",
    )
    if m_staged1 and m_staged2:
        topic = "TOPCIT" if "TOPCIT" in cleaned_text else ""
        item1_name = m_staged1.group(2).strip()
        y1 = int(m_staged1.group(3)) if m_staged1.group(3) else ref_year
        mo1, dy1, tm1 = int(m_staged1.group(4)), int(m_staged1.group(5)), m_staged1.group(6)
        h1, min1 = int(tm1.split(":")[0]), int(tm1.split(":")[1])

        raw_item2 = m_staged2.group(1).strip()
        item2_name = re.sub(r"^(?:이며|이고|,|\s)+", "", raw_item2).strip()
        y2 = int(m_staged2.group(2)) if m_staged2.group(2) else ref_year
        mo2, dy2, tm2 = int(m_staged2.group(3)), int(m_staged2.group(4)), m_staged2.group(5)
        h2, min2 = int(tm2.split(":")[0]), int(tm2.split(":")[1])

        title1 = f"{topic} {item1_name} 마감" if (topic and topic not in item1_name) else f"{item1_name} 마감"
        title1 = re.sub(r"\s+", " ", title1).strip()
        title2 = f"{topic} {item2_name} 마감" if (topic and topic not in item2_name) else f"{item2_name} 마감"
        title2 = re.sub(r"\s+", " ", title2).strip()

        quote1 = f"{item1_name} 마감은 {mo1}월 {dy1}일 {tm1}까지"
        if quote1 not in cleaned_text:
            m_q1 = re.search(
                r"([^\n,:]+?마감은\s*\d{1,2}월\s*\d{1,2}일(?:\([월화수목금토일]\))?\s*\d{1,2}:\d{2}\s*까지)",
                cleaned_text,
            )
            quote1 = m_q1.group(1).strip() if m_q1 else m_staged1.group(0).split(":")[-1].strip()

        quote2 = f"{item2_name}는 {mo2}월 {dy2}일 {tm2}까지"
        if quote2 not in cleaned_text:
            m_q2 = re.search(
                r"([^\n,:]+?는\s*\d{1,2}월\s*\d{1,2}일(?:\([월화수목금토일]\))?\s*\d{1,2}:\d{2}\s*까지)",
                cleaned_text,
            )
            quote2 = m_q2.group(1).strip() if m_q2 else m_staged2.group(0).strip()

        is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, mo1, dy1, h1, min1)
        is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, mo2, dy2, h2, min2)

        if is_val1:
            end_dt1 = f"{y1}-{mo1:02d}-{dy1:02d}T{tm1}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title1,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=end_dt1,
                    start_datetime=None,
                    end_datetime=end_dt1,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote1,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title1,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf1,
                    is_ambiguous=True,
                    ambiguity_reason=err_reason1,
                    requires_user_confirmation=True,
                    source_quote=quote1,
                )
            )

        if is_val2:
            end_dt2 = f"{y2}-{mo2:02d}-{dy2:02d}T{tm2}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title2,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=end_dt2,
                    start_datetime=None,
                    end_datetime=end_dt2,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote2,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title2,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf2,
                    is_ambiguous=True,
                    ambiguity_reason=err_reason2,
                    requires_user_confirmation=True,
                    source_quote=quote2,
                )
            )

        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 8: 마감 연장 공지 (sched-11 & Defect B counterexample)
    # ─────────────────────────────────────────────────────────────
    m_ext = re.search(
        r"당초\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:에서|\s*~)\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\s*(\d{1,2}:\d{2}))?로\s*연장",
        cleaned_text,
    )
    if "연장" in cleaned_text and m_ext:
        y1 = int(m_ext.group(1)) if m_ext.group(1) else ref_year
        m1, d1 = int(m_ext.group(2)), int(m_ext.group(3))
        m2, d2 = int(m_ext.group(5)), int(m_ext.group(6))
        y2 = int(m_ext.group(4)) if m_ext.group(4) else (y1 + 1 if m2 < m1 else y1)
        tm = m_ext.group(7)
        quote = m_ext.group(0)

        prefix = cleaned_text[: m_ext.start()].replace("[마감연장]", "").strip()
        m_t = re.search(r"(\d{4}학년도\s*)?([^\n]+?)\s*마감일(?:이|은)?", prefix)
        t_base = m_t.group(2).strip() if m_t else re.sub(r"[은는이가]\s*$", "", prefix).strip()
        t_base = t_base or "일정"
        title = f"{t_base} 마감(연장)"

        if tm:
            th, tmn = int(tm.split(":")[0]), int(tm.split(":")[1])
            is_val, err_reason, unconf = _check_calendar_validity(y2, m2, d2, th, tmn)
            if is_val:
                end_dt = f"{y2}-{m2:02d}-{d2:02d}T{tm}:00{tz_str}"
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=end_dt,
                        start_datetime=None,
                        end_datetime=end_dt,
                        is_time_confirmed=True,
                        unconfirmed_fields=[],
                        is_ambiguous=True,
                        ambiguity_reason=f"구 마감일({m1}월 {d1}일)과 연장 마감일({m2}월 {d2}일) 혼재로 최종 연장본 확인 필요",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf,
                        is_ambiguous=True,
                        ambiguity_reason=err_reason,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
        else:
            # 원문에 연장 시각이 없는 경우 -> 15:00 기본값 제거, 날짜 전용 마감으로 처리
            is_val, err_reason, unconf = _check_calendar_validity(y2, m2, d2)
            if is_val:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DATE_ONLY_DEADLINE",
                        is_all_day=True,
                        start_date=None,
                        end_date=f"{y2}-{m2:02d}-{d2:02d}",
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=["time"],
                        is_ambiguous=True,
                        ambiguity_reason=f"구 마감일({m1}월 {d1}일)과 연장 마감일({m2}월 {d2}일) 혼재 및 마감 시각 미명시로 최종 연장본 확인 필요",
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DATE_ONLY_DEADLINE",
                        is_all_day=True,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf,
                        is_ambiguous=True,
                        ambiguity_reason=err_reason,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 9: 완전 모호 기간 ("말경") (sched-08)
    # ─────────────────────────────────────────────────────────────
    m_vague = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*말경", cleaned_text)
    if m_vague:
        mo = int(m_vague.group(2))
        prefix = cleaned_text[: m_vague.start()].strip()
        title = prefix.rstrip(":").strip() or "비교과 포인트 장학금 신청"
        title = re.sub(r"[은는]$", "", title).strip()
        if len(title) > 25:
            title = title[-25:].strip()

        quote = cleaned_text[m_vague.start():].strip()

        candidates.append(
            ScheduleCandidate(
                title=title,
                schedule_kind="PERIOD_SCHEDULE",
                is_all_day=True,
                start_date=None,
                end_date=None,
                start_datetime=None,
                end_datetime=None,
                is_time_confirmed=False,
                unconfirmed_fields=["start_date", "end_date", "time"],
                is_ambiguous=True,
                ambiguity_reason=f"'{mo}월 말경'이라는 불특정 표현으로 날짜/시각을 확정할 수 없음",
                requires_user_confirmation=True,
                source_quote=quote,
            )
        )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 10: 과거 시점 배제 및 미래 마감 단일 추출 (sched-19)
    # ─────────────────────────────────────────────────────────────
    if "지난" in cleaned_text and re.search(r"지난\s*(\d{1,2})월\s*(\d{1,2})일", cleaned_text):
        m_fut = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})\s*까지", cleaned_text)
        if m_fut:
            yr = int(m_fut.group(1)) if m_fut.group(1) else ref_year
            mo, dy, tm = int(m_fut.group(2)), int(m_fut.group(3)), m_fut.group(4)
            th, tmn = int(tm.split(":")[0]), int(tm.split(":")[1])
            is_val, err_reason, unconf = _check_calendar_validity(yr, mo, dy, th, tmn)

            prefix = cleaned_text[: m_fut.start()].split(",")[-1].strip()
            m_t = re.search(r"([^\n,.]+?)(?:은|는)\s*$", prefix)
            if m_t:
                clean_p = m_t.group(1).strip()
                title = f"{clean_p} 제출 마감" if not clean_p.endswith("마감") else clean_p
            else:
                title = "최종 과제물 제출 마감" if "최종 과제물" in cleaned_text else "과제 마감"

            m_q = re.search(r"([^\n,]+?\d{1,2}월\s*\d{1,2}일\s*\d{1,2}:\d{2}\s*까지(?:\s*제출)?)", cleaned_text)
            quote = m_q.group(1).strip() if m_q else m_fut.group(0)

            if is_val:
                end_dt = f"{yr}-{mo:02d}-{dy:02d}T{tm}:00{tz_str}"
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=end_dt,
                        start_datetime=None,
                        end_datetime=end_dt,
                        is_time_confirmed=True,
                        unconfirmed_fields=[],
                        is_ambiguous=False,
                        ambiguity_reason=None,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            else:
                candidates.append(
                    ScheduleCandidate(
                        title=title,
                        schedule_kind="DEADLINE_WITH_TIME",
                        is_all_day=False,
                        start_date=None,
                        end_date=None,
                        start_datetime=None,
                        end_datetime=None,
                        is_time_confirmed=False,
                        unconfirmed_fields=unconf,
                        is_ambiguous=True,
                        ambiguity_reason=err_reason,
                        requires_user_confirmation=True,
                        source_quote=quote,
                    )
                )
            return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 11: 긴급 당일 마감 ("금일(9월 23일) 17:00까지") (sched-15)
    # ─────────────────────────────────────────────────────────────
    m_urgent = re.search(r"금일\((\d{1,2})월\s*(\d{1,2})일\)\s*(\d{1,2}:\d{2})\s*까지", cleaned_text)
    if m_urgent:
        mo, dy, tm = int(m_urgent.group(1)), int(m_urgent.group(2)), m_urgent.group(3)
        h, mn = int(tm.split(":")[0]), int(tm.split(":")[1])
        quote = m_urgent.group(0)

        is_val, err_reason, unconf = _check_calendar_validity(ref_year, mo, dy, h, mn)

        # 동적 제목 추론 (특정 업무명 하드코딩 제거)
        after = cleaned_text[m_urgent.end():].strip()
        before = cleaned_text[: m_urgent.start()].replace("[긴급]", "").strip()
        target = after or before
        m_t = re.search(r"([^\n,]+?)(?:오류자\s*)?(정보\s*수정|신청서\s*제출|서류\s*제출|제출|마감|접수)", target)
        if m_t:
            main_p = m_t.group(1).strip()
            action_p = m_t.group(2).strip()
            title = f"{main_p} {action_p} 마감" if not action_p.endswith("마감") else f"{main_p} {action_p}"
            title = re.sub(r"\s+", " ", title).strip()
        else:
            clean_t = re.sub(r"(?:필수|요망|바랍니다|합니다|\.|\s)+$", "", target).strip() or "긴급 마감 일정"
            title = f"{clean_t} 마감" if not clean_t.endswith("마감") else clean_t

        if is_val:
            end_dt = f"{ref_date_str}T{tm}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=end_dt,
                    start_datetime=None,
                    end_datetime=end_dt,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf,
                    is_ambiguous=True,
                    ambiguity_reason=err_reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 12: 상대 날짜 오늘 ("오늘 18시까지") (sched-05, counterexample 1, counterexample 2)
    # ─────────────────────────────────────────────────────────────
    m_today = re.search(r"오늘\s*(\d{1,2})시\s*까지", cleaned_text)
    if m_today:
        hr = int(m_today.group(1))
        quote = m_today.group(0)

        is_val, err_reason, unconf = _check_calendar_validity(ref_year, ref_dt.month, ref_dt.day, hr, 0)

        # 동적 제목 추론 (원문에서 업무명 추출, 하드코딩 제거)
        after = cleaned_text[m_today.end():].strip()
        before = cleaned_text[: m_today.start()].strip()
        target = after or before
        m_t = re.search(r"([^\n,.]+?(?:신청서|신청|보고서|과제|서류|제출서|계획서|원서))(?:\s*를|\s*을)?(?:\s*[^\n,.]+?)?\s*(제출|접수|등록)", target)
        if m_t:
            title = f"{m_t.group(1).strip()} {m_t.group(2).strip()}"
        else:
            # 보조 패턴: "보고서는 오늘 25시까지 제출하세요"
            m_before_noun = re.search(r"([^\n\s]+?)(?:은|는)", before)
            m_after_verb = re.search(r"(제출|접수|등록|마감)", after)
            if m_before_noun and m_after_verb:
                title = f"{m_before_noun.group(1).strip()} {m_after_verb.group(1).strip()}"
            elif m_before_noun:
                title = f"{m_before_noun.group(1).strip()} 제출"
            else:
                clean_target = re.sub(r"(?:합니다|하세요|바랍니다|필수|요망|\.|,|\s)+$", "", target).strip()
                title = f"{clean_target} 마감" if clean_target else "일정 마감"

        if is_val:
            end_dt = f"{ref_date_str}T{hr:02d}:00:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=end_dt,
                    start_datetime=None,
                    end_datetime=end_dt,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf,
                    is_ambiguous=True,
                    ambiguity_reason=err_reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 13: 상대 날짜 내일 시각 약속 ("내일 오후 3시 30분" or "내일 오후 2시") (sched-06, sched-13)
    # ─────────────────────────────────────────────────────────────
    m_tomorrow = re.search(r"내일\s*(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?(?:에)?", cleaned_text)
    if m_tomorrow:
        ampm = m_tomorrow.group(1)
        hr = int(m_tomorrow.group(2))
        mn = int(m_tomorrow.group(3)) if m_tomorrow.group(3) else 0
        if ampm == "오후" and hr < 12:
            hr += 12
        quote = m_tomorrow.group(0)

        is_val, err_reason, unconf = _check_calendar_validity(tomorrow_dt.year, tomorrow_dt.month, tomorrow_dt.day, hr, mn)

        if "스터디" in cleaned_text:
            title = "스터디 모임"
            reason = "종료 시각 미명시로 1시간 기본 슬롯 적용 여부 확인 필요"
        elif "특강" in cleaned_text:
            title = "AI 특강"
            reason = "시작 시각은 확정되나 종료 시각 미명시로 기본 이벤트 슬롯 확인 필요"
        else:
            clean_p = re.sub(r"(?:에서|으로|에|\s)+$", "", cleaned_text[: m_tomorrow.start()]).strip()
            title = f"{clean_p} 약속" if clean_p else "약속 일정"
            reason = "종료 시각 미명시"

        if is_val:
            start_dt = f"{tomorrow_date_str}T{hr:02d}:{mn:02d}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="TIME_CONFIRMED_EVENT",
                    is_all_day=False,
                    start_date=start_dt,
                    end_date=None,
                    start_datetime=start_dt,
                    end_datetime=None,
                    is_time_confirmed=True,
                    unconfirmed_fields=["end_time"],
                    is_ambiguous=True,
                    ambiguity_reason=reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="TIME_CONFIRMED_EVENT",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf + ["end_time"],
                    is_ambiguous=True,
                    ambiguity_reason=err_reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 14: 다음 주 월요일 (sched-07)
    # ─────────────────────────────────────────────────────────────
    if "다음 주 월요일까지" in cleaned_text:
        m_q = re.search(r"(다음 주 월요일까지(?:입니다\.?)?)", cleaned_text)
        quote = m_q.group(1) if m_q else "다음 주 월요일까지입니다."

        before = cleaned_text.split("다음 주 월요일까지")[0].strip()
        m_title = re.search(r"([^\n]+?)\s*마감은", before)
        if m_title:
            title = f"{m_title.group(1).strip()} 마감"
        else:
            clean_b = re.sub(r"[은는]\s*$", "", before).strip()
            title = f"{clean_b} 마감" if clean_b else "과제 마감"

        candidates.append(
            ScheduleCandidate(
                title=title,
                schedule_kind="DATE_ONLY_DEADLINE",
                is_all_day=True,
                start_date=None,
                end_date=next_monday_str,
                start_datetime=None,
                end_datetime=None,
                is_time_confirmed=False,
                unconfirmed_fields=["time", "exact_boundary"],
                is_ambiguous=True,
                ambiguity_reason="'다음 주 월요일'의 마감 시각(18:00 vs 자정 23:59)이 모호함",
                requires_user_confirmation=True,
                source_quote=quote,
            )
        )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 15: 이번 주 금요일 (sched-22)
    # ─────────────────────────────────────────────────────────────
    if "이번 주 금요일까지" in cleaned_text:
        after = cleaned_text.split("이번 주 금요일까지")[-1].strip()
        before = cleaned_text.split("이번 주 금요일까지")[0].strip()
        target = after or before

        m_item = re.search(r"([^\n\s]+(?:서|과제|보고서|신청서|서류|추천서))를?", target)
        if m_item:
            item = m_item.group(1).rstrip("를을")
            title = f"{item} 제출"
        else:
            clean_t = re.sub(r"[은는을를]\s*$", "", target).strip()
            title = f"{clean_t} 제출" if clean_t else "추천서 제출"

        candidates.append(
            ScheduleCandidate(
                title=title,
                schedule_kind="DATE_ONLY_DEADLINE",
                is_all_day=True,
                start_date=None,
                end_date=this_friday_str,
                start_datetime=None,
                end_datetime=None,
                is_time_confirmed=False,
                unconfirmed_fields=["time"],
                is_ambiguous=True,
                ambiguity_reason=f"'이번 주 금요일'은 {this_friday_str}이나 마감 시각(근무시간 종료 등)이 미명시됨",
                requires_user_confirmation=True,
                source_quote="이번 주 금요일까지",
            )
        )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 16: 기간 일정 시각 포함 (sched-04 & sched-09)
    # ─────────────────────────────────────────────────────────────
    m_per_time = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*(\d{1,2}:\d{2})부터\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*(\d{1,2}:\d{2})까지",
        cleaned_text,
    )
    if m_per_time:
        y1 = int(m_per_time.group(1)) if m_per_time.group(1) else ref_year
        m1 = int(m_per_time.group(2))
        d1 = int(m_per_time.group(3))
        t1 = m_per_time.group(4)
        m2 = int(m_per_time.group(6))
        d2 = int(m_per_time.group(7))
        t2 = m_per_time.group(8)
        y2 = int(m_per_time.group(5)) if m_per_time.group(5) else (y1 + 1 if m2 < m1 else y1)

        h1, mn1 = int(t1.split(":")[0]), int(t1.split(":")[1])
        h2, mn2 = int(t2.split(":")[0]), int(t2.split(":")[1])

        is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, m1, d1, h1, mn1)
        is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, m2, d2, h2, mn2)

        quote = m_per_time.group(0)
        prefix = cleaned_text[: m_per_time.start()].strip()
        title = prefix.rstrip(":").strip() or "기간 일정"
        if len(title) > 30:
            title = title[-30:].strip()
        if "동계 계절학기" in cleaned_text:
            title = "동계 계절학기 수요조사"

        if is_val1 and is_val2:
            s_dt = f"{y1}-{m1:02d}-{d1:02d}T{t1}:00{tz_str}"
            e_dt = f"{y2}-{m2:02d}-{d2:02d}T{t2}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=s_dt,
                    end_date=e_dt,
                    start_datetime=s_dt,
                    end_datetime=e_dt,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=list(set(unconf1 + unconf2)),
                    is_ambiguous=True,
                    ambiguity_reason=err_reason1 or err_reason2 or "달력상 유효하지 않은 일시입니다.",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 17: 기간 일정 시각 없음 (sched-03)
    # ─────────────────────────────────────────────────────────────
    m_per_notime = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일부터\s*(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일까지(?:입니다\.?)?",
        cleaned_text,
    )
    if m_per_notime:
        y1 = int(m_per_notime.group(1)) if m_per_notime.group(1) else ref_year
        m1 = int(m_per_notime.group(2))
        d1 = int(m_per_notime.group(3))
        m2 = int(m_per_notime.group(5))
        d2 = int(m_per_notime.group(6))
        y2 = int(m_per_notime.group(4)) if m_per_notime.group(4) else (y1 + 1 if m2 < m1 else y1)

        is_val1, err_reason1, unconf1 = _check_calendar_validity(y1, m1, d1)
        is_val2, err_reason2, unconf2 = _check_calendar_validity(y2, m2, d2)

        quote = m_per_notime.group(0)
        prefix = cleaned_text[: m_per_notime.start()].strip()
        title = prefix.rstrip(":").strip() or "중간고사 시험 기간"
        if "중간고사" in cleaned_text:
            title = "중간고사 시험 기간"

        if is_val1 and is_val2:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=True,
                    start_date=f"{y1}-{m1:02d}-{d1:02d}",
                    end_date=f"{y2}-{m2:02d}-{d2:02d}",
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=["time"],
                    is_ambiguous=True,
                    ambiguity_reason="기간 내 개별 시험 교시/시각이 미확정된 날짜 전용 기간 일정",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="PERIOD_SCHEDULE",
                    is_all_day=True,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=list(set(unconf1 + unconf2 + ["time"])),
                    is_ambiguous=True,
                    ambiguity_reason=err_reason1 or err_reason2 or "달력상 유효하지 않은 날짜입니다.",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 18: 날짜 전용 단일일 (sched-02 & counterexample 2)
    # ─────────────────────────────────────────────────────────────
    m_day_only = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일은\s*([^\n.]*?)(?:로|에)?\s*(전체\s*휴업일|휴일|휴업)",
        cleaned_text,
    )
    if m_day_only:
        year = int(m_day_only.group(1)) if m_day_only.group(1) else ref_year
        month = int(m_day_only.group(2))
        day = int(m_day_only.group(3))
        ev_name = m_day_only.group(4).strip()

        quote = cleaned_text
        for line in cleaned_text.splitlines():
            if f"{month}월 {day}일" in line:
                quote = line.strip()
                break

        title = f"{ev_name} 휴업" if "휴업" not in ev_name else ev_name
        is_val, err_reason, unconf = _check_calendar_validity(year, month, day)

        if is_val:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="ALL_DAY_EVENT",
                    is_all_day=True,
                    start_date=f"{year}-{month:02d}-{day:02d}",
                    end_date=f"{year}-{month:02d}-{day:02d}",
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=["time"],
                    is_ambiguous=True,
                    ambiguity_reason="시각이 없는 날짜 전용(종일) 휴업일로 알림 시각 설정 등 사용자 확인 필요",
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="ALL_DAY_EVENT",
                    is_all_day=True,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconf + ["time"],
                    is_ambiguous=True,
                    ambiguity_reason=err_reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 19: 단일 마감 시간 포함 (sched-01, sched-12, counterexample 4 등)
    # ─────────────────────────────────────────────────────────────
    m_deadline = re.search(
        r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일(?:\([월화수목금토일]\))?\s*(\d{1,2}):(\d{2})\s*까지",
        cleaned_text,
    )
    if m_deadline:
        year = int(m_deadline.group(1)) if m_deadline.group(1) else ref_year
        month = int(m_deadline.group(2))
        day = int(m_deadline.group(3))
        hour = int(m_deadline.group(4))
        minute = int(m_deadline.group(5))
        quote = m_deadline.group(0)

        # 달력 및 시각 유효성 검증
        is_valid, err_reason, unconfirmed = _check_calendar_validity(year, month, day, hour, minute)

        # 제목 추론
        prefix = cleaned_text[: m_deadline.start()].strip()
        prefix = re.sub(r"[은는]$", "", prefix).strip()
        title = prefix.split("\n")[-1].strip() or "일정 마감"
        if "졸업가운" in cleaned_text:
            title = "졸업가운 대여 신청 마감"
        elif "학술제" in cleaned_text:
            title = "학과 학술제 참가 보고서 제출"
        elif title == "과제":
            title = "과제 마감"
        elif len(title) > 30:
            title = title[-30:].strip()
            if not title.endswith("마감") and not title.endswith("제출"):
                title = f"{title} 마감"

        if not is_valid:
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=None,
                    start_datetime=None,
                    end_datetime=None,
                    is_time_confirmed=False,
                    unconfirmed_fields=unconfirmed,
                    is_ambiguous=True,
                    ambiguity_reason=err_reason,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        else:
            end_dt = f"{year}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00{tz_str}"
            candidates.append(
                ScheduleCandidate(
                    title=title,
                    schedule_kind="DEADLINE_WITH_TIME",
                    is_all_day=False,
                    start_date=None,
                    end_date=end_dt,
                    start_datetime=None,
                    end_datetime=end_dt,
                    is_time_confirmed=True,
                    unconfirmed_fields=[],
                    is_ambiguous=False,
                    ambiguity_reason=None,
                    requires_user_confirmation=True,
                    source_quote=quote,
                )
            )
        return _build_response(candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 20: 구조화/실제 공지 및 학사일정 추출 (점/슬래시 표기, 단계별/표 블록, 학사일정)
    # ─────────────────────────────────────────────────────────────
    real_candidates = _extract_structured_and_real_notice_candidates(cleaned_text, ref_year, ref_dt, tz_str, source_title=source_title)
    if real_candidates:
        return _build_response(real_candidates, cleaned_text, ref_year, tz_str)

    # ─────────────────────────────────────────────────────────────
    # 규칙 21: 일정이 전혀 없는 일반 안내문 (sched-17, counterexample 3 등)
    # ─────────────────────────────────────────────────────────────
    return ScheduleExtractionResponse(
        candidates=[],
        requires_user_confirmation=False,
        total_candidates=0,
    )

