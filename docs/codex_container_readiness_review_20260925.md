# 로컬 컨테이너 배포 준비 결과 — 2026-09-25

## 판정: 로컬 컨테이너 영속성·복구 검증 통과

설정 검토에서 발견한 문제를 수정하고 실제 Linux aarch64 Docker 이미지로 검증했다. 외부 공개 배포, HTTPS, 실 RAG/LLM 통합, 예약 알림은 이번 범위가 아니다.

## 변경 내용

- Dockerfile: Node 빌드 단계를 추가해 React를 이미지 안에서 빌드. 기존 dist 복사 의존 및 모델 사전 다운로드 제거. 공개 지식 seed와 필요한 소스만 명시적으로 복사.
- Compose: React+FastAPI 단일 backend 서비스로 정리, 기본 주소 127.0.0.1. 고정 container_name 제거. 인증·일정 DB 영속 볼륨과 모델 캐시 추가. AUTH_DB_PATH를 `/var/lib/campusmate/campusmate.db`로 명시.
- 헬스체크: 설치되지 않은 curl 대신 Python 표준 라이브러리 사용.
- requirements: Linux ARM64에서 설치 가능한 torch 조건 분리. x86_64 CPU wheel 지정과 macOS 조건은 유지.
- `scripts/sqlite_snapshot.py`: WAL 포함 일관된 SQLite 백업, 무결성 검사, 기존 대상 덮어쓰기 거부.
- `scripts/verify_container_persistence.py`: 실제 컨테이너 수명주기 및 새 볼륨 복구 검사.
- `tests/test_sqlite_snapshot.py`: WAL 데이터 포함/복원, 덮어쓰기 거부, 실패 시 부분 백업 제거 검사.
- `.dockerignore`와 `.gitignore`: 빌드 소스 허용, 로컬 dist/환경파일/개인 DB 제외 및 backups 제외.

## 실제 검증

빌드 명령:

```bash
docker compose --env-file /dev/null -p campusmate-review-20260925 build backend
```

이미지: `campusmate-review-20260925-backend:latest`. 빌드 성공. Node/npm 및 Python 패키지 다운로드는 수행했으며 외부 LLM 호출·학교 크롤링·모델 가중치 다운로드는 실행하지 않았다.

```bash
.venv/bin/python scripts/verify_container_persistence.py --image campusmate-review-20260925-backend
```

테스트 프로젝트: `campusmate-check-3f2aab6de4`.

| 검사 | 결과 |
| --- | --- |
| Docker health 상태 + HTTP /health | 통과 |
| 빌드된 React 루트/JS/CSS HTTP 응답 | 통과 |
| 계정/세션/일정 생성 후 restart | 원본 레코드 보존 |
| force-recreate로 컨테이너 ID 변경 | 계정/세션/일정/소수점 초 보존 |
| 실행 중 SQLite backup + 호스트 반출 | 성공 |
| 일정 삭제 후 별도 새 볼륨에 backup 복원 | 원래 계정·세션·일정 완전 복구 |
| 저장소 data 파일 해시 | 940개 모두 동일 |
| snapshot 단위 검사 | **3 passed in 0.02s** |
| Compose config 검증 | 통과 |

테스트 계정과 임시 프로젝트를 사용했다. 테스트 컨테이너·네트워크·볼륨은 종료 시 정리했고 이미지와 빌드 캐시는 남겼다. 저장소의 실제 사용자 DB는 열거나 변경하지 않았다. Docker Desktop은 이번 작업에서 기동했다.

## 다음 단계와 제한

이번에는 배포 설정과 백업 도구에 맞는 테스트를 실행했으며 기존 156개 전체 회귀를 재실행한 결과는 아니다. 앱 기능 변경은 하지 않았다. `/health` 통과는 RAG 모델/인덱스/생성 준비를 보증하지 않는다.

다음 단계는 배포 대상·도메인·예산·접근 범위를 정한 후, 검증 버전 고정과 HTTPS 소규모 배포를 준비하는 것이다. 실제 RAG 요청 비용/모델 다운로드 및 예약 알림 구현은 별도 범위로 남긴다. 운영 백업 보관/접근 권한/세션 복구 정책도 배포 전에 결정해야 한다.

실행 및 복구 절차: `docs/campusmate_local_container_guide.md`.
