# 공식 정보 수집 확장 2차 (2026-09-15)

이번 변경은 공개 데이터 수집과 격리 검색 검증이다. 운영 DB 교체, 서비스 배포,
실제 서비스의 전체 데이터 반영 완료를 의미하지 않는다.

## 확보한 정보

| 데이터 | 문서 수 | 범위와 한계 |
| --- | ---: | --- |
| `data/official_pages.json` | 144 | 공식 상시 안내 HTML. 연간 학사일정과 현재 주 식단 포함 |
| `data/official_pages_enriched.json` | 144 | 위 안내에 PDF/HWP/이미지 추출문을 결합한 별도 결과 |
| `data/official_faq.json` | 179 | 공개 학사 FAQ 18페이지 전체. 게시일이 없으므로 날짜를 만들지 않음 |
| `data/official_forms.json` | 57 | 공개 학사서식 게시판 2195의 8페이지 전체. 오래된 유효 서식을 위해 기간 제한 해제 |
| `data/official_forms_enriched.json` | 57 | 서식 첨부 추출 결과와 미지원 상태 포함 |
| `data/notice_archive.json` | 960 | 우선순위 게시판의 제한된 과거 수집. 최근 3년 전체 수집은 아직 미완료 |

원본과 보강 파일은 같은 문서의 다른 표현이므로 문서 수를 합산하지 않는다.
서식 일부는 공지 아카이브에도 포함되어 있어 통합할 때 ID/URL 중복 제거가 필요하다.

## 실제로 고친 누락 원인

- 식단 표가 `form` 안에 있었다. 폼 전체를 제거하던 본문 정제 대신 입력 컨트롤만 제거하여 날짜와 메뉴를 보존한다.
- 장학제도 PDF는 확장자 링크가 아니라 `fileDown.do`였다. 다운로드 링크를 수집하고 파일 바이트로 형식을 판별한다.
- 학사일정은 화면의 일부 월만 저장하지 않고 사이트가 사용하는 공개 연간 조회 엔드포인트를 호출한다. 학부/대학원 일정을 확인했고, 교직원 행사 일정은 12개월 모두 등록 없음임을 별도로 기록한다.
- FAQ는 일반 공지 상세 페이지가 아니라 목록의 펼침 영역에 답변이 있다. 전용 수집기를 추가하고 일반 공지 수집기가 FAQ를 완료로 오인하지 않도록 거부한다.
- 사이트가 연결한 학점인정 게시판 143은 HTTP 404였다. 수집 성공이나 빈 게시판으로 처리하지 않는다.

## 추출 결과와 제한

상시 안내 144건의 미디어 상태는 complete 73, not_applicable 65, partial 5,
failed_or_unsupported 1이다. 213개 자료에서 success 78, empty 129, partial 5,
size_exceeded 1을 기록했다. 본문은 HTML 대비 약 64,688자 추가됐다.
`complete`는 설정된 추출 절차의 완료 상태이며, OCR 정확도나 안내의 완전성을 보증하지 않는다.
빈 OCR 결과는 사진·아이콘일 수도 있으므로 글자 누락 없음으로 단정하지 않는다.

서식 57건은 complete 43, not_applicable 4, partial 1,
failed_or_unsupported 9이다. HWP 3.0, 일반 ZIP/DOCX 등은 이번 범위에서 추출하지 않는다.
PDF 페이지 상한은 10, 다운로드 상한은 20MB이다. 전공트랙 안내의 약 35.7MB 파일은 차단 상태로 남겼다.
자료별 상태·오류·해시는 각 enriched JSON과 `.report.json`에 보존한다.

본문은 매번 `html_content`에서 다시 구성하여 이전 추출문을 누적하지 않는다.
새 추출이 실패하면 이전 성공 결과를 보존하되, 갱신 실패와 이전 자료 보존을 명시한다.
`--reuse-media`는 기존 추출문을 다시 결합하는 옵션이며 원격 재검증을 뜻하지 않는다.

## 갱신 정책

- 상시 안내 기본 14일, 학사 FAQ 14일.
- 학사일정과 식단은 1일. 식단은 현재 주 범위이며 미래 주 자료를 확보했다고 주장하지 않는다.
- 워크플로는 매일 실행하되 URL별 경과 시간을 검사한다.
- 이번 미디어 보강과 과거 공지/서식 일괄 수집은 명령으로 실행했다. 미디어 정기 보강,
  모든 게시판의 증분 수집, 통합 DB 발행 자동화는 아직 연결하지 않았다.
- 워크플로의 예약 실행은 기본 브랜치에 반영된 뒤 활성화된다. 작업 브랜치 push만으로 운영 예약이 켜지지 않는다.

## 재현 명령

```bash
python -m crawler.official_site --max-pages 200
python -m crawler.faq
python -m crawler.notice_archive --boards 2195 --since 1900-01-01 --max-pages 30 --max-notices 300 --output data/official_forms.json
python scripts/enrich_official_pages.py --input data/official_pages.json --output data/official_pages_enriched.json
python scripts/enrich_official_pages.py --input data/official_forms.json --output data/official_forms_enriched.json
python -m pytest tests/test_official_site.py tests/test_knowledge_collection.py -q
```

과거 공지는 상세 성공마다 체크포인트를 저장한다. 타임아웃 후 확인된 페이지부터
`--start-page`로 이어갈 수 있다. 이는 앞선 페이지 재검증이 아니며 단일 게시판에서만 허용된다.
초기 보고서 `notice_archive.json.report.json`의 FAQ 완료 표시는 이전 파서의 오인식이다.
FAQ 범위 판단은 전용 `official_faq.json.report.json`을 사용한다.

일반 공지의 목록/상세 타임아웃 뒤 34페이지부터 재개하여 200건을 추가했고,
`data/notice_archive_retry_20260915.report.json`에 오류 0건, 총 960건을 기록했다.
45페이지에서 200건 한도에 도달했으므로 다음 실행은 **45페이지부터** 재개한다.
이미 저장한 상세는 건너뛴다. 페이지 이동으로 생길 수 있는 누락은 이후 정기 재검증이 필요하다.
초기 실패 상세 221884는 이번 재개 범위에서 회수되지 않아 실패 목록에 남아 있다.
일반 게시판 2127은 881건(2026-03-05~2026-09-15), 장애학생지원 게시판 2128은 67건,
AI 관련 게시판 2203은 10건, 서식 게시판 2195는 2건이다.
전체 960건 중 HTML 본문 확보는 742건, title_only는 218건이다.
이 아카이브의 이미지/첨부는 아직 일괄 보강하지 않았으므로 저장 건수와 답변 가능한 본문 건수를 구분한다.

## 검증

- 변경 범위 테스트: **19 passed**. 식단 보존, 연간 일정, PDF/HWPX 다운로드 핸들러,
  FAQ 표/식별자, 실패 상태와 이전 성공 데이터 보존, 잘못된 재개 요청 거부를 검사했다.
- 상시 안내·FAQ·서식 **380문서 / 1,015청크**를 임시 Chroma DB에 적재하여 실제 검색했다.
  실행 후 임시 DB를 정리했으며 운영 DB는 변경하지 않았다.
- `data/knowledge_retrieval_smoke.json`에 입력 파일 해시와 5개 질문의 검색 결과를 기록했다.
  초과학기 등록 일정, 외국인 수강학점 FAQ, 자퇴원 서식을 검색했다.
  평점 반올림 질문은 지정한 안내 URL 대신 직접 답하는 FAQ를 찾았고,
  장학제도 종류 질문은 교내장학 안내를 찾았다. 이 두 건의 좁은 URL 일치 검사는 false이며,
  결과를 사후에 자동 PASS로 바꾸지 않았다.
- 이 검증에는 LLM 답변 생성과 실제 앱 HTTP/E2E가 포함되지 않는다.

## 다음 작업

1. 남은 과거 공지를 체크포인트부터 추가 수집하고 게시판별 날짜 범위·실패 목록을 확정한다.
2. 통합 입력 목록과 중복 제거, 공지/FAQ/상시 안내의 출처 및 유효 시점 정책을 연결한다.
3. 보강 결과를 정기 갱신 파이프라인에 연결하고 임시 DB에서 실제 HTTP 검색/답변을 검증한다.
4. 기존 미해결 오답·짧은 질문 누락을 함께 확인한 뒤, 운영 DB 갱신과 배포를 진행한다.
