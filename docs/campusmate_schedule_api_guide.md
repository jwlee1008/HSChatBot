> 역사 기록: 2026-09-27 제품 범위가 챗봇으로 변경되었습니다. 개인 일정·인증·캘린더·알림 계획은 비활성 보관 상태입니다. 현재 범위는 `docs/campusmate_chatbot_scope_20260927.md`를 따릅니다.

# CampusMate 개인 일정 CRUD 및 사용자 격리 API 가이드 (R1-B)

문서 버전: v1.0 (2026-09-23)  
대상: 백엔드/프론트엔드 개발자 및 시스템 검수자

---

## 1. 개요 및 인증 방식

CampusMate 개인 일정 API는 한성대학교 학생 개인이 확인한 학사·장학·개인 일정을 영속적으로 저장, 조회, 수정, 삭제하는 RESTful API입니다.

- **기본 엔드포인트 접두사**: `/api/v1/schedules`
- **인증 요구사항**: 모든 엔드포인트는 R1-A에서 구현된 Opaque Bearer 세션 토큰을 필요로 합니다.
  ```http
  Authorization: Bearer <access_token>
  ```
- **소유권 격리 (BOLA/IDOR 방어)**: 모든 일정은 생성한 사용자의 계정에 귀속됩니다. 타인의 일정 UUID 또는 존재하지 않는 UUID에 대한 `GET`, `PATCH`, `DELETE` 요청은 구별 없이 동일한 안전한 `404 Not Found`(`{"detail": "일정을 찾을 수 없습니다."}`)를 반환합니다.
- **사용자 확인 계약 (`confirmed: true`)**: 일정 생성(`POST`) 및 수정(`PATCH`) 요청 시 `confirmed: true`가 필수입니다. 인공지능 추출 결과나 원문이 자동으로 저장되지 않으며, 클라이언트가 사용자의 명시적 저장/수정 승인을 거쳤음을 보증해야 합니다.

---

## 2. 5대 개인 일정 유형 (ScheduleKind) 및 날짜·시각 모델

CampusMate는 모호한 시간 표현으로 인한 오류를 방지하기 위해 5가지 엄격한 일정 유형을 정의합니다.

| `schedule_kind` | 설명 | 필수 입력 필드 | 반드시 `null`이어야 하는 필드 | 응답 계산 필드 (`is_all_day` / `is_time_confirmed`) |
|---|---|---|---|---|
| `ALL_DAY_EVENT` | 종일 행사 (예: 축제, 수강신청 기간) | `start_date`, `end_date` | `start_datetime`, `end_datetime` | `true` / `false` |
| `DATE_ONLY_DEADLINE` | 시간 미지정 날짜 마감 (예: 서류 제출일) | `end_date` | `start_date`, `start_datetime`, `end_datetime` | `false` / `false` |
| `TIME_CONFIRMED_DEADLINE` | 시각 확정 마감 (예: 18:00 마감) | `end_date`, `end_datetime` | `start_date`, `start_datetime` | `false` / `true` |
| `TIME_CONFIRMED_EVENT` | 시각 확정 행사 (예: 14:00~16:00 멘토링) | `start_date`, `end_date`, `start_datetime`, `end_datetime` | 없음 | `false` / `true` |
| `SINGLE_POINT_APPOINTMENT` | 단일 시점 약속 (예: 11:00 상담) | `start_date`, `start_datetime` | `end_date`, `end_datetime` | `false` / `true` |

### 날짜·시각 엄격 규칙
1. **시간대 고정**: 현재 지원되는 `timezone`은 `"Asia/Seoul"`(KST, UTC+09:00)뿐이며, 다른 시간대는 `422`로 거부됩니다.
2. **달력 날짜 일치 원칙**:
   - `start_datetime`과 `end_datetime`은 명시적인 타임존 오프셋을 가진 ISO 8601 문자열이어야 합니다 (naive datetime, 날짜-only, epoch 숫자 거부).
   - 모든 일시는 서버 저장 시 UTC 기준 ISO 8601로 정규화됩니다.
   - **중요**: 입력된 일시를 `Asia/Seoul` 시간대로 변환했을 때의 달력 날짜(`YYYY-MM-DD`)는 반드시 대응하는 `start_date` 또는 `end_date`와 완전히 일치해야 합니다.
     - 예: `2026-10-01T00:30:00+09:00`은 UTC로 `2026-09-30T15:30:00Z`로 저장되지만, 서울 기준 날짜는 `2026-10-01`이므로 대응 날짜 필드는 반드시 `2026-10-01`이어야 합니다. 불일치 시 `422` 반환.
3. **일시 소수점 정밀도 보존 정책**:
   - `start_datetime`과 `end_datetime`에 소수점 초(마이크로초)가 포함된 경우, 임의 절단 없이 최대 6자리 마이크로초(`.100000Z`)까지 정밀도를 온전히 보존하여 저장 및 응답합니다.
   - 절단으로 인한 `start_datetime == end_datetime` 불변식 파괴 및 저장 후 수정 불가 오류를 원천 차단합니다.
   - 소수점 초까지 동일하여 실제로 `start_datetime == end_datetime`인 행사는 `422`로 거부됩니다.
4. **그레고리력, 윤년 및 변환 범위 검증**:
   - `2026-02-29`와 같은 평년 윤일은 `422`로 거부됩니다.
   - 지원 연도 범위는 1000~9999년이며, 타임존 오프셋 변환 시 파이썬 `datetime` 한계를 초과하는 경우 500 오류가 아닌 안전한 `422`를 반환합니다.
5. **구간 유효성**: `ALL_DAY_EVENT`는 `start_date <= end_date`여야 하며, `TIME_CONFIRMED_EVENT`는 `start_datetime < end_datetime`이어야 합니다.
6. **`source_url` 엄격한 유효성 검증**:
   - `http://` 또는 `https://` 프로토콜만 허용됩니다 (`ftp`, `javascript` 등 거부).
   - 원본 문자열의 공백 및 탭(`\t`), 줄바꿈(`\n`), 캐리지 리턴(`\r`) 등 모든 제어문자는 거부됩니다 (`422`).
   - 포트 번호 검증: 숫자가 아닌 포트(`:abc`), 범위 초과(`:99999`, `:0`), 빈 포트(`:`)는 거부되며, 유효 범위(`1~65535`)의 포트만 허용됩니다 (`localhost:8000`, `127.0.0.1:8080`, `:443` 등 허용).
   - 유효한 호스트(도메인명, IPv4, localhost)가 반드시 존재해야 합니다 (`https://`, `https://not a host`, `http://?query` 등은 `422`로 차단).
   - `null` 및 빈 문자열(`""`)은 필드 미설정 또는 초기화(`NULL`)로 처리됩니다.
   - 잘못된 URL로의 `PATCH` 실패 시 기존 레코드(`source_url`, `updated_at` 등)는 전혀 변경되지 않습니다.
   - 서버는 저장만 수행하며 해당 URL로의 외부 네트워크 조회를 시도하지 않습니다.

---

## 3. 엔드포인트 명세 및 요청 예시

### 3.1 일정 생성 (`POST /api/v1/schedules`)
- **Status**: `201 Created`
- **Request Headers**: `Authorization: Bearer <token>`, `Content-Type: application/json`

#### 유형 1: 종일 행사 (`ALL_DAY_EVENT`)
```http
POST /api/v1/schedules HTTP/1.1
Host: localhost:8000
Authorization: Bearer test_access_token_12345
Content-Type: application/json

{
  "title": "2학기 수강신청 기간",
  "description": "2026학년도 2학기 본 수강신청",
  "course_name": null,
  "schedule_kind": "ALL_DAY_EVENT",
  "start_date": "2026-10-01",
  "end_date": "2026-10-03",
  "timezone": "Asia/Seoul",
  "source_url": "https://www.hansung.ac.kr/notice/1",
  "source_title": "2학기 수강신청 안내",
  "extracted_quote": "수강신청 기간은 10월 1일부터 10월 3일까지입니다.",
  "is_completed": false,
  "priority": "HIGH",
  "confirmed": true
}
```

#### 유형 2: 날짜 전용 마감 (`DATE_ONLY_DEADLINE`)
```json
{
  "title": "졸업유예 신청서 제출",
  "schedule_kind": "DATE_ONLY_DEADLINE",
  "end_date": "2026-10-10",
  "confirmed": true
}
```

#### 유형 3: 시각 확정 마감 (`TIME_CONFIRMED_DEADLINE`)
```json
{
  "title": "국가장학금 신청 마감",
  "schedule_kind": "TIME_CONFIRMED_DEADLINE",
  "end_date": "2026-10-15",
  "end_datetime": "2026-10-15T18:00:00+09:00",
  "confirmed": true
}
```

#### 유형 4: 시각 확정 행사 (`TIME_CONFIRMED_EVENT`)
```json
{
  "title": "AI 산학 프로젝트 멘토링",
  "course_name": "캡스톤디자인",
  "schedule_kind": "TIME_CONFIRMED_EVENT",
  "start_date": "2026-10-20",
  "end_date": "2026-10-20",
  "start_datetime": "2026-10-20T14:00:00+09:00",
  "end_datetime": "2026-10-20T16:00:00+09:00",
  "confirmed": true
}
```

#### 유형 5: 단일 시점 약속 (`SINGLE_POINT_APPOINTMENT`)
```json
{
  "title": "지도교수 면담",
  "schedule_kind": "SINGLE_POINT_APPOINTMENT",
  "start_date": "2026-10-22",
  "start_datetime": "2026-10-22T11:00:00+09:00",
  "confirmed": true
}
```

#### 성공 응답 (`201 Created`)
```json
{
  "id": "e4b2d1c9-715a-4b9e-b83b-31215b2e9d21",
  "user_id": "a1c2d3e4-5678-90ab-cdef-1234567890ab",
  "title": "2학기 수강신청 기간",
  "description": "2026학년도 2학기 본 수강신청",
  "course_name": null,
  "schedule_kind": "ALL_DAY_EVENT",
  "is_all_day": true,
  "is_time_confirmed": false,
  "start_date": "2026-10-01",
  "end_date": "2026-10-03",
  "start_datetime": null,
  "end_datetime": null,
  "timezone": "Asia/Seoul",
  "source_url": "https://www.hansung.ac.kr/notice/1",
  "source_title": "2학기 수강신청 안내",
  "extracted_quote": "수강신청 기간은 10월 1일부터 10월 3일까지입니다.",
  "is_completed": false,
  "priority": "HIGH",
  "user_confirmed_at": "2026-09-23T07:45:00.000000Z",
  "created_at": "2026-09-23T07:45:00.000000Z",
  "updated_at": "2026-09-23T07:45:00.000000Z"
}
```

---

### 3.2 일정 목록 및 캘린더 조회 (`GET /api/v1/schedules`)
- **Status**: `200 OK`
- **Query Parameters**:
  - `date_from` (string, `YYYY-MM-DD`, 선택): 조회 시작일.
  - `date_to` (string, `YYYY-MM-DD`, 선택): 조회 종료일.
    - **규칙**: `date_from`과 `date_to`는 **둘 다 제공되거나 둘 다 생략**되어야 합니다. 하나만 제공되거나 `date_from > date_to`인 경우 `422`를 반환합니다.
    - **기간 겹침 로직**: 일정의 유효 기간과 `[date_from, date_to]` 범위가 겹치면 반환됩니다 (월 경계를 넘는 다일 행사 포함).
  - `is_completed` (boolean, 선택): 완료 여부 필터.
  - `priority` (string, 선택): 중요도 필터 (`HIGH`, `MEDIUM`, `LOW`).
  - `limit` (integer, 기본 50, 1~100): 페이지당 개수.
  - `offset` (integer, 기본 0, 0 이상): 페이지 오프셋.
- **정렬 기준**: 일정 기준 날짜(`COALESCE(start_date, end_date)`) 오름차순, 동률 시 `id` 오름차순.

#### 요청 예시
```http
GET /api/v1/schedules?date_from=2026-10-01&date_to=2026-10-31&priority=HIGH&limit=20&offset=0 HTTP/1.1
Authorization: Bearer <token>
```

#### 성공 응답 (`200 OK`)
```json
{
  "items": [
    {
      "id": "e4b2d1c9-715a-4b9e-b83b-31215b2e9d21",
      "user_id": "a1c2d3e4-5678-90ab-cdef-1234567890ab",
      "title": "2학기 수강신청 기간",
      "description": "2026학년도 2학기 본 수강신청",
      "course_name": null,
      "schedule_kind": "ALL_DAY_EVENT",
      "is_all_day": true,
      "is_time_confirmed": false,
      "start_date": "2026-10-01",
      "end_date": "2026-10-03",
      "start_datetime": null,
      "end_datetime": null,
      "timezone": "Asia/Seoul",
      "source_url": "https://www.hansung.ac.kr/notice/1",
      "source_title": "2학기 수강신청 안내",
      "extracted_quote": "수강신청 기간은 10월 1일부터 10월 3일까지입니다.",
      "is_completed": false,
      "priority": "HIGH",
      "user_confirmed_at": "2026-09-23T07:45:00.000000Z",
      "created_at": "2026-09-23T07:45:00.000000Z",
      "updated_at": "2026-09-23T07:45:00.000000Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 3.3 단건 상세 조회 (`GET /api/v1/schedules/{schedule_id}`)
- **Status**: `200 OK`
- 본인 소유의 일정이 존재하면 단건 `ScheduleResponse` 반환.
- 타인 소유이거나 존재하지 않는 UUID는 `404 Not Found`.

---

### 3.4 부분 수정 (`PATCH /api/v1/schedules/{schedule_id}`)
- **Status**: `200 OK`
- **Request Body**: `SchedulePatchRequest`
  - `confirmed: true` 필수.
  - `confirmed` 외에 변경 필드가 0개이면 `422 Unprocessable Content`.

#### PATCH 동작 원칙
1. **미전송 필드 보존**: 요청 본문에 포함되지 않은 필드는 기존 DB 값을 그대로 보존합니다.
2. **명시적 null 처리**:
   - `description`, `course_name`, `source_url`, `source_title`, `extracted_quote`: `null`을 전송하면 DB 값이 `NULL`로 비워집니다.
   - `title`, `schedule_kind`, `timezone`, `priority`, `is_completed`: non-nullable 필드이므로 `null` 전달 시 `422`로 거부됩니다.
3. **유형 전환 시 잔여 필드 검증**:
   - 예를 들어 `TIME_CONFIRMED_EVENT`에서 `ALL_DAY_EVENT`로 전환할 때는, `schedule_kind: "ALL_DAY_EVENT"`와 함께 기존에 존재하던 `start_datetime: null`, `end_datetime: null`을 명시적으로 비워주어야 합니다.
   - 모순되는 잔여 필드가 남아 있으면 `422` 오류가 발생하며, **DB에 어떠한 부분 변경도 반영되지 않고 원자적으로 롤백**됩니다.

#### 수정 요청 예시 (설명 비우기 및 제목/완료여부 변경)
```http
PATCH /api/v1/schedules/e4b2d1c9-715a-4b9e-b83b-31215b2e9d21 HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "수정된 수강신청 일정",
  "description": null,
  "is_completed": true,
  "confirmed": true
}
```

---

### 3.5 일정 삭제 (`DELETE /api/v1/schedules/{schedule_id}`)
- **Status**: `204 No Content`
- 본인 소유의 일정 레코드를 삭제합니다.
- 타인 소유이거나 존재하지 않는 UUID는 `404 Not Found`.

---

## 4. 데이터베이스 마이그레이션 안내 (v1 -> v2)

- R1-B 마이그레이션은 SQLite `schema_migrations` 테이블을 통해 관리됩니다.
- **버전 1**: `users`, `sessions` 테이블 및 인덱스.
- **버전 2**: `personal_schedules` 테이블 및 `idx_schedules_user_id`, `idx_schedules_dates` 인덱스.
- 서버 기동(`lifespan`) 시 `init_db(config.AUTH_DB_PATH)`가 자동 호출되며, 기존 v1 데이터는 100% 보존됩니다.
- 마이그레이션 적용 후에도 이전 세션 토큰은 만료 전까지 정상적으로 유효합니다.
