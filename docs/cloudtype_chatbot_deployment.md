# CampusMate Cloudtype 배포

## 운영 대상

- 서비스: `hschatbot`, Python 3.12 템플릿, 프리티어 1GB, 포트 8000.
- 실제 Git 저장소: `https://github.com/jwlee1008/HSChatBot.git`
- 배포 브랜치: `main`.
- 앱: <https://port-0-hschatbot-mu2fbvpjb5643bfc.sel3.cloudtype.app>
- 원본 저장소 `pregeon/HSChatBot`의 `codex/official-information`에만 push하면 이 서비스에는 반영되지 않는다. 운영 `main`에도 변경을 병합해야 한다.

## 2026-10-07 장애와 수정

기존 빌드 `48fc1d7`은 `/health`에 200을 반환했지만 검색·질의는 500으로 실패했다. 실행 로그의 실제 원인은 GPU가 없는 CPU 서버에서 Transformers 5.19가 Torch 2.6의 `current_accelerator()`를 호출하면서 발생한 `Cannot access accelerator device when none is available` 오류였다. 화면은 모든 서버 오류를 연결 실패와 8000번 포트 문제로 표시했다.

- Python 템플릿의 기본 `pip install -r requirements.txt`는 고정된 패키지 목록을 직접 설치한다. 템플릿은 설치 전에 `requirements.txt*`만 복사하므로 별도 파일을 `-r`로 참조하면 실패한다. Docker의 `requirements-lock.txt`와 동일한 버전 목록을 유지한다. 검증된 Transformers 5.17과 CPU Torch 2.6 조합이다.
- 첫 질의에서 검색 모델을 새로 만들지 않고 이미 준비한 임베딩·DB를 재사용해 LLM만 초기화한다. 초기화 실패는 같은 인스턴스에서 재시도한다.
- 검색·답변 생성은 별도 worker에서 실행해 대기 중에도 health 요청에 응답한다.
- Gemini 기본 모델은 `gemini-3.8-flash`이며, 3.8 요청에서 `temperature`, `top_p`, `top_k`, `candidate_count`를 제외하고 `thinking_level=low`를 지정한다.
- 프런트엔드는 HTTP 서버 오류·시간 초과·연결 실패를 구분하며 빌드 산출물을 Git에 포함한다.

선별 오프라인 회귀 검사 75개와 프런트엔드 빌드가 통과했다. CPU accelerator가 예외를 내는 상황을 재현해 잠금 버전의 sentence-transformers import와 임베딩 생성도 확인했다. 운영 동작은 아래 절차로 별도로 확인한다.

## 기존 서비스 업데이트

Cloudtype의 서비스 **설정 → 배포 설정**에서 위 저장소와 브랜치를 확인한다. 다음 환경변수와 실행 명령을 사용한다. 키 값은 기존 설정을 유지하며 소스에 넣지 않는다.

```text
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.8-flash
GEMINI_API_KEY=<Cloudtype에 설정한 키>
CHROMA_PERSIST_DIR=data/integrated_eval_chroma_db
CHROMA_COLLECTION_NAME=campus_knowledge
Port=8000
Start command=uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

하단 **배포하기**로 최신 Git 코드를 빌드한다. 배포 내역의 이전 빌드에서 **재배포**를 누르면 그 빌드를 다시 적용하므로 최신 Git 코드 여부를 확인해야 한다. [Cloudtype 업데이트 안내](https://docs.cloudtype.dev/ko/developers/deploy)

## 배포 후 확인

1. 배포 내역의 적용 커밋이 운영 `main`의 최신 커밋인지 확인한다.
2. 첫 화면의 제목이 CampusMate인지 확인한다. 이전 화면이 남으면 페이지를 새로고침한다.
3. `/health`의 `llm_provider`가 `gemini`, 모델 사전 로드 후 `doc_count`가 3,447인지 확인한다. health 200만으로 검색·생성 성공을 판단하지 않는다.
4. `/api/retrieve`에서 `도서관 운영시간`을 검색해 공식 출처를 확인한다.
5. `/api/query`로 같은 질문의 답변·출처·생성 상태를 확인하고 Cloudtype 워크로드의 메모리 및 재시작 여부를 확인한다.

수집 봇이 갱신한 원본 JSON과 실제 검색 DB는 별도다. 새 원문을 답변에 사용하려면 통합 지식 JSON과 Chroma 인덱스를 갱신하고 다시 배포해야 한다.
