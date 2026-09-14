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
    # 2자리 연도 ('26, '27 또는 26년, 27년 등)
    y2 = re.search(r"(?:'(\d{2})|\b(\d{2})\s*(?:년|학년도))", query)
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
        )

    def _build_chain(self):
        """LangChain LCEL 체인을 구성한다."""
        return RAG_PROMPT | self.llm | StrOutputParser()

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
        candidate_k = max(k * 4, 15)
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

        # 2. 관련성 미달 후보는 최신성·연도 가산점 전에 즉시 제외!
        # 낮은 관련도의 최신 공지가 가산점으로 통과하는 현상을 원천 방지
        filtered_raw = [(doc, score) for doc, score in raw_results if score >= threshold]
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
        scored_candidates = []
        for doc, score in filtered_raw:
            meta = doc.metadata
            title = meta.get("title", "")
            date_str = meta.get("date", "")
            content = doc.page_content
            c_status = meta.get("content_status", "")

            final_score = score

            # 본문 없이 제목만 있는 공지는 세부 질의 대응 불가하므로 감점
            if c_status == "title_only":
                final_score -= 0.15

            # 연도 매칭 보정 (동적 연도 지원)
            target_year = entities.get("year")
            if target_year:
                # 쿼리에 명시된 연도가 제목(적용 연도), 본문, 또는 등록일자에 포함된 경우
                if target_year in title or target_year in date_str or entities.get("short_year", "") in content:
                    final_score += 0.25
                else:
                    # 후보 제목에 명시된 다른 연도(예: 2024, 2025, 2027 등)가 있으면 감점
                    other_years = re.findall(r"\b(20\d{2})\b", title)
                    if any(y != target_year for y in other_years):
                        final_score -= 0.20
            else:
                # 쿼리에 연도가 없는 경우: 검색 후보군 중 최신 등록일 기준 상대적 최신성 가중치
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
                if target_round in title or target_round in content:
                    final_score += 0.12
                other_round = "1차" if target_round == "2차" else "2차"
                if other_round in title:
                    final_score -= 0.15

            # 질의의 고유 주제어(예: 편입생, 폐강, TOPCIT 등) 매칭 보정
            query_subject_words = [
                w for w in re.findall(r"[가-힣a-zA-Z0-9]{2,}", query)
                if w not in {
                    "언제", "누구", "어디", "어디로", "어떻게", "알려줘", "알려",
                    "기간", "신청", "내용", "기준", "방법", "대상자", "대상",
                    "안내", "관련", "대한", "학년도", "학기"
                }
            ]
            if query_subject_words:
                matched_title = [w for w in query_subject_words if w in title or (len(w) >= 3 and w[:2] in title)]
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

            if "가구원" in query:
                if "가구원" in content or "가구원" in title:
                    final_score += 0.12

            scored_candidates.append((doc, final_score))

        # 리랭킹 점수 기준 내림차순 정렬
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # 4. 동일 공지의 여러 유효 청크(신청기간, 동의기간 등)는 근거에 함께 보존하되, 특정 공지의 과도한 독점 방지
        # 및 서로 다른 공지 간의 사실 혼입(context bleeding) 방지
        context_docs = []
        url_chunk_counts = {}
        top_score = scored_candidates[0][1] if scored_candidates else 0.0
        top_url = (
            scored_candidates[0][0].metadata.get("url")
            or scored_candidates[0][0].metadata.get("parent_url")
            or scored_candidates[0][0].metadata.get("id")
            if scored_candidates else ""
        )

        for doc, cand_score in scored_candidates:
            doc.metadata["_score"] = cand_score
            url = doc.metadata.get("url") or doc.metadata.get("parent_url") or doc.metadata.get("id")

            # 서로 다른 공지 간 사실 혼입 방지 필터:
            # 만약 1위 공지의 점수가 명확히 높고(>= 0.70), 이미 최소 1개 이상의 청크가 채택되었을 때,
            # 현재 후보가 1위 공지와 다른 공지이면서 점수 격차가 유의미하게 크면(top_score - cand_score > 0.12)
            # 무관한 타 공지 내용이 컨텍스트에 섞여 사실 왜곡을 일으키지 않도록 제외한다.
            # (단, threshold < 0인 디버깅/테스트 강제 반환 모드에서는 필터를 건너뜀)
            if threshold >= 0 and url != top_url and len(context_docs) >= 1:
                if top_score >= 0.70 and (top_score - cand_score > 0.12):
                    logger.info(
                        "타 공지 노이즈 청크 제외: top_score=%.3f, cand_score=%.3f, doc=%s",
                        top_score, cand_score, doc.metadata.get("title", "")[:30]
                    )
                    continue

            count = url_chunk_counts.get(url, 0)
            if count < max_chunks_per_notice:
                context_docs.append(doc)
                url_chunk_counts[url] = count + 1
            if len(context_docs) >= k:
                break

        return context_docs

    def query(self, question: str, top_k: int | None = None) -> dict:
        """
        RAG 전체 파이프라인을 수행한다.
        유사도 검색(무관 질문 임계값 차단) → 리랭킹 → LLM 생성 → 요약 응답 + 고유 출처 카드 반환.
        """
        logger.info("RAG 질의 시작: '%s'", question)

        # 유사도 검색 및 리랭킹
        context_docs = self.retrieve(question, top_k=top_k)

        # 원시 관련성 임계값(0.25)을 통과한 공지가 없으면 LLM 호출 없이 즉시 유보
        if not context_docs:
            return {"answer": "관련 공지를 찾지 못했습니다.", "sources": []}

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
        else:
            answer = self.chain.invoke({
                "question": question,
                "context": format_retrieved_docs(context_docs),
            })

        # LLM이 관련 공지를 찾지 못했다고 답변한 경우 출처 카드 비우기
        clean_ans = answer.strip()
        if any(w in clean_ans for w in ("관련 공지를 찾지 못했습니다", "공지를 찾을 수 없습니다", "해당 공지를 찾을 수 없습니다")):
            return {"answer": answer, "sources": []}

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
