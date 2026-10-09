# CampusMate 홈서버 데이터 운영 전략 (2026-10-08 수집, 2026-10-09 완료)

운영 주소: **https://hschatbot.jwlee.dev**. 2026-10-08 `/health` 정상 응답과
`/api/query` 실제 답변을 확인했다. 응답의 모델명은 **gemini-3.5-flash-lite**다.
과거 Cloudtype 문서는 이전 배포 기록이다.

## 최종 완료 결과 (2026-10-09)

- Git 최신 `myrepo/main` **29037bf**까지 반영했다.
- **1,485문서 / 6,886청크**를 새 DB에 적재하고 기본 로컬 DB·JSON·manifest를 교체했다.
- 제목만 있는 문서는 **202건 → 3건**으로 줄었다. 빈 이미지 1건과 미지원 파일 2건이다.
- ID/본문 해시 동기화 검사: 누락·추가·오래된 본문·검증 불가능 문서 **모두 0건**.
- 실제 검색 검증: 최신 장학, 이미지 공지, 아침밥, 성적 FAQ, 자퇴원, 10월 중간고사 **6/6 통과**.
  API 기본 검색 개수와 같은 top_k=3으로 출처와 필수 본문을 확인했다. LLM 생성 평가는 포함하지 않는다.
- 관련 회귀 테스트 **163개 통과**. 공식 안내를 무관한 동년 공지보다 우선하고,
  요청 날짜가 담긴 청크를 찾도록 검색을 보완했다. 과거 변경 공지를 요청하면 현행 안내를 강제하지 않는다.
- 후보 묶음: `data/knowledge_snapshots/20261009T053728Z-15405409/`.
  검색 결과는 그 폴더의 `retrieval_report.json`, 동기화 결과는 `sync_report.json`에 있다.
- 이전 로컬 자료: `backups/knowledge-20261009T054044Z-9fb8e9fa/`에 보존했다.
- 홈서버 DB 교체 및 예약 작업 설치는 접속 정보가 없어 실행하지 않았다.
  운영 사이트에서 확인한 기존 청크 수는 3,447개였으며 로컬 완료와 구분한다.

## 확인한 문제와 이번 조치

기존 서비스 지식은 1,366문서 / 3,447검색 청크이며 최신 공지 등록일은 9월 15일이었다.
Git에 올라오는 최신 안내·FAQ와 통합 JSON/색인이 연결되지 않았다.
특히 식단은 9월 14~20일 자료가 남아 있었고, 최신 원본에는 10월 5~11일 자료가 있었다.
통합 공지 202건은 이미지가 있으면서도 제목만 검색할 수 있는 상태였다.

- `myrepo/main`의 최신 커밋 `137a39a`를 fast-forward로 반영했다.
- 최근 일반 공지는 9월 1일까지 목록을 확인하고 상세 213건을 새로 읽었다.
  기존 아카이브 960건에서 1,079건으로 늘었다. 장애학생지원·AI 게시판은 같은 기간에 새 글이 없었다.
- 상시 안내 144건, FAQ 179건, 서식 57건을 통합 입력에 연결했다.
  안내·서식의 첨부파일을 재확인하고 최근 공지·기존 이미지 공지를 보강했다.
- 최신 raw 안내/서식/공지와 보강본을 모두 통합하도록 수정했다.
  원문 HTML과 미디어 링크가 같을 때 OCR을 보존하고, 실제 정정이 확인되면 최신 원문을 채택한다.
- 새 DB를 별도 디렉터리에 만들고 문서 ID/본문 해시/잔존 청크를 검증하는 명령을 추가했다.

이 작업의 홈서버 반영 여부는 별도 확인해야 한다. 로컬 DB 구축이 운영 DB 갱신을 의미하지 않는다.
원격 반영에는 SSH 주소, 저장소 경로, 실행 방식이 필요하다.

## 정기 갱신 정책

| 자료 | 주기 | 범위·처리 |
|---|---|---|
| 일반·장애학생지원·AI 공지 | 매일 06:00 KST | 최근 35일을 다시 확인해 새 글과 정정을 수집; `--refresh` 필수 |
| 이미지·첨부가 있는 최근 공지 | 매일 공지 수집 후 | 최신 공지부터 보강; 처리 예산을 넘은 건은 다음 실행으로 넘기고 숫자를 기록 |
| 학사일정·식단 | 매일 | 연간 일정과 현재 주 식단; 미래 주 식단은 있다고 추측하지 않음 |
| 일반 안내·학사 FAQ | 14일 | 명령은 매일 실행하되 각 자료의 확인 주기로 실제 요청을 제한 |
| 학사 서식 | 초기에는 매일 목록·본문 확인 | 57건 규모; 운영량 확인 후 주 1회로 줄일 수 있음 |
| 기존 이미지 공지의 미추출 자료 | 초기 전수 보강, 이후 주 1회 | 제목만 있는 공지부터 우선 처리, 실패·암호화·미지원 상태를 기록 |
| 안내·서식 첨부 재검증 | 주 1회 | 같은 URL의 파일 변경도 다운로드 검증/파일 해시로 확인 |
| 과거 공지 백필 | 주 1회, 제한된 건수 | 기존 일반게시판은 2026년 3월부터 일부 확보한 범위; 전체 과거 공지 수집 완료로 표현하지 않음 |

현재 원본의 195개 목표 중 상시 안내 144건을 확보했다. 외부·동적 링크 22개,
별도 게시판 26개, 수동 검토 3개는 확보한 안내 본문과 구분한다.
학과·트랙 게시판, 로그인 자료, 삭제 공지는 별도 범위 확정 후 추가한다.

## 실행 순서

**수집 → 보강 → 통합 JSON → 새 Chroma 색인 → 엄격 동기화 검사 → 검색 검증 → 교체 → 외부 확인**.

```bash
# 매일: 최근 공지 우선으로 제한된 미디어 보강과 새 DB 검증
.venv/bin/python scripts/refresh_knowledge.py --enrich

# 원본을 이미 수집·보강했을 때: 네트워크 수집 없이 새 DB 생성
.venv/bin/python scripts/refresh_knowledge.py --skip-collect

# 기존 이미지 공지 전수 보강 및 최근 공지 보강
.venv/bin/python scripts/enrich_notice_archive.py --since 2026-09-15 --title-only

# 일시적 실패만 소규모 재처리 (이미 성공한 자료는 다시 추출하지 않음)
.venv/bin/python scripts/enrich_notice_archive.py --retry-failed --limit 10

# 주간 안내/서식 첨부 재검증
.venv/bin/python scripts/enrich_official_pages.py --input data/official_pages.json --output data/official_pages_enriched.json
.venv/bin/python scripts/enrich_official_pages.py --input data/official_forms.json --output data/official_forms_enriched.json
```

각 실행은 `data/knowledge_snapshots/<시간-UUID>/`에 통합 JSON, 입력 해시가 담긴 manifest,
`chroma_db/`, `sync_report.json`, `refresh_report.json`을 함께 저장한다.
`validated_candidate`는 DB 동기화가 검증됐다는 뜻이며 운영 교체 완료 표시가 아니다.
수집 실패, 요청 범위까지 도달하지 못함, DB 동기화 실패는 교체를 막는다.
이미지·첨부의 일부 추출 한계와 작업 예산으로 미룬 건은 보고서에 별도로 남긴다.

서비스와 수집 작업은 같은 홈서버에서 실행한다. 정기 작업은 한 번에 하나만 실행하도록
`flock` 또는 systemd 서비스로 직렬화한다. GitHub는 코드와 감사 가능한 자료·보고서 보관에 사용하고,
변하는 Chroma SQLite/HNSW 색인은 서버의 영속 디스크에 둔다.
현재 GitHub의 두 수집 workflow는 운영 DB에 자동 반영하지 않는다.
홈서버 정기 작업을 실제 설치·검증한 뒤 중복 수집 workflow를 정리한다.
이 문서만으로 예약 작업이 활성화된 것은 아니다.

## 운영 반영 및 복구

홈서버 AI가 이어서 작업할 경우 `docs/home_server_ai_handoff_20261009.md`를 함께 전달한다.
코드·원본 JSON은 Git으로, 큰 DB 후보 묶음은 Google Drive 등의 압축파일 전달로 옮길 수 있다.
현재 SQLite는 약 258MiB로 GitHub 일반 Git의 100MiB 파일 제한을 넘는다.
운영 DB를 Drive 동기화 경로에서 실행하지 않고, 완전히 다운로드한 묶음을 서버 로컬 디스크에 푼다.
다른 실행 환경에서는 이미 보강한 JSON으로 서버에서 다시 색인하고 검증한 뒤 적용한다.

프로세스가 열린 Chroma 디렉터리에 새 SQLite나 HNSW 파일을 복사하지 않는다.
서비스를 정지하고 이전 JSON·DB·manifest를 백업한 다음 같은 버전의 세 파일 묶음을 적용한다.
재시작 후 `/health`뿐 아니라 최신 공지 제목 질문, 현재 식단, FAQ 검색을 확인한다.
모델 이름은 `/api/query`의 `model`로 확인할 수 있다.

일반 디렉터리의 DB를 쓰는 경우, 서비스를 정지한 상태에서 다음 명령을 사용한다.
`RUN`은 생성된 후보 폴더의 실제 이름으로 바꾼다. 이 명령은 후보의 해시·동기화를 다시
검사하고 이전 자료를 `backups/`에 보존하며, 교체 오류 시 이전 경로로 복구한다.
`--server-stopped`는 운영자가 프로세스 정지를 확인했다는 표시다.

```bash
.venv/bin/python scripts/activate_knowledge_snapshot.py data/knowledge_snapshots/RUN --server-stopped
```

Docker의 마운트 루트는 rename할 수 없어 위 교체 명령의 대상이 될 수 없다.
볼륨 아래 하위 디렉터리를 쓰거나, 다음과 같이 후보 디렉터리를 별도 마운트하는 방식으로 적용한다.

Docker Compose의 `chroma_data` 볼륨은 이미지 안의
`/app/data/integrated_eval_chroma_db`를 가린다. **이미지를 다시 빌드해도 기존 볼륨 DB는 갱신되지 않는다.**
또한 현재 Docker 이미지에는 crawler/scripts와 OCR 실행 도구가 없어 별도 worker 준비가 필요하다.
홈서버의 Python 가상환경에서 먼저 수집·색인 작업을 실행하는 방식이 가장 간단하다.
다른 OS/의존성 환경에는 원본 JSON을 전달하고 그 서버에서 색인을 구축한다.

Docker를 계속 사용한다면 검증한 후보를 별도 영속 서비스 디렉터리로 복사해 연결하고
`CHROMA_PERSIST_DIR`, `NOTICES_PATH`, `CHROMA_COLLECTION_NAME=campus_knowledge`를 함께 설정한다.
기존 named volume은 백업으로 남긴다. 서비스 컨테이너에서 접근 가능한 경로로 설정해야 한다.
후보 경로를 바꾸기 전 `validated_candidate` 보고서와 검색 검증 결과를 확인한다.
문제가 생기면 이전 후보 경로로 되돌리고 서버를 재시작한다.

검증한 현재 후보를 서비스에 연결하는 Compose override 예시는 다음과 같다.
소스 코드와 후보 디렉터리를 홈서버에 전달한 후, 실제 저장소 경로에서 적용해야 한다.
후보를 `data/knowledge_runtime/20261009T053728Z-15405409/`에 복사하고 아래 설정을 적용한다.
Chroma는 잠금·metadata 파일을 쓸 수 있도록 서비스 디렉터리에 쓰기 권한이 필요하다.

```yaml
services:
  backend:
    volumes:
      - ./data/knowledge_runtime/20261009T053728Z-15405409:/app/knowledge
    environment:
      CHROMA_PERSIST_DIR: /app/knowledge/chroma_db
      CHROMA_COLLECTION_NAME: campus_knowledge
      NOTICES_PATH: /app/knowledge/unified_campus_knowledge.json
```

원본 후보는 검증 기록으로 보존하고 서비스 내부 파일 변경과 분리한다.

초기에는 짧은 정지·교체 방식을 사용한다. 사용자가 늘어나면 두 API 인스턴스를 준비해
새 버전의 검색·답변을 확인한 뒤 프록시를 전환하는 방식으로 발전시킨다.
최근 성공 버전 7개와 주간 백업 4개를 우선 보존하고, 정리 작업은 실제 용량을 확인해 적용한다.

## 성공 기준과 남은 범위

DB의 `missing_in_db`, `extra_in_db`, `stale_in_db`, `unverifiable_in_db`가 모두 0이어야 한다.
최근 수집 범위의 최신 등록일과 마지막 확인시각, title_only 잔여 건수,
미디어 실패·보류 건수를 기록한다. 웹사이트의 청크 수만으로 최신성은 판정하지 않는다.
필수 검색 검증은 최신 장학 공지, 이번 주 식단, 성적 FAQ, 자퇴원 서식이다.
이미지로만 제공한 공지는 OCR 성공 내용까지 확인한다.

과거 공지의 오래된 마감일이 최신 신청으로 오인되는 문제와 짧은 일반 질문의 검색 품질은
자료 적재와 별도로 평가해야 한다. 이번 작업에서 모든 미지원 첨부와 학내 전체 자료가
확보됐다고 판단하지 않는다.
