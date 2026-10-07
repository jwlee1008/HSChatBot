# 일정 기능 포함 Cloudtype 배포 가능성 — 2026-09-26

## 판정

**기술적으로 가능. 현재 코드를 그대로 업로드해서 데이터 보존까지 보장하는 배포는 아직 준비되지 않음.** 기능 삭제나 앱 재개발이 필수는 아니다. Cloudtype을 유지하는 경우 별도 PostgreSQL에 계정·세션·일정을 저장하도록 이식하는 경로가 문서상 지원과 가장 잘 맞는다. 이 보고서는 코드 및 공식 문서 조사이며 Cloudtype 신규 서비스 생성/배포 실증 결과가 아니다.

## 확인한 제약

1. 앱의 SQLite 연결은 AUTH_DB_PATH의 로컬 파일, WAL, PRAGMA, sqlite3.Row를 사용한다. 인증/일정 서비스에 SQLite SQL 파라미터, 예외 처리와 BEGIN IMMEDIATE가 직접 들어 있다. DATABASE_URL만 설정해서 PostgreSQL로 바뀌지 않는다.
2. 기존 서비스는 Python 3.12/1GB/프리티어이며 디스크 미연결(직전 대시보드 조사). 공식 일반 문제 문서도 앱 파일 영속 저장 제약을 안내한다. 앱 영속 볼륨 지원이 별도 확인되지 않는 한 현재 SQLite를 운영 저장소로 인정할 수 없다. 유료 전환만으로 해결된다고 가정하지 않는다.
3. Cloudtype은 별도 PostgreSQL DB 서비스를 지원하고 해당 DB의 중지·재배포 시 데이터를 보존한다고 안내한다. 앱과 같은 환경의 내부 주소로 연결할 수 있다. DB 서비스 삭제 시 데이터는 제거된다.
4. Cloudtype 공식 Docker 문서는 ARM 런타임 미지원, 기본 이미지 2GB/유료 5GB 제한, non-root 실행 관련 설정을 안내한다. 기존 Linux ARM64 빌드 통과는 AMD64 실증이 아니다. AMD64 이미지 실제 크기는 이번 조사에서 측정하지 않았다.
5. 현재 Dockerfile에는 USER/쓰기 디렉터리 소유권 구성이 없고 계정 DB는 /var/lib/campusmate, Compose 모델 캐시는 /root/.cache/huggingface를 가정한다. Cloudtype UID/GID에 맞춘 DB/Chroma/모델 캐시 경로와 쓰기 권한 정리가 필요하다.
6. 일정 추출기는 규칙 기반 함수다. 추가 LLM 서버/GPU가 필요하지 않다. 무거운 요소는 기존 챗봇의 로컬 임베딩과 선택적인 로컬 생성 모델이다. Gemini 모드도 임베딩은 CPU에서 로드한다. 1GB 적합성이나 권장 메모리를 실측 없이 단정하지 않는다.
7. Chroma seed는 로컬 약 71MB, 원문 JSON은 약 4.6MB다. 현재처럼 버전 고정 seed를 이미지에서 재생성 가능하게 배포할 수 있다. 실행 중 색인 갱신을 영구 보존하는 기능은 별도 저장/반영 설계가 필요하다. 임베딩 모델은 재기동 시 다운로드·캐시 소실·cold start가 문제가 될 수 있어 모델 포함 이미지와 시작 시 다운로드 중 실제 크기/시간을 측정해 선택한다.
8. 프리티어는 매일 중지된다. 제한된 시연과 상시 운영을 구분해야 한다. 기존 브라우저 배너/Notification 버튼과 브라우저 종료 후 예약 Push는 다른 기능이다. 후자는 현재 구현돼 있지 않다.

## 제안 구조

Cloudtype 앱 서비스 1개: React 정적 산출물 + FastAPI + 일정 추출 + 기존 RAG.
Cloudtype PostgreSQL 서비스 1개: users, sessions, personal_schedules, migration metadata.
LLM 제공자: 기존 Gemini 연결을 확인해 유지하는 경로. 키 값·지원 모델·실제 호출은 이번에 검증하지 않음.
Chroma: 기존 seed를 배포 버전에 포함하고 writable 디렉터리에서 사용. 초기에 서버에서 직접 재수집/색인 갱신하지 않음.

## 필요한 변경 및 완료 조건

- DB 연결/마이그레이션/인증/일정 저장 계층을 PostgreSQL용으로 구현. API, React 화면, 추출기는 가능한 유지.
- PATCH 동시 수정은 PostgreSQL 트랜잭션과 행 잠금 또는 버전 충돌 검출로 기존 데이터 유실 방지 계약 유지. boolean/UTC/마이크로초/nullable 필드 계약 보존.
- PostgreSQL 백업·새 DB 복원 검증 추가. 기존 sqlite_snapshot.py는 PostgreSQL 백업 도구가 아니다. 기존 사용자 데이터가 있다면 별도 이관 검증.
- Python 드라이버/잠금 파일 및 DB 환경변수, non-root 권한/캐시 경로 정리.
- AMD64 이미지 설치·pip check·API 검증과 이미지 크기 제한 확인. React는 빌드 단계에서 생성하고 같은 FastAPI 주소로 제공.
- 실제 Cloudtype 환경에서 모델 초기화, 첫 질의, 반복 질의의 메모리·시간·오류 측정. PREWARM=false나 health 200만으로 RAG 준비 완료 판정 금지.
- 회원가입→로그인→챗봇→후보 추출→확인 저장→캘린더 수정/삭제→로그아웃 검증. 앱 재시작/재배포 후 동일 계정·일정 유지, 타 사용자 접근 차단, 동시 PATCH, DB 백업 복원 확인.

## 선택지

- Cloudtype 유지 + PostgreSQL: 현재 기능 유지 가능. 저장 계층 이식과 배포 검증 필요. 권장 조사 결론.
- Cloudtype + 현재 SQLite: 앱에 쓰기 가능한 영속 볼륨이 실제 제공되고 재배포 보존이 검증되는 경우에만 대안. 현재 서비스에는 해당 근거 없음.
- 영속 디스크가 있는 별도 서버 + SQLite: 저장 계층 변경은 줄일 수 있으나 Cloudtype 유지 조건에서 벗어남.

구현 가능성과 완료 상태를 구분한다. 이번에 배포/결제/DB 생성/코드 변경/commit/push/모델 다운로드/외부 LLM 호출을 실행하지 않았다. 실제 운영 크기·비용·일정은 아직 확정하지 않았다.

## 공식 근거

- 앱 파일 영속성: https://docs.cloudtype.dev/ko/troubleshooting/common
- PostgreSQL 및 DB 데이터 보존: https://docs.cloudtype.dev/ko/developers/database
- Docker 템플릿과 UID/GID: https://docs.cloudtype.dev/ko/developers/dockerfile
- 아키텍처·이미지 크기 제한: https://docs.cloudtype.dev/ko/troubleshooting/dockerfile
- 프리티어 중지: https://docs.cloudtype.dev/ko/developers/resource
