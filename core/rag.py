"""
CampusRAG 코어 RAG 파이프라인 모듈

유사도 검색(retrieve)과 RAG 질의응답(query)을 수행한다.
LLM Provider(local/gemini/openai)에 따라 생성 모델을 스위칭한다.
"""

import logging

from langchain_core.documents import Document
from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

import config
from core.embedder import get_chroma_vectorstore
from core.prompts import RAG_PROMPT, format_retrieved_docs

logger = logging.getLogger(__name__)


import re
import warnings
from datetime import datetime

RELEVANCE_THRESHOLD = config.RELEVANCE_THRESHOLD  # 서비스와 평가 공통 원시 코사인 유사도 임계값 (0.25)
MIN_RELEVANCE_THRESHOLD = RELEVANCE_THRESHOLD  # 하위 호환성 별칭


def extract_query_entities(query: str) -> dict:
    """질의에서 연도, 학기, 차수 등의 검색 엔티티를 정규식으로 추출한다 (연도 범위 제한 없음)."""
    entities = {}

    # 4자리 연도 (1900~2099)
    y4 = re.search(r"\b(19\d{2}|20\d{2})(?:년|학년도)?", query)
    # 2자리 연도 ('26, '27 또는 26년, 27년, 24-1학기 등)
    y2 = re.search(r"(?:'(\d{2})|\b(\d{2})\s*(?:년|학년도|-))", query)
    if y4:
        entities["year"] = y4.group(1)
        entities["short_year"] = f"'{y4.group(1)[-2:]}"
    elif y2:
        yy = y2.group(1) or y2.group(2)
        entities["year"] = f"20{yy}"
        entities["short_year"] = f"'{yy}"

    # 학기 추출 (1학기, 2학기)
    sem_match = re.search(r"([12])학기", query)
    if sem_match:
        entities["semester"] = f"{sem_match.group(1)}학기"

    # 차수 추출 (1차, 2차)
    round_match = re.search(r"([12])차", query)
    if round_match:
        entities["round"] = f"{round_match.group(1)}차"

    return entities


class CampusRAG:
    """
    CampusRAG 핵심 클래스.

    - retrieve(): Chroma DB에서 유사도 검색 및 엔티티/최신성 기반 리랭킹 수행 (답변 근거 청크 반환)
    - query(): 유사도 검색 + LLM 생성까지 수행 (출처 카드는 URL 단위로 중복 제거하여 반환)
    """

    def __init__(self, load_llm: bool = False):
        """
        Args:
            load_llm: True이면 LLM까지 로드 (query 사용 시).
                      False이면 검색만 가능 (retrieve 사용 시).
        """
        logger.info("CampusRAG 초기화 시작")
        self.vectorstore = get_chroma_vectorstore()
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": config.TOP_K},
        )
        self.llm = None
        if load_llm:
            self.llm = self._load_llm()
            self.chain = self._build_chain()
        logger.info("CampusRAG 초기화 완료 (LLM 로드: %s)", load_llm)

    def _load_llm(self) -> BaseLLM:
        """설정된 LLM Provider에 따라 적절한 LLM을 로드한다."""
        provider = config.LLM_PROVIDER.lower()
        logger.info("LLM 로딩: provider=%s", provider)

        if provider == "local":
            return self._load_local_llm()
        elif provider == "gemini":
            return self._load_gemini_llm()
        elif provider == "openai":
            return self._load_openai_llm()
        else:
            raise ValueError(f"지원하지 않는 LLM Provider: {provider}")

    def _load_local_llm(self) -> BaseLLM:
        """HuggingFace 로컬 모델을 로드한다."""
        from langchain_huggingface import HuggingFacePipeline
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        device = config.get_device()
        logger.info("로컬 LLM 로딩: %s (device: %s)", config.LOCAL_LLM_MODEL, device)

        tokenizer = AutoTokenizer.from_pretrained(config.LOCAL_LLM_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            config.LOCAL_LLM_MODEL,
            torch_dtype="auto",
        )
        if device != "cpu":
            model = model.to(device)

        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=config.LOCAL_LLM_MAX_NEW_TOKENS,
            return_full_text=False,  # 프롬프트 제외, 생성 텍스트만 반환
            do_sample=False,
            repetition_penalty=1.05,
        )

        def chat_prompt(prompt):
            return tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt.to_string()}],
                tokenize=False,
                add_generation_prompt=True,
            )

        return RunnableLambda(chat_prompt) | HuggingFacePipeline(pipeline=pipe)

    def _load_gemini_llm(self) -> BaseLLM:
        """Google Gemini API를 LLM으로 로드한다."""
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not config.GEMINI_API_KEY:
            raise ValueError(
                "Gemini API 키가 설정되지 않았습니다. "
                ".env 파일에 GEMINI_API_KEY를 설정하세요."
            )

        return ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GEMINI_API_KEY,
            temperature=0.3,
            timeout=30.0,
            max_retries=0,  # 503/429 등 오류는 서비스 레벨에서 명시적으로 제어
        )

    def _load_openai_llm(self) -> BaseLLM:
        """OpenAI API를 LLM으로 로드한다."""
        from langchain_openai import ChatOpenAI

        if not config.OPENAI_API_KEY:
            raise ValueError(
                "OpenAI API 키가 설정되지 않았습니다. "
                ".env 파일에 OPENAI_API_KEY를 설정하세요."
            )

        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=0.3,
            timeout=30.0,
            max_retries=0,
        )

    def _build_chain(self):
        """LangChain LCEL 체인을 구성한다."""
        return RAG_PROMPT | self.llm | StrOutputParser()

    def _invoke_llm_with_error_handling(self, chain_input: dict) -> tuple[str, dict]:
        """
        LLM을 호출하고 오류(503, 429, 인증 등)를 구분하여 안전하게 처리한다.
        - 503: 1회 제한된 backoff 재시도 후 일시 장애 안내
        - 429: 재시도 없이 한도 초과 안내
        - 401/403: 재시도 없이 인증/설정 오류 안내
        - 사용자 모르게 로컬 모델로 전환하지 않음
        - API 키 노출 방지
        반환: (answer_text, execution_meta)
        """
        import time

        provider = config.LLM_PROVIDER.lower()
        model_name = {
            "gemini": config.GEMINI_MODEL,
            "local": config.LOCAL_LLM_MODEL,
            "openai": config.OPENAI_MODEL,
        }.get(provider, "unknown")

        meta = {
            "provider": provider,
            "model": model_name,
            "api_called": True,
            "status": "success",
            "error": None,
            "latency_seconds": 0.0,
        }

        started = time.monotonic()
        max_503_retries = 1
        backoff_delay = 1.5

        for attempt in range(max_503_retries + 1):
            try:
                answer = self.chain.invoke(chain_input)
                meta["latency_seconds"] = round(time.monotonic() - started, 3)
                return answer, meta
            except Exception as e:
                err_str = str(e)
                if config.GEMINI_API_KEY:
                    err_str = err_str.replace(config.GEMINI_API_KEY, "[REDACTED]")

                is_503 = (
                    "503" in err_str
                    or "Service Unavailable" in err_str
                    or "temporarily unavailable" in err_str
                    or "overloaded" in err_str
                )
                is_429 = (
                    "429" in err_str
                    or "ResourceExhausted" in err_str
                    or "quota" in err_str.lower()
                    or "rate limit" in err_str.lower()
                )
                is_auth = any(
                    code in err_str
                    for code in ("401", "403", "PermissionDenied", "API_KEY_INVALID", "Unauthenticated")
                )

                if is_503 and attempt < max_503_retries:
                    logger.warning(
                        "Gemini 503 서버 혼잡 발생 (재시도 %d/%d, %.1f초 대기): %s",
                        attempt + 1,
                        max_503_retries,
                        backoff_delay,
                        err_str[:150],
                    )
                    time.sleep(backoff_delay)
                    continue

                meta["latency_seconds"] = round(time.monotonic() - started, 3)
                meta["status"] = "api_error"
                meta["error"] = err_str[:500]

                if is_503:
                    user_msg = (
                        "현재 AI 서비스(Gemini)가 일시적인 서버 혼잡(503 Service Unavailable)으로 지연되고 있습니다. "
                        "잠시 후 다시 질문해 주세요."
                    )
                elif is_429:
                    user_msg = (
                        "AI 서비스 요청 한도(Rate Limit)에 도달했습니다(429 Resource Exhausted). "
                        "잠시 후 다시 시도해 주세요."
                    )
                elif is_auth:
                    user_msg = "AI 서비스 인증 오류가 발생했습니다. API 키 및 접근 설정을 확인해 주세요."
                else:
                    user_msg = (
                        "AI 답변 생성 서비스에 일시적인 오류가 발생했습니다. "
                        "잠시 후 다시 시도해 주시거나 학사 공지 원문을 확인해 주세요."
                    )

                return user_msg, meta

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        min_threshold: float | None = None,
        max_chunks_per_notice: int = 2,
    ) -> list[Document]:
        """
        유사도 검색 및 엔티티/최신성 기반 리랭킹을 수행하여
        LLM 답변 근거로 활용할 관련 공지사항 청크 Document 리스트를 반환한다.
        동일 공지의 유효한 복수 청크(신청/동의 등)를 보존한다.
        """
        k = top_k or config.TOP_K
        threshold = min_threshold if min_threshold is not None else RELEVANCE_THRESHOLD
        entities = extract_query_entities(query)
        logger.info("유사도 검색 시작: query='%s', entities=%s, top_k=%d, threshold=%.2f", query, entities, k, threshold)

        # 1. 1차 벡터 검색 (relevance_scores 우선, 실패 시 score 기반 변환 폴백)
        # LangChain Chroma: score = 1.0 - distance / sqrt(2)
        # 대형 통합 DB(3,400+ 청크)에서 긴 문서 청크 독점 방지 및 회수율 확보를 위해 후보군을 충분히 확보
        candidate_k = max(k * 15, 60)
        raw_results = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            try:
                raw_results = self.vectorstore.similarity_search_with_relevance_scores(query, k=candidate_k)
            except Exception as e:
                logger.warning("similarity_search_with_relevance_scores 실패, distance 기반 변환 폴백: %s", e)
                try:
                    docs_with_dist = self.vectorstore.similarity_search_with_score(query, k=candidate_k)
                    raw_results = [(doc, 1.0 - float(dist) / 1.41421356) for doc, dist in docs_with_dist]
                except Exception as e2:
                    logger.error("유사도 검색 완전 실패: %s", e2)
                    return []

        if not raw_results:
            logger.info("검색 결과가 없습니다.")
            return []

        # 2. 관련성 임계값 검사 및 고유 전문 약어(Lexical Match) 구제
        # 학내 맥락(교육, 특강, 신청, 대회 등)이 있는 기술 질문은 정상 허용하되,
        # 일반 코드 생성 요청("파이썬으로 코드 짜줘")이나 기기 스펙("아이폰 스펙") 등 순수 무관 질문은 엄격히 차단한다.
        CAMPUS_INTENT_PATTERN = (
            r"(?:교내|대학|한성대|학교|학사|수강|교육|특강|신청|접수|방법|일정|기간|대상|모집|선발|"
            r"장학|학점|이수|대회|공모전|경진대회|프로그램|캠프|센터|동아리|설명회|특화|지원|학생)"
        )
        has_campus_intent = bool(re.search(CAMPUS_INTENT_PATTERN, query, re.IGNORECASE))

        CODE_GEN_REQUEST_PATTERN = (
            r"(?:코드\s*(?:짜줘|작성|구현|만들어|출력)|소스코드|알고리즘\s*(?:짜줘|구현)|구현해줘|코딩해줘|트리\s*구현|구현하는\s*코드)"
        )
        is_code_generation = bool(re.search(CODE_GEN_REQUEST_PATTERN, query, re.IGNORECASE))

        EXTERNAL_OFF_TOPIC_PATTERNS = [
            r"(?:아이폰|갤럭시|스마트폰\s*스펙|노트북\s*추천|그래픽카드|cpu|gpu)",
            r"(?:날씨|기온|미세먼지|주식|코인|비트코인|부동산|영화\s*추천|맛집\s*추천)",
        ]
        is_external_off_topic = any(re.search(pat, query, re.IGNORECASE) for pat in EXTERNAL_OFF_TOPIC_PATTERNS)

        is_off_topic = False
        if is_code_generation:
            is_off_topic = True
        elif is_external_off_topic and not has_campus_intent:
            is_off_topic = True
        elif not has_campus_intent and re.search(r"(?:이진\s*탐색|이진\s*트리|자료구조)", query, re.IGNORECASE):
            is_off_topic = True

        SPECIALIZED_TERMS = {
            "topcit", "toeic", "toefl", "cpa", "aicpa", "k-mooc", "kmooc", "ipp", "rotc"
        }
        # 고유 전문 약어 또는 영문 대문자 3자 이상 약어만 추출
        distinctive_subject_words = []
        if not is_off_topic:
            for w in re.findall(r"[a-zA-Z0-9\-_]{2,}", query):
                w_low = w.lower()
                if w_low in SPECIALIZED_TERMS or (w.isupper() and len(w) >= 3 and w not in {"FOR", "THE", "AND", "NOT"}):
                    distinctive_subject_words.append(w_low)

        filtered_raw = []
        for doc, score in raw_results:
            title = doc.metadata.get("title", "")
            adj_score = score

            # 무관 질문(off-topic)은 어휘 가산점을 절대 부여하지 않으며 높은 임계값을 요구
            if is_off_topic:
                if score >= 0.40:
                    filtered_raw.append((doc, score))
                continue

            # 단축 쿼리("TOPCIT 평가" 등) 고유 전문 약어 구제 (원시 점수 0.15 이상일 때만 적용)
            if distinctive_subject_words and score >= 0.15:
                if any(w in title.lower() for w in distinctive_subject_words):
                    adj_score = score + 0.08

            if adj_score >= threshold:
                filtered_raw.append((doc, adj_score))

        if not filtered_raw:
            logger.info("원시 관련성 임계값(%.3f) 이상의 유효 후보 문서가 없습니다.", threshold)
            return []


        # 최신 공지 기준일 탐색 (임계값을 통과한 후보군 대상)
        max_dt = None
        for doc, _ in filtered_raw:
            d_str = doc.metadata.get("date", "")
            if d_str:
                try:
                    dt = datetime.strptime(d_str[:10], "%Y-%m-%d")
                    if max_dt is None or dt > max_dt:
                        max_dt = dt
                except Exception:
                    pass

        # 3. 휴리스틱 리랭킹 가중치 계산 (원시 관련성 통과 후보군만 적용)
        # 공지와 상시 안내(guidance, faq, form)의 검색 정책을 분리
        scored_candidates = []
        is_schedule_query = any(k in query for k in ("기간", "마감", "언제", "일정", "일시", "시간", "접수", "날짜"))
        is_target_query = any(k in query for k in ("대상", "자격", "누구", "제외", "조건", "신청자"))

        for doc, score in filtered_raw:
            meta = doc.metadata
            title = meta.get("title", "")
            date_str = meta.get("date", "")
            content = doc.page_content
            c_status = meta.get("content_status", "")
            source_type = meta.get("source_type", "notice")
            is_guidance = source_type in ("guidance", "faq", "form")

            final_score = score

            # 본문 없이 제목만 있는 공지는 세부 질의 대응 불가하므로 감점
            if c_status == "title_only":
                final_score -= 0.15

            # [공지 전용 정책]: 연도 및 최신성 보정 (상시 안내/FAQ는 연도 불일치/경과일수 감점 배제)
            if not is_guidance:
                target_year = entities.get("year")
                if target_year:
                    if target_year in title or date_str.startswith(target_year) or entities.get("short_year", "") in content:
                        final_score += 0.30
                    else:
                        # 제목 또는 등록일자에서 타 연도(2024, 2025 등) 추출 (한글 년 결합 처리)
                        title_years = re.findall(r"(?:^|[^\d])(20\d{2})(?:[^\d]|$)", title)
                        doc_year = date_str[:4] if (date_str and len(date_str) >= 4 and date_str[:4].isdigit()) else ""
                        other_years = set(title_years)
                        if doc_year:
                            other_years.add(doc_year)
                        other_years.discard(target_year)
                        if other_years:
                            final_score -= 0.40  # 쿼리 연도와 상충하는 다른 연도 공지 강력 차단
                else:
                    if max_dt and date_str:
                        try:
                            doc_dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                            diff_days = (max_dt - doc_dt).days
                            if diff_days <= 90:
                                final_score += 0.22  # 최근 3개월 (당해 학기)
                            elif diff_days <= 180:
                                final_score += 0.05  # 최근 6개월 (직전 학기)
                            elif diff_days <= 365:
                                final_score -= 0.10  # 1년 이내 과거 공지
                            else:
                                final_score -= 0.18  # 1년 초과 과거 공지
                        except Exception:
                            pass

                # 학기 매칭 보정
                target_sem = entities.get("semester")
                if target_sem:
                    if target_sem in title or target_sem in content:
                        final_score += 0.12
                    other_sem = "1학기" if target_sem == "2학기" else "2학기"
                    if other_sem in title:
                        final_score -= 0.15

                # 차수 매칭 보정 (1차, 2차)
                target_round = entities.get("round")
                if target_round:
                    if target_round in title:
                        final_score += 0.22  # 제목에 차수(1차/2차)가 명시된 공지 강력 우대
                    elif target_round in content:
                        final_score += 0.06
                    other_round = "1차" if target_round == "2차" else "2차"
                    if other_round in title:
                        final_score -= 0.18

            # 청크 실질 내용이 너무 빈약한 구역(단순 OCR 노이즈 등) 감점
            if len(content.strip()) < 80:
                final_score -= 0.25

            # [질의 의도 기반 청크 선별]: 일정 또는 대상/제외 조건이 담긴 핵심 청크 우대
            if is_schedule_query:
                schedule_keywords = ("신청 기간", "신청기간", "접수 기간", "마감", "접수", "15:00", "18:00", "17:00", "까지", "부터")
                if any(kw in content for kw in schedule_keywords):
                    final_score += 0.12
            if is_target_query:
                target_keywords = ("대상자", "지원자격", "신청대상", "제외", "외국인", "자격", "신청자")
                if any(kw in content for kw in target_keywords):
                    final_score += 0.12

            # 공지 첫 청크(개요/대상/일정 집약부) 우대
            if meta.get("chunk_index") == 0:
                final_score += 0.05

            # 질의의 고유 주제어 매칭 보정
            if distinctive_subject_words:
                matched_title = [w for w in distinctive_subject_words if w in title.lower()]
                if matched_title:
                    final_score += 0.08 * len(matched_title)

            # 핵심 키워드 일치 보정
            if "국가장학금" in query:
                if "국가장학금" in title:
                    final_score += 0.18
                elif "국가장학금" in content:
                    final_score += 0.10
                else:
                    final_score -= 0.20
                if "국가고시" in title:
                    final_score -= 0.20

            if "신청" in query and "신청" in title:
                final_score += 0.08

            if "가구원" in query:
                if "가구원" in content or "가구원" in title:
                    final_score += 0.12

            scored_candidates.append((doc, final_score))

        # 리랭킹 점수 기준 내림차순 정렬
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # 4. 청크 선택 및 사실 혼입(context bleeding) 방지
        # 상위 1위 문서가 높은 관련도(top_score >= 0.70)를 가진 주 공지인 경우,
        # 해당 공지의 핵심 청크(신청일정, 대상자, 제외조건 등)를 최대 3개까지 수용하여 정보 누락을 방지
        context_docs = []
        url_chunk_counts = {}
        top_score = scored_candidates[0][1] if scored_candidates else 0.0
        top_url = (
            scored_candidates[0][0].metadata.get("url")
            or scored_candidates[0][0].metadata.get("parent_url")
            or scored_candidates[0][0].metadata.get("id")
            if scored_candidates else ""
        )
        effective_max_chunks = 3 if top_score >= 0.70 else max_chunks_per_notice

        for doc, cand_score in scored_candidates:
            doc.metadata["_score"] = cand_score
            url = doc.metadata.get("url") or doc.metadata.get("parent_url") or doc.metadata.get("id")

            # 서로 다른 공지 간 사실 혼입 방지 필터
            if threshold >= 0 and url != top_url and len(context_docs) >= 1:
                if top_score >= 0.70 and (top_score - cand_score > 0.12):
                    logger.info(
                        "타 공지 노이즈 청크 제외: top_score=%.3f, cand_score=%.3f, doc=%s",
                        top_score, cand_score, doc.metadata.get("title", "")[:30]
                    )
                    continue

            allowed_chunks = effective_max_chunks if url == top_url else max_chunks_per_notice
            count = url_chunk_counts.get(url, 0)
            if count < allowed_chunks:
                context_docs.append(doc)
                url_chunk_counts[url] = count + 1
            if len(context_docs) >= k:
                break

        return context_docs

    def query(self, question: str, top_k: int | None = None) -> dict:
        """
        RAG 전체 파이프라인을 수행한다.
        유사도 검색(무관 질문 임계값 차단) → 리랭킹 → LLM 생성 → 요약 응답 + 고유 출처 카드 반환.
        Gemini 503 재시도 및 429/인증 오류를 안전하게 처리하고 실행 메타데이터를 반환한다.
        """
        logger.info("RAG 질의 시작: '%s'", question)
        provider = config.LLM_PROVIDER.lower()
        model_name = {
            "gemini": config.GEMINI_MODEL,
            "local": config.LOCAL_LLM_MODEL,
            "openai": config.OPENAI_MODEL,
        }.get(provider, "unknown")

        # 유사도 검색 및 리랭킹
        context_docs = self.retrieve(question, top_k=top_k)

        # 원시 관련성 임계값(0.25)을 통과한 공지가 없으면 LLM 호출 없이 즉시 유보
        if not context_docs:
            return {
                "answer": "관련 공지를 찾지 못했습니다.",
                "sources": [],
                "status": "no_context",
                "api_called": False,
                "provider": provider,
                "model": model_name,
                "latency_seconds": 0.0,
                "error": None,
            }

        if self.llm is None:
            raise RuntimeError(
                "LLM이 로드되지 않았습니다. "
                "CampusRAG(load_llm=True)로 초기화하세요."
            )

        # 검색된 최우선(Top-1) 공지가 본문 없는 title_only이거나 모든 공지가 title_only인 경우 조기 안내
        top_doc = context_docs[0]
        if top_doc.metadata.get("content_status") == "title_only" or all(doc.metadata.get("content_status") == "title_only" for doc in context_docs):
            first = top_doc.metadata
            answer = (
                f"검색된 공지 「{first.get('title', '')}」 "
                f"({first.get('date', '')}, {first.get('source', '')})는 "
                "수집된 정보가 제목뿐이므로 세부 내용을 확인할 수 없습니다. "
                "아래 원문 보기에서 이미지·첨부파일을 확인해 주세요."
            )
            meta = {
                "provider": provider,
                "model": model_name,
                "api_called": False,
                "status": "title_only_notice",
                "latency_seconds": 0.0,
                "error": None,
            }
        else:
            answer, meta = self._invoke_llm_with_error_handling({
                "question": question,
                "context": format_retrieved_docs(context_docs),
            })

        # LLM이 관련 공지를 찾지 못했다고 답변한 경우 출처 카드 비우기
        clean_ans = answer.strip()
        if any(w in clean_ans for w in ("관련 공지를 찾지 못했습니다", "공지를 찾을 수 없습니다", "해당 공지를 찾을 수 없습니다")):
            return {
                "answer": answer,
                "sources": [],
                **meta,
            }

        # 출처 카드는 URL 기준으로 중복 제거하여 사용자에게 제공
        seen_urls = set()
        deduped_sources = []
        for doc in context_docs:
            url = doc.metadata.get("url") or doc.metadata.get("parent_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped_sources.append(
                    {
                        "title": doc.metadata.get("title", ""),
                        "source": doc.metadata.get("source", ""),
                        "date": doc.metadata.get("date", ""),
                        "url": url,
                        "category": doc.metadata.get("category", ""),
                    }
                )

        return {
            "answer": answer,
            "sources": deduped_sources,
            **meta,
        }


def print_retrieve_results(results: list[Document]) -> None:
    """검색 결과를 보기 좋게 출력한다 (CLI 디버깅용)."""
    print(f"\n{'='*60}")
    print(f"검색 결과: {len(results)}건")
    print(f"{'='*60}")
    for i, doc in enumerate(results, 1):
        meta = doc.metadata
        print(f"\n[{i}] {meta.get('title', '제목 없음')}")
        print(f"    출처: {meta.get('source', '')} | 분류: {meta.get('category', '')}")
        print(f"    날짜: {meta.get('date', '')} | 링크: {meta.get('url', '')}")
        print(f"    내용: {doc.page_content[:100]}...")
    print(f"\n{'='*60}")
