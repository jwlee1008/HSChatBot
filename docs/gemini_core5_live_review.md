# 핵심 5문항 실제 검증 (2026-09-15 14:59 KST)

실행 식별자: `gemini_core5_20260915T055935Z`.
Gemini 모델: `gemini-3.8-flash`. 기존 통합 DB를 새 경로에 복사하여
`campus_knowledge` 3,447청크를 사용했다. 코드/데이터셋/DB 해시는 manifest에 기록했다.
원본 통합 DB SQLite 해시 불변을 확인했으며 운영 DB는 변경하지 않았다.

## 생성 평가

첫 취업멘토링 질문에서 429 RESOURCE_EXHAUSTED (오류에 limit: 20 명시)가 발생했다.
평가기는 즉시 중단하고 나머지 4개를 NOT_RUN으로 저장했다.
API_ERROR 1, NOT_RUN 4, 실제 생성 성공 0이다. 정답률과 정상 생성 지연은 측정 불가다.
자동 요약의 생성 지연 0초는 정상 생성 표본이 없기 때문이며 속도 측정값이 아니다.
추가 재시도나 유료 전환은 하지 않았다.

## 별도 검색 확인 (API 호출 없음)

평가 전에 같은 DB/코드로 5문항의 검색 근거를 별도 저장했다.
이는 NOT_RUN 4개에 대한 Gemini 생성 성공을 의미하지 않는다.

- exp-01 취업멘토링: 본문 신청 기간 9/10~9/17 15:00 회수. 제목 충돌도 문맥에 남아 있음.
- exp-02 편입생: 일반편입생 및 외국인 유학생 제외 조건 회수.
  타 공지의 2016학년도 이전 입학자 조건도 함께 검색되어 실제 답변 혼입 여부는 미검증.
- exp-04 TOPCIT: 연장 공지와 원 공지는 회수했으나 온라인 접수/보증금 납부의
  업무와 날짜를 연결하는 핵심 단계 청크가 누락됨. 제목의 ~9.9와 문맥 없는
  9/11 10:00~13:00 조각만으로 전체 근거 확보 성공이라고 판단하지 않는다.
- exp-06 평점 FAQ: 반올림하지 않고 셋째 자리부터 버림, 3.4975→3.49 예시 회수.
- exp-10 코드 작성: 검색 결과 0건. LLM 없이 유보 가능한 검색 동작 확인.

## 결과 파일

`data/gemini_core5_20260915T055935Z_` 접두사의
`dataset.json`, `manifest.json`, `evidence.json`, `results.json`, `checkpoint.json`.
DB 복사본은 같은 접두사의 `chroma_db/`에 보존했다.

## 한도 회복 후 재개

아래 명령은 이번 실행 당시 코드와 DB를 유지한 경우에만 사용한다.
코드를 수정하거나 DB 내용을 바꾼 경우 기존 성공 결과와 섞지 말고 새 평가로 시작한다.

```bash
CHROMA_PERSIST_DIR="$PWD/data/gemini_core5_20260915T055935Z_chroma_db" \
CHROMA_COLLECTION_NAME=campus_knowledge LLM_PROVIDER=gemini \
.venv/bin/python scripts/run_eval.py \
  --dataset data/gemini_core5_20260915T055935Z_dataset.json \
  --checkpoint data/gemini_core5_20260915T055935Z_checkpoint.json \
  --output data/gemini_core5_20260915T055935Z_resumed_results.json \
  --resume --retry-policy failed_and_unrun
```

한도 리셋 시각은 이번 응답으로 확인하지 못했다. 자동 재시도/예약은 설정하지 않았다.
