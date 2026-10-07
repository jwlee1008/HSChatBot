# Cloudtype 기존 배포 조사 — 2026-09-26

## 직접 확인

Safari에 로그인된 기존 Cloudtype 서비스 대시보드를 읽기 전용으로 확인했다. 시작/중지, 설정 저장, 재배포 및 결제는 실행하지 않았다. 환경변수 값은 마스킹을 해제하지 않았다.

- 서비스 hschatbot / main: python@3.12, 최소 CPU, 메모리 1GB, 프리티어, 중지됨.
- 적용된 커밋: 34a1eaad84aec0b4e3dc65eb8c8358bbb05f00b5. 로컬 HEAD와 일치하나 최신 인증/일정 등 수정은 작업 트리에 존재하고 커밋되지 않았다.
- 시작 명령: uvicorn backend.main:app --host 0.0.0.0 --port 8000. 포트 8000.
- 디스크 탭: 연결된 디스크가 없습니다.
- 이벤트 탭: 표시할 이벤트가 없습니다. 중지의 개별 원인은 확인 불가.
- 설정 안내: 프리티어 리소스는 매일 1회 중지됩니다.
- 환경변수 이름: LLM_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL, CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME. 값 및 유효성은 미확인.
- 발급된 HTTPS 주소의 / 및 /health를 GET: 둘 다 HTTP 404 HTML 응답. 실행 중인 FastAPI 정상 응답은 확인하지 못했다.

## 판단

기존 배포 경로와 HTTPS 주소는 있으나 최근 검수한 완성본의 운영 배포는 아니다. 이전 ARM64 Docker 검수 결과를 Cloudtype 배포 검증으로 간주하면 안 된다.

공식 Docker 문제해결 문서는 ARM 런타임 미지원과 이미지 크기 제한(기본 2GB, 유료 5GB)을 명시한다. Cloudtype에 Dockerfile 배포 시 AMD64 빌드, 이미지 크기, non-root 실행 및 DB/캐시 쓰기 권한을 별도 검증해야 한다. 현재 Python 템플릿이 새 멀티스테이지 Dockerfile을 사용한다고 가정하지 않는다.

현재 계정·세션·일정은 SQLite 파일에 저장된다. Compose named volume은 Cloudtype Python 서비스로 자동 이전되지 않는다. 공식 일반 문제 문서는 앱 디스크 마운트 미지원이라고 안내하지만 UI에는 디스크 탭이 있으므로, 문서와 실제 플랜 기능의 차이를 확인해야 한다. 최소한 현재 서비스에 디스크가 연결되지 않았다는 사실은 직접 확인했다. DB 상품에 제공되는 디스크 용량을 Python 앱의 SQLite 영속 마운트와 혼동하지 않는다.

1GB에서 실제 임베딩 모델의 정상 구동/최대 메모리는 측정하지 않았다. 외부 Gemini를 쓰더라도 로컬 임베딩 메모리는 필요하다. 중지가 OOM 때문이라고 단정하지 않는다.

## 다음 순서

1. 계정·일정 저장 방식 확정: 해당 앱의 영속 디스크 지원을 확인하고 불가하면 Cloudtype 별도 DB에 맞춰 저장 계층을 이식하거나 영속 디스크가 있는 서버로 배포한다. 단순 DB URL 교체로 SQLite 전용 코드를 이전할 수 없다.
2. 검수된 변경만 배포용 커밋으로 정리할 준비: 개인 DB/키/불필요한 산출물 제외, 롤백 기준 커밋 기록. 현재는 commit/push하지 않음.
3. Cloudtype 유지 시 Dockerfile 방식과 AMD64를 검증: Python 잠금 설치, React 빌드, 이미지 크기, non-root 쓰기 권한, 8000 포트, HTTP 헬스체크.
4. 테스트 환경에서 실제 모델 로드 및 첫 질의의 메모리/지연/오류 측정. LLM 키/모델의 유효성 확인. 필요한 자원 규모는 측정 후 결정.
5. 최신 버전 재배포 후 회원가입→로그인→질의→출처 일정 추출→확인 저장→재시작/재배포→데이터 유지와 로그아웃 검증. 실제 RAG 비용 발생 검사는 별도 실행 범위를 정함.
6. 지속 운영이 필요하면 구독 리소스/예산 결정. 기존 프리뷰 HTTPS 주소로 먼저 검증하며 도메인 구매는 선행 조건이 아니다.

## 근거

- https://docs.cloudtype.dev/ko/developers/resource : 프리티어 매일 중지, 프리뷰 도메인, 구독 리소스 별도 적용.
- https://docs.cloudtype.dev/ko/developers/features : HTTPS 프리뷰 URL 발급.
- https://docs.cloudtype.dev/ko/troubleshooting/dockerfile : ARM 미지원, 이미지 크기, non-root 관련 주의.
- https://docs.cloudtype.dev/ko/troubleshooting/common : 앱 파일 영속성 제한 안내.
- https://docs.cloudtype.dev/ko/developers/database : 별도 DB 서비스 저장소.
