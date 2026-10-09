# 홈서버 AI 작업 인계 (2026-10-09)

운영 서비스는 https://hschatbot.jwlee.dev 이다. 이 문서와 전달용 ZIP을 읽고,
홈서버의 실제 실행 환경을 확인한 다음 로컬에서 완료한 지식을 운영에 적용한다.
이 문서는 작업 인계이며, 홈서버 배포나 예약 작업이 이미 완료됐다는 뜻이 아니다.

## 완료된 작업과 전달물

- Git 기반: `myrepo/main`의 `29037bf`. 현재 브랜치는 `codex/official-information`.
- 이 작업의 변경 내용은 아직 커밋하거나 push하지 않았다. ZIP의 `source/`는 현재 작업 파일이다.
- 2026-10-08까지의 공지, 안내, FAQ, 서식을 통합해 **1,485문서 / 6,886청크**를 구축했다.
- 제목만 있는 문서는 202건에서 3건으로 줄었고, 엄격 동기화와 검색 6건을 통과했다.
- 관련 회귀 테스트 163개를 통과했다. 모델 생성의 전체 품질 평가와 구분한다.
- 운영 서버에는 적용하지 않았다. 이전 운영 `/health`의 청크 수는 3,447이었다.
- 이전 운영 응답의 모델은 `gemini-3.5-flash-lite`였다. 서버의 현재 `.env`와 모델 설정을 보존한다.
- 매일 갱신하는 홈서버 예약 작업은 아직 설치하지 않았다.

ZIP 구성:

| 경로 | 내용 |
|---|---|
| `source/` | 실행 코드, frontend 빌드, 테스트, 원본/보강 JSON, 정책, 운영 문서 |
| `changes.patch` | 기준 HEAD 대비 코드·문서 변경과 새 파일. 데이터와 DB는 제외 |
| `snapshot/` | 검증한 JSON·manifest·Chroma DB 전체·검증 보고서 |
| `handoff_manifest.json` | 전달 파일별 SHA-256, 크기, 기준 커밋 |
| `verify_transfer.py` | 압축을 푼 파일들의 해시 확인 (Python 표준 라이브러리만 사용) |

`.git`, `.env`, API 키, 가상환경, node_modules, 모델 캐시, 개인 문서, 기존 백업은 포함하지 않는다.
Chroma 파일을 GitHub 일반 Git에 올리려 하지 않는다. 현재 SQLite는 약 258MiB로
100MiB 파일 제한을 넘는다. Google Drive는 ZIP 전달 및 백업에 사용하고,
실행 중인 DB를 Drive 동기화 폴더에 두지 않는다. 다운로드를 마친 뒤 서버 로컬 디스크에 푼다.

## 서버에서 먼저 확인할 것

1. 압축을 **운영 저장소 밖의 새 디렉터리**에 풀고 `python3 verify_transfer.py`를 실행한다.
2. 저장소 경로, OS/CPU, Python/Chroma 버전, Docker 또는 직접 실행 방식,
   실제 DB 경로·컬렉션명, 서비스 정지/시작 방법을 확인한다.
3. 운영 Git 상태와 설정을 보존한다. `changes.patch`는 `git apply --check`로 적용 가능성을 먼저 확인한다.
   기준 코드가 다르면 충돌을 검토하며 병합한다. `source/`는 비교와 새 파일 복원에 사용할 수 있다.
4. `source/data/`의 원본·보강 JSON과 보고서를 서버 저장소의 `data/`에 함께 전달한다.
   데이터 JSON은 코드 patch에 포함되지 않는다. 서버에 더 최신 자료가 있으면 날짜와 원문 버전을 비교한다.
5. `snapshot/`을 서버 저장소의 `data/knowledge_snapshots/imported-20261009/`에 복사해
   전달 원본으로 보존한다. 보고서 속 Mac 절대 경로는 당시 실행 기록이며 서버 실행 경로가 아니다.

## 첫 운영 적용

OS나 의존성 환경이 다르면 전달한 **수집·OCR 결과를 사용해 서버에서 DB만 다시 생성**하는 방식을 우선한다.
기존 수집을 처음부터 다시 실행할 필요가 없다. 홈서버 가상환경과 실행 의존성을 준비한 후:

전달 DB의 검증 환경은 macOS arm64, Python 3.12.14, Chroma 1.5.9,
langchain-chroma 1.1.0이다. 임베딩은 `jhgan/ko-sroberta-multitask`의 768차원,
컬렉션은 `campus_knowledge`다. Linux에서 이 DB를 그대로 연 결과는 아직 검증하지 않았다.
로컬 sentence-transformers는 6.0.1, 저장소 requirements-lock은 6.1.0이므로
의존성 파일만으로 당시 실행 환경이 완전히 재현된다고 판단하지 않는다.

```bash
.venv/bin/python scripts/refresh_knowledge.py --skip-collect
```

새로 출력된 `data/knowledge_snapshots/<RUN>/`을 대상으로 검증한다.
전달 DB를 직접 사용하려는 경우에도 아래 두 검증을 서버에서 통과해야 한다.
서버에서 다시 생성한 DB는 입력이 같을 때 1,485문서 / 6,886청크가 기준이다.

```bash
.venv/bin/python scripts/check_data_status.py \
  --json-path data/knowledge_snapshots/<RUN>/unified_campus_knowledge.json \
  --db-path data/knowledge_snapshots/<RUN>/chroma_db \
  --collection-name campus_knowledge --strict
.venv/bin/python scripts/verify_knowledge_snapshot.py data/knowledge_snapshots/<RUN> \
  --cases data/knowledge_refresh_smoke_cases_20261008.json
```

검증 후 운영 서비스를 정지하고 DB·JSON·manifest를 백업한다. 일반 디렉터리 적용은:

```bash
.venv/bin/python scripts/activate_knowledge_snapshot.py \
  data/knowledge_snapshots/<RUN> --server-stopped
```

활성 DB/JSON 경로가 기본값과 다르면 `--active-db`, `--dataset`, `--manifest`를 지정한다.
`--server-stopped`는 자동 정지 옵션이 아니므로 실제 서비스를 먼저 정지해야 한다.

Docker는 기존 `chroma_data` named volume이 이미지 안의 DB를 가린다.
`docker compose up -d --build`만으로 DB가 갱신되지 않는다. 검증 후보를
`data/knowledge_runtime/<RUN>/`에 별도로 복사해 쓰기 가능한 bind mount로 연결하고:

- `CHROMA_PERSIST_DIR=/app/knowledge/chroma_db`
- `NOTICES_PATH=/app/knowledge/unified_campus_knowledge.json`
- `CHROMA_COLLECTION_NAME=campus_knowledge`

를 함께 설정한다. 기존 named volume과 Compose 설정은 복구용으로 보존한다.
Docker 마운트 루트 자체는 activation 스크립트의 rename 대상이 될 수 없다.
현재 서비스 이미지는 수집 scripts/crawler/OCR 도구가 없어 갱신은 호스트 가상환경에서 실행한다.
자세한 Compose 예시는 `docs/home_server_knowledge_operations_20261008.md`에 있다.

서비스를 다시 시작하고 `/health`, 최신 공지·식단·FAQ·서식 검색, 실제 `/api/query`를 확인한다.
문제가 생기면 이전 데이터 경로·설정으로 되돌리고 서비스를 다시 시작한다.

## 자동 갱신 설치

첫 적용 성공 후 홈서버에 실제 systemd timer 또는 cron을 설치하고 수동으로 한 차례 실행해 검증한다.
매일 06:00 KST에 아래 전체 작업을 수행하도록 만든다:

**중복 실행 잠금 → `refresh_knowledge.py --enrich` → 엄격 동기화/검색 검증 →
운영 정지 → 백업·적용 → 재시작 → API 확인**.

후보 검증이 실패하면 운영 DB를 그대로 유지한다. 서비스를 정지한 후 실패하면
반드시 기존 서비스 재기동/복구를 처리한다. 실행 시간·결과·실패 원인을 로그에 남긴다.
매일 쓰는 검색 사례는 식단·접수 기간 등 날짜 의존 기대값도 함께 갱신한다.
이번 고정 2026-10-08 검증 사례를 영구적인 최신성 기준으로 사용하지 않는다.

공지·일정·식단은 매일, 안내·FAQ는 14일 확인 주기, 첨부 재검증은 주 1회가 기본 정책이다.
GitHub 수집 workflow는 운영 DB에 자동 반영하지 않는다. 서버 예약을 실제 확인한 뒤
서버 수집과 중복되는 workflow를 정리한다. 사용자가 매일 명령을 실행해야 하는 구조로 끝내지 않는다.

완료 보고에는 운영 적용 여부, `/health` 청크 수, 검색 검증 결과, 사용 모델,
예약 작업 이름·주기·최근 실행 결과, 복구 경로를 기록한다.
