# CampusMate 문서 목록

저학년의 반란 CampusMate 프로젝트의 문서 탐색 기준입니다. 2026년 10월 18일 갱신했습니다. 현재 제품은 로그인 없는 공식 정보 질의응답 챗봇이며, 예전 일정·인증 관련 문서를 현재 기능으로 해석하지 않습니다.

## 현재 제출과 설계

| 문서 묶음 | 기준일 | 내용 |
|---|---|---|
| [설계 산출물 4종](../outputs/campusmate_design_20261018/README.md) | 2026-10-18 | TRD, 프로그램 목록, StoryBoard, GitHub 형상관리표 |
| [제품 요구사항과 수행 계획](chatbot_release_20261007/README.md) | 2026-10-07 | 챗봇 PRD v1.2, 수행 계획서, 발표·마일스톤, WBS·대본 |
| [현재 챗봇 범위](campusmate_chatbot_scope_20260927.md) | 2026-09-27 | 익명 질문과 공식 출처, 보관된 개인 일정 기능의 경계 |

10월 7일 자료에 적힌 1,366문서·3,447청크는 당시와 Git 기본 seed의 기준입니다. 10월 18일 TRD에 적힌 1,485문서·6,886청크는 10월 9일 로컬 확장 기록입니다. 문서 최신화와 운영 DB 교체는 별도 작업입니다.

## 실행과 형상관리

| 문서 | 용도 |
|---|---|
| [프로젝트 README](../README.md) | 설치, 웹 실행, API, 환경변수, 데이터 버전과 기본 검증 |
| [저장소 구성과 형상관리](repository_structure.md) | 폴더 역할, 기준 원격, 변경과 산출물 관리 원칙 |
| [컨테이너 실행 가이드](campusmate_local_container_guide.md) | FastAPI·React와 Docker 실행, 과거 기능 분리 |
| [Cloudtype 배포 기록](cloudtype_chatbot_deployment.md) | 당시 저장소·브랜치·실행 설정과 장애 수정 이력 |

## 평가와 작업 이력

- [챗봇 진행 상황과 남은 과제](campusmate_chatbot_progress_and_tasks_20261007.md): 10월 7일 상태와 후속 검증 계획입니다.
- [데이터 확장과 배포 조사](campusmate_data_and_cloudtype_plan_20261007.md): 당시 모델·수집·배포 조사 기록입니다. 현재 가용성·요금·운영 상태는 다시 확인해야 합니다.
- [평가 기준선](campusmate_evaluation_baseline.md): 검색·생성 평가의 기록과 기준입니다.
- `codex_*`, `gemini_*`, `pm_*` 문서는 해당 시점의 검토·수정 이력입니다. 이후 변경을 반영한 최신 기능 명세로 일괄 취급하지 않습니다.

## 보관 자료

- [개인 일정 기능 보관](../archived_features/personal_schedule_20260927/README.md): 인증·일정·캘린더 관련 과거 소스입니다.
- [이전 기획·발표 대본](../archived_artifacts/planning_before_20261007/): 제품 범위 조정 전 자료입니다.
- 루트의 9월 PRD·WBS·발표자료와 일정 API 문서는 이전 버전입니다. 제출본은 위의 현재 문서 묶음에서 선택합니다.
