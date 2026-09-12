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


class CampusRAG:
    """
    CampusRAG 핵심 클래스.

    - retrieve(): Chroma DB에서 유사도 검색만 수행 (LLM 불필요)
    - query(): 유사도 검색 + LLM 생성까지 수행 (RAG 전체 파이프라인)
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
        """HuggingFace 로컬 모델(gemma-2-2b-it)을 로드한다."""
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
            repetition_penalty=1.2,
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

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """
        유사도 검색만 수행하여 관련 공지사항 Document 리스트를 반환한다.
        LLM 없이도 동작한다.

        Args:
            query: 검색 질의 문자열
            top_k: 반환할 문서 수 (기본값: config.TOP_K)

        Returns:
            유사도 순으로 정렬된 Document 리스트
        """
        k = top_k or config.TOP_K
        logger.info("유사도 검색: query='%s', top_k=%d", query, k)
        results = self.vectorstore.similarity_search(query, k=k)
        logger.info("검색 결과: %d건", len(results))
        return results

    def query(self, question: str, top_k: int | None = None) -> dict:
        """
        RAG 전체 파이프라인을 수행한다.
        유사도 검색 → LLM 생성 → 요약 응답 + 출처 정보 반환.

        Args:
            question: 학생의 자연어 질문

        Returns:
            {
                "answer": "LLM이 생성한 요약 답변",
                "sources": [검색된 Document 리스트 (출처 카드용)]
            }
        """
        if self.llm is None:
            raise RuntimeError(
                "LLM이 로드되지 않았습니다. "
                "CampusRAG(load_llm=True)로 초기화하세요."
            )

        logger.info("RAG 질의: '%s'", question)

        # 출처 정보를 별도로 가져옴
        sources = self.retrieve(question, top_k=top_k)

        # LLM 체인으로 답변 생성
        if not sources:
            return {"answer": "관련 공지를 찾지 못했습니다.", "sources": []}
        if all(doc.metadata.get("content_status") == "title_only" for doc in sources):
            # 이미지 공지에 본문이 없으면 LLM이 일정 등을 지어내지 않도록 안내한다.
            first = sources[0].metadata
            answer = (
                f"검색된 공지 {len(sources)}건이 있습니다: 「{first.get('title', '')}」 "
                f"({first.get('date', '')}, {first.get('source', '')}).\n"
                "수집된 정보가 제목뿐이므로 신청 기간 등 세부 내용을 확인할 수 없습니다. "
                "아래 원문 보기에서 이미지·첨부파일을 확인해 주세요."
            )
        else:
            answer = self.chain.invoke({
                "question": question,
                "context": format_retrieved_docs(sources),
            })

        return {
            "answer": answer,
            "sources": [
                {
                    "title": doc.metadata.get("title", ""),
                    "source": doc.metadata.get("source", ""),
                    "date": doc.metadata.get("date", ""),
                    "url": doc.metadata.get("url", ""),
                    "category": doc.metadata.get("category", ""),
                }
                for doc in sources
            ],
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
