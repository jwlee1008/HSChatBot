# CampusMate 챗봇 실행 가이드

2026-09-27부터 기본 제품은 학내 공지 챗봇이다. 개인 일정·인증·캘린더·알림은 보관 기능이며 기본 서버와 Docker 이미지에 포함하지 않는다. 이 문서는 이전 일정 DB 백업/복원 중심 안내를 대체한다.

## 로컬 실행

```bash
npm ci --prefix frontend-web
npm run build --prefix frontend-web
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

http://127.0.0.1:8000 에서 로그인 없이 질문하고 출처 카드를 확인한다. `/health`, `/api/retrieve`, `/api/query`가 활성 API다. RAG 초기화를 생략한 오프라인 검사에는 `PREWARM_RAG_ON_STARTUP=false`를 사용한다. 이 설정은 실제 질문 시 필요한 모델 초기화까지 막는 것은 아니다.

## 컨테이너 실행

```bash
docker compose --env-file /dev/null -p campusmate-chatbot up -d --build backend
docker compose --env-file /dev/null -p campusmate-chatbot ps
```

Python 기본 이미지와 Node 빌드 이미지는 digest로 고정하고, Python은 requirements-lock.txt, 프론트엔드는 npm ci를 사용한다. 이번 분리 후 이미지를 새로 빌드해야 한다. 이전 campusmate-locked-backend 이미지에는 일정 기능이 남아 있으므로 그대로 재사용하지 않는다.

기본 포트는 127.0.0.1:8000이다. `CAMPUSMATE_PORT`로 변경할 수 있다. 기존 개인 DB 볼륨을 제거하는 명령은 실행하지 않는다. 새 Compose에는 Chroma seed와 모델 캐시용 볼륨만 있다.

Gemini를 사용하는 경우 LLM_PROVIDER=gemini와 해당 제공자의 키/모델 설정이 필요하다. 실제 사용할 모델의 지원 여부와 키는 운영 시 확인한다. 키는 파일 내용이나 로그로 공유하지 않는다. 기본 local 모드는 로컬 생성 모델까지 로드할 수 있으므로 메모리 및 다운로드를 고려한다.

## 검증 범위

```bash
PREWARM_RAG_ON_STARTUP=false .venv/bin/python -m pytest tests/test_chatbot_only.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
.venv/bin/python scripts/verify_rag_eval_evidence.py
```

선별 오프라인 회귀 검사이며 전체 테스트나 실제 외부 LLM 품질 평가가 아니다. /health 200은 RAG의 모델·검색·생성 준비 완료를 의미하지 않는다. ARM64 기반 기존 검증과 Cloudtype AMD64 검증을 구분한다. 이번 기능 분리는 외부 재배포를 실행하지 않았다.

## 과거 기능 보관

`archived_features/personal_schedule_20260927/README.md`에 보관 파일과 복구 원칙이 있다. 해당 경로는 Docker 빌드 컨텍스트와 pytest 재귀 탐색에서 제외한다. 과거 검수 보고서는 당시 기능의 역사 기록이다.
