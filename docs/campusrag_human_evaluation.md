# CampusRAG 답변 검증

[평가 질문 25개](../data/eval_campus_questions.json). 수강신청, 휴학·복학, 졸업요건, 장학금, 학사일정 각 5개. 복수 원문 3개, 답변 유보 6개. 개선용 `dev` 15개, 확인용 `test` 10개. 질문 출처는 현재 모두 `llm`.

## 학생 질문 추가

학생에게 평소 표현 그대로 질문을 받는다. 이름, 학번, 성적표, 신청번호를 지운 뒤 `origin: "student"`로 추가한다. 같은 의도의 질문은 하나만 고른다. 각 질문에 채점 기준과 학교 원문을 붙인다. 근거가 없는 질문은 `reference_urls`를 빈 배열로 둔다. 문항 추가 후 두 버전을 다시 평가한다.

## 답변 수집

프로젝트 폴더에서 실행한다. 수집 전에 한 스냅샷에서 사본 두 개를 만든다. Chroma가 평가 중 사본에 쓸 수 있다. 두 실행에 같은 모델과 청크 수를 쓴다. 검색 청크 저장 기능을 포함한 기존 코드로 먼저 수집한다.

```powershell
$evalDir = Join-Path $env:TEMP ("campusrag-eval-" + (Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $evalDir | Out-Null
Copy-Item -LiteralPath data/knowledge_runtime/active -Destination "$evalDir/before-snapshot" -Recurse
Copy-Item -LiteralPath "$evalDir/before-snapshot" -Destination "$evalDir/after-snapshot" -Recurse
$env:LLM_PROVIDER = 'local'
$env:LOCAL_LLM_MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
python scripts/evaluate_campus.py collect --snapshot "$evalDir/before-snapshot" --output "$evalDir/before.json"
# 개선 코드 적용 뒤 실행
python scripts/evaluate_campus.py collect --snapshot "$evalDir/after-snapshot" --output "$evalDir/after.json"
python scripts/evaluate_campus.py review "$evalDir/before.json" "$evalDir/before-review.json"
python scripts/evaluate_campus.py review "$evalDir/after.json" "$evalDir/after-review.json"
```

수집 파일은 질문별 답변, 사용자에게 표시한 출처 카드, 해당 질의에서 실제 검색한 청크와 메타데이터를 담는다. 검색만 확인하려면 `collect --mode retrieve`를 쓴다. 한도·인증 오류가 나면 수집을 멈추고 남은 항목을 `not_run`으로 남긴다. 다시 실행할 때 새 출력 파일을 지정한다.

## 가·부 판정

검토자가 `reviewer`와 `reviewer_type`(`human`)을 채운다. 원문을 열어 학기, 신청 대상, 날짜, 시각, 제외 조건을 확인한다. 복수 원문 질문은 각 답변 부분을 해당 원문과 대조한다.

| 항목 | 가 기준 |
|---|---|
| `answer` | 필요한 사실을 모두 답하고, 오류와 추측이 없다. 근거 부재 질문은 확인 한계를 명시한다. |
| `links` | 제시한 링크가 열리고 질문과 직접 관련되며, 질문의 각 부분에 대한 근거를 제공한다. 유보 문항은 `null`로 둔다. |

부에는 `note`에 틀린 문구와 원문 근거를 적고, `reasons`에 해당 원인을 넣는다. AI 예비 판정은 `reviewer_type: "ai"`로 표시한다.

| 원인 | 판정 | 개선 |
|---|---|---|
| 검색 실패 | 필요한 원문이나 핵심 청크가 검색에 없다 | 본문 분할, 문서 유형, 순위 |
| 생성 오류 | 근거가 있는데 답변이 틀리거나 빠졌다 | 프롬프트, 마감과 신청 대상 구분 |
| 링크 오류 | 원문을 열 수 없거나 근거 링크가 빠졌다 | 주소 검증, 답변에 쓰인 출처 연결 |
| 최신성 문제 | 다른 학기, 과거 공지, 정정 전 값을 썼다 | 학기 태그, 정정 공지 우선 |
| 근거 없는 답변 | 원문에서 확인할 수 없는 내용을 단정했다 | 유보 규칙, 개인 조회 범위 명시 |

## 전후 비교

```powershell
python scripts/evaluate_campus.py compare "$evalDir/before.json" "$evalDir/after.json" `
  --before-review "$evalDir/before-review.json" --after-review "$evalDir/after-review.json"
```

정답률 분모는 전체 문항, 링크 정확도 분모는 원문이 필요한 문항이다. 각 지표는 분모 전체 판정이 끝났을 때 계산한다. 수집 오류와 미실행은 상태 집계에 남긴다. 자동 원문 포함률은 검색 청크와 카드에 사전 등록한 원문 URL이 모두 있는지 센다. 답변 정답률과 링크 정확도는 검토자 판정으로만 계산한다.

## 2026-11-09 결과

운영 지식 사본 7,731청크, 로컬 Qwen2.5-1.5B-Instruct, `top_k=3`. 두 실행에서 동일한 25문항을 모두 수집했다.

| 지표 | 개선 전 | 개선 후 |
|---|---:|---:|
| 정답률 · AI 예비 판정 | 2/25 · 8.0% | 11/25 · 44.0% |
| 링크 정확도 · AI 예비 판정 | 5/19 · 26.3% | 15/19 · 78.9% |
| 자동 원문 검색률 | 10/19 · 52.6% | 19/19 · 100.0% |
| 자동 원문 제시율 | 10/19 · 52.6% | 18/19 · 94.7% |

원문 검색률은 문서 주소 일치 기준이다. 검색에 맞는 원문이 있어도 졸업 이수 기준, 장학금 마감, 학사일정에서 생성 오답이 남았다. 사람 판정과 학생 실질문 수집은 대기 중이다. 재평가에서 나온 개인·실시간 조회 실패를 보완할 때 일부 `test` 문항도 확인했다. 독립 표본의 점수는 별도 학생 질문으로 측정한다.
