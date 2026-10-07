# CampusMate 배포 전 재현성 및 운영 준비 보강 보고서 — 2026-09-25

> 2026-09-26 Codex 후속 검수에서 검사 대상 설명과 환경 범위를 정정했다. 최신 독립 실행 결과는 [후속 검수 보고서](codex_deployment_readiness_review_20260926.md)를 우선한다.

## 1. 개요 및 최종 판정

### 판정: 배포 전 재현성 확보 및 로컬·컨테이너 자동 검증 통과

배포 전 의존성 재현성을 확보하기 위해 현재 검증된 환경을 기준으로 `requirements-lock.txt`를 생성하고 `Dockerfile` 빌드 파이프라인과 연결했다.
로컬 가상환경(`.venv`)과 빌드된 Linux ARM64 Docker 이미지 내부 환경 양쪽에서 모든 핵심 회귀, 수용 검사, 영속성·복구 검사를 완벽하게 통과했다.

> [!IMPORTANT]
> **`/health` 통과에 대한 명시적 한계**:
> `/health`의 HTTP 200 OK는 기본 HTTP 응답 가능 상태만 확인하며 DB 연결을 직접 검사하지 않음하며, RAG 모델 다운로드·임베딩 색인·외부 LLM 호출 준비 완료를 의미하지 않는다. 실제 RAG 쿼리 준비 상태는 운영 환경의 사전 웜업(`PREWARM_RAG_ON_STARTUP=true`) 및 모델 캐시 주입 후 별도 검증해야 한다.

---

## 2. 변경 및 신규 파일 목록

| 파일 경로 | 구분 | 주요 내용 |
| --- | --- | --- |
| `requirements-lock.txt` | 신규 생성 | Linux ARM64에서 검증된 패키지 버전을 고정(macOS torch 범위는 미고정)하고, PyTorch에 대해 macOS(`sys_platform == 'darwin'`), Linux x86_64(`platform_machine == 'x86_64'`), Linux ARM64(`platform_machine != 'x86_64'`) 조건 분기 유지 |
| `Dockerfile` | 변경 | `COPY requirements-lock.txt requirements.txt ./` 및 `pip install --no-cache-dir -r requirements-lock.txt`로 연결하여 빌드 재현성 확보 |
| `scripts/verify_container_api_regression.py` | 신규 생성 | 프로덕션 컨테이너 내부 Python 환경에서 외부 pytest/playwright 없이 TestClient 및 표준 라이브러리로 핵심 API(인증, 일정 CRUD, BOLA, 정밀도, 추출, 날짜 파싱, 스냅샷)를 검증하는 독립 러너 |
| `docs/campusmate_local_container_guide.md` | 변경 | 의존성 잠금 반영 및 컨테이너 내부 핵심 API 회귀 명령(`verify_container_api_regression.py`) 추가 |
| `docs/gemini_deployment_readiness_report.md` | 신규 생성 | 배포 전 재현성 및 운영 준비 보강 최종 보고서 (본 문서) |

---

## 3. 실제 실행 명령과 결과 구분

### A. 로컬 `.venv` 환경 결과 (호스트: macOS Darwin arm64)

#### 1) 기존 핵심 9개 파일 회귀 + SQLite 스냅샷 검사
- **실행 명령**:
  ```bash
  .venv/bin/pytest tests/test_browser_e2e.py tests/test_ui_and_e2e_flow.py tests/test_schedule_extraction.py tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py tests/test_sqlite_snapshot.py -v
  ```
- **실행 결과**: **159 passed, 1 warning in 53.26s (exit code 0)**
  - 기존 156개 핵심 회귀 전원 통과 (Chromium Playwright E2E 3종 포함)
  - `tests/test_sqlite_snapshot.py` 3종 전원 통과 (WAL 포함 복원, 덮어쓰기 거부, 비정상 소스 롤백)
  - 경고 1건: Starlette/AnyIO deprecation 경고 (`DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated`)

#### 2) 실제 공지 수용 검사 (목표 5/5 유지)
- **실행 명령**:
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/verify_real_notice_acceptance.py
  ```
- **실행 결과**: **5 passed / 5 total (exit code 0)**
  - `uat-transfer`: {'expected_end': '2026-09-18T17:00:00+09:00'}; 8개 후보, 원문 근거 검사 통과
  - `uat-topcit`: {'expected_end': '2026-09-11T13:00:00+09:00'}; 4개 후보, 원문 근거 검사 통과
  - `uat-mentoring`: {'expected_end': '2026-09-17T15:00:00+09:00'}; 2개 후보, 원문 근거 검사 통과
  - `uat-calendar`: {'expected_start': '2026-10-19', 'expected_end': '2026-10-24'}; 78개 후보, 원문 근거 검사 통과
  - `uat-no-date`: {'expected_count': 0}; 0개 후보, 원문 근거 검사 통과

---

### B. 컨테이너 내부 환경 결과 (이미지: Linux aarch64 `campusmate-locked-backend`)

#### 1) 잠금된 의존성 기반 이미지 빌드
- **실행 명령**:
  ```bash
  docker compose --env-file /dev/null -p campusmate-locked build backend
  ```
- **실행 결과**: **빌드 성공 (127.5s)**
  - `requirements-lock.txt`를 기반으로 CPU 전용 PyTorch 및 고정 버전 패키지 설치 완료
  - 이미지 태그: `campusmate-locked-backend:latest`

#### 2) 컨테이너 수명주기, 영속성 및 백업/새 볼륨 복원 재검증
- **실행 명령**:
  ```bash
  .venv/bin/python scripts/verify_container_persistence.py --image campusmate-locked-backend
  ```
- **실행 결과**: **전원 통과 (exit code 0)**
  ```json
  {
    "project": "campusmate-check-62ad832cf6",
    "checks": [
      "docker_health_and_built_react_assets",
      "restart_preserves_account_session_schedule_precision",
      "new_container_preserves_named_volume",
      "online_sqlite_backup_and_export",
      "restore_to_fresh_volume_recovers_deleted_record"
    ],
    "data_files": 940,
    "data_unchanged": true
  }
  ```
  - 컨테이너 health 상태 및 React 정적 자산 로드 확인
  - 컨테이너 restart 후 계정·세션·마이크로초(`.123456`) 정밀도 보존 확인
  - force-recreate로 컨테이너 ID 변경 후 볼륨 데이터 영속 확인
  - 온라인 SQLite snapshot 생성 및 호스트 반출 성공
  - 기존 데이터 삭제 후 **독립 새 볼륨(`restore_data`)** 복원 및 데이터 완전 복구 확인

#### 3) 이미지 내부 Python 환경 핵심 API 회귀
- **실행 명령**:
  ```bash
  docker run --rm -v $(pwd)/scripts:/app/scripts:ro campusmate-locked-backend python scripts/verify_container_api_regression.py
  ```
- **실행 결과**: **11 passed, 0 failed in Linux aarch64 (exit code 0)**
  ```text
  [PASS] 1. GET /health contract
  [PASS] 2. Auth registration and duplicate rejection (409 Conflict)
  [PASS] 3. Auth login and invalid password rejection (401 Unauthorized)
  [PASS] 4. GET /api/v1/auth/me session resolution
  [PASS] 5. POST /api/v1/schedules with microsecond precision (.123456)
  [PASS] 6. Schedule BOLA multi-user isolation (404 enforced)
  [PASS] 7. PATCH /api/v1/schedules preserves untouched microsecond datetime
  [PASS] 8. DELETE /api/v1/schedules and verify empty list (204 No Content)
  [PASS] 9. Schedule extraction logic & candidate grounding
  [PASS] 10. Date parsing & strict calendar rejection
  [PASS] 11. SQLite snapshot WAL backup and overwrite protection
  ```

---

### C. 데이터 파일 무결성 대조 결과

- **검증 대상**: `data/` 디렉터리 내 전체 파일 940개
- **검증 방식**: 작업 시작 전 SHA-256 해시를 기록하고, 모든 테스트·빌드·복원 완료 후 SHA-256 해시와 전수 비교
- **결과**: **940개 파일 전수 SHA-256 일치 (변경 0건, 무결성 100% 보존)**

---

## 4. 검증된 아키텍처 및 미실행·미검증 항목

### 검증 완료된 아키텍처
1. **Linux aarch64 (ARM64)**: Docker 컨테이너 런타임 환경 (Python 3.12.14 slim 및 Node 22 bookworm slim 빌드 단계)
2. **macOS Darwin arm64**: 로컬 개발 가상환경 (`.venv`, Python 3.12, Chromium Playwright E2E)

### 미검증 (Unverified) 아키텍처 및 환경
1. **Linux x86_64 (AMD64)**:
   - `requirements-lock.txt`에 `torch==2.6.0+cpu; sys_platform != 'darwin' and platform_machine == 'x86_64'` 조건을 명시했으나, 현재 물리 테스트 호스트가 Apple Silicon ARM64이므로 실제 AMD64 bare-metal/클라우드 인스턴스 빌드는 실행하지 않았다.
   - 운영 서버가 x86_64인 경우 배포 직전 해당 아키텍처 인스턴스에서 1회 사전 빌드 검증이 필요하다.
2. **공개 HTTPS 인터넷 배포 환경**:
   - 현재 Compose 바인딩은 `127.0.0.1`로 격리되어 있으며, 공인 IP 노출이나 TLS 역방향 프록시는 미검증이다.

### 의도적 미실행 및 별도 과제 범위
1. **실제 RAG 임베딩/생성 통합 검증**:
   - 외부 LLM API 호출(Gemini/OpenAI) 및 Hugging Face 모델 가중치 네트워크 다운로드는 제약 조건에 따라 실행하지 않았다.
2. **백그라운드 예약 알림 (Scheduled Notifications)**:
   - Cron/Celery/APScheduler 등 일정 도래 전 알림 발송 워커는 아키텍처 설계 및 구현 작업으로 남아 있다.
3. **학교 공식 웹사이트 실시간 크롤링**:
   - 학교 서버 부하 및 운영 정책에 따라 테스트 중에는 오프라인 시드 데이터(`unified_campus_knowledge.json`)만을 사용했다.

---

## 5. HTTPS 배포 전 사용자가 결정해야 할 핵심 운영 항목

운영 서버에 CampusMate를 HTTPS로 배포하기 전, 팀과 인프라 담당자가 반드시 합의하고 결정해야 할 7가지 항목을 정리했다.

### 1) 배포 대상 및 인프라 형태
- **선택지**:
  - A. **단일 클라우드 VM (IaaS)**: AWS EC2 (t4g.small / c7g.medium ARM64 권장) 또는 GCP Compute Engine. Docker Compose 직접 구동.
  - B. **컨테이너 서버리스 (CaaS)**: GCP Cloud Run 또는 AWS ECS Fargate (영속 볼륨 마운트 필요).
- **결정 필요 사항**: 관리 복잡도, 유지 비용, 지속적인 볼륨 마운트 편의성을 고려해 VM 기반 Compose 구동인지 서버리스인지 결정.

### 2) 접근 범위 (Network Access Scope)
- **선택지**:
  - A. **학내망/VPN 한정**: 학내 IP 대역 또는 학교 VPN 접속자에게만 포트 개방 (보안 위험 최소화, UT용 적합).
  - B. **완전 공개 인터넷**: 누구나 접속 가능 (WAF, Rate Limiting, DDoS 방어 필수).
- **결정 필요 사항**: 최초 릴리스가 재학생 10~20명 대상 비공개 UT인지, 전체 재학생 대상 오픈 베타인지 결정.

### 3) 도메인 및 TLS/HTTPS 구성
- **결정 필요 사항**:
  - 사용할 도메인 이름 (예: `campusmate.hansung.ac.kr` 또는 서드파티 독립 도메인 `campusmate.kr`).
  - TLS 종단 방식: Reverse Proxy (Caddy / Nginx + Let's Encrypt 자동 갱신) vs 클라우드 ALB/Cloudflare SSL 종단.

### 4) 비용 한도 및 쿼터 관리
- **결정 필요 사항**:
  - LLM API 비용 상한선: Gemini API / OpenAI API 월간 사용량 예산 캡(Budget Hard Cap) 설정 ($10~$30/월 등).
  - 사용자당 호출 Rate Limit: 분당 쿼리 횟수(예: 10 req/min) 및 하루 최대 쿼리 횟수 제한 정책.

### 5) 비밀값(Secrets) 주입 체계
- **결정 필요 사항**:
  - 저장소 `.env` 파일은 Git에서 제외되므로, 운영 환경에서 `GEMINI_API_KEY`, `OPENAI_API_KEY`, DB 경로 등을 주입할 방식 결정.
  - 권장: 호스트 시스템 환경변수 주입, 또는 클라우드 Secret Manager / Docker Swarm secrets 사용.

### 6) DB 백업 위치·주기·보존 기간
- **결정 필요 사항**:
  - **백업 도구**: 검증된 `scripts/sqlite_snapshot.py` 활용 (온라인 WAL 일관 백업).
  - **백업 주기**: 일 1회 (새벽 04:00 자동 크론).
  - **저장 위치**: 컨테이너 로컬 볼륨에만 보관하지 않고, S3 / GCS 등 별도의 오프사이트(Off-site) 오브젝트 스토리지로 반출.
  - **보존 기간**: 일일 백업 14일, 주간 백업 8주 보존 후 자동 만료.

### 7) 장애 복원 시 세션 폐기(Session Invalidation) 정책
- **결정 필요 사항**:
  - 과거 시점 백업 snapshot으로 복원할 경우, 백업 생성 시점에 유효했던 세션 토큰이 다시 유효해져 탈취 세션 재활성화 위험이 발생할 수 있다.
  - **권장 정책**: DB 복원 즉시 `DELETE FROM sessions;`를 수행하여 모든 활성 세션을 일괄 파기하고, 모든 사용자에게 재로그인을 요구함으로써 세션 하이재킹을 원천 차단.

---

## 6. 결론

CampusMate는 의존성 재현성 잠금(`requirements-lock.txt`), Linux ARM64 컨테이너 빌드 및 영속성/새 볼륨 복구 검증, 로컬 .venv 및 컨테이너 내부 핵심 API 회귀 검증(159/159, 11/11, 5/5)을 모두 완료했다.
데이터 무결성(940개 파일)도 완벽하게 보존되었다.
사용자가 위의 **7가지 운영 결정 사항**을 확정하면, 소규모 스테이징 인스턴스에 HTTPS를 연결하여 실 RAG 연동 및 운영 배포 단계로 진행할 수 있다.
