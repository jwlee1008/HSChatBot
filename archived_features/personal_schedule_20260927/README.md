# 개인 일정 기능 보관본

2026-09-27 사용자 요청으로 현재 제품을 학내 공지 챗봇으로 한정했다. 개인 일정/인증/캘린더/알림과 관련 검사 코드를 이 폴더에 분리했다. 향후 구현 예정이라는 뜻이 아니며, 명시적인 복구 요청 전까지 비활성 보관한다.

- backend/auth, db, routers, schedules: 이전 구현 원본
- backend/main.py, schemas.py, config.py, frontend-web/src/App.tsx: 이전 통합 앱 원본
- tests 및 fixtures, scripts: 해당 기능의 검사/백업/수용 도구
- Dockerfile, docker-compose.yml, requirements*: 이전 실행 환경 참고본
- manifest.json: 보관 시점 파일별 SHA-256

현재 앱에서 import/라우터 등록/SQLite 초기화를 하지 않으며 프론트엔드 번들에도 포함하지 않는다. Docker 컨텍스트와 기본 pytest 재귀 수집에서도 제외한다. 개인 DB·계정 정보·API 키·data/ 파일은 이 보관본에 복사하지 않았다.

## 복구 원칙

이 폴더는 독립 실행 앱이 아니라 당시 파일 경로를 보존한 소스 묶음이다. 복구할 경우 별도 브랜치/작업 복사본에서 manifest를 검증하고 같은 상대 경로로 필요한 파일을 복사한다. main.py/config.py/스키마/App.tsx/Docker 설정은 현재 챗봇 변경을 덮어쓰지 않도록 병합해야 한다. 기존 core/rag.py 및 scripts/build_unified_dataset.py 등 공유 모듈과 함께 사용한다. 과거 tests를 복구한 뒤 전체 흐름을 다시 검증해야 하며 이전 159개 통과를 복구 후 결과로 재사용하지 않는다.

기존 docs의 인증/일정 보고서는 역사 기록이다. 활성 제품 범위는 루트 README 및 docs/campusmate_chatbot_scope_20260927.md를 따른다. archived_features를 루트에 통째로 덮어쓰는 자동 복구는 제공하지 않는다.
