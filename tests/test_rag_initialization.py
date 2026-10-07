"""Offline regressions for model reuse, retryable initialization, and API responsiveness."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

import backend.main as api
import core.rag as core_rag
from backend.schemas import QueryRequest


@pytest.fixture
def isolated_rag(monkeypatch):
    store = Mock()
    store._collection.count.return_value = 1
    load_store = Mock(return_value=store)
    load_llm = Mock(return_value=RunnableLambda(lambda prompt: "공식 공지를 확인하세요."))
    monkeypatch.setattr(core_rag, "get_chroma_vectorstore", load_store)
    monkeypatch.setattr(core_rag.CampusRAG, "_load_llm", load_llm)
    monkeypatch.setattr(api, "rag_instance", None)
    monkeypatch.setattr(api, "_rag_lock", asyncio.Lock())
    return load_store, load_llm


def test_prewarmed_first_query_reuses_embedding_store_and_instance(isolated_rag, monkeypatch):
    load_store, load_llm = isolated_rag
    doc = Document(page_content="도서관 이용은 공식 안내를 확인하세요.", metadata={
        "title": "도서관 안내", "url": "https://www.hansung.ac.kr/library",
    })

    async def scenario():
        prewarmed = await api.get_or_init_rag(load_llm=False)
        store = prewarmed.vectorstore
        monkeypatch.setattr(prewarmed, "retrieve", Mock(return_value=[doc]))
        response = await api.query(QueryRequest(question="도서관 안내", top_k=1))
        assert response.status == "success"
        assert response.answer == "공식 공지를 확인하세요."
        assert api.rag_instance is prewarmed
        assert prewarmed.vectorstore is store
        assert prewarmed.llm is not None
        assert prewarmed.chain is not None

    asyncio.run(scenario())
    # The store factory owns the heavyweight embedding load; it must run only once.
    load_store.assert_called_once_with()
    load_llm.assert_called_once_with()


def test_concurrent_backend_initialization_uses_one_llm(isolated_rag):
    load_store, load_llm = isolated_rag

    async def scenario():
        prewarmed = await api.get_or_init_rag(load_llm=False)
        results = await asyncio.gather(*(api.get_or_init_rag(load_llm=True) for _ in range(8)))
        assert all(rag is prewarmed for rag in results)

    asyncio.run(scenario())
    load_store.assert_called_once_with()
    load_llm.assert_called_once_with()


def test_concurrent_core_ensure_llm_loads_once(isolated_rag):
    _, load_llm = isolated_rag
    rag = core_rag.CampusRAG(load_llm=False)
    barrier = threading.Barrier(4)
    started = threading.Event()
    release = threading.Event()
    llm = load_llm.return_value

    def blocked_load():
        started.set()
        assert release.wait(timeout=2)
        return llm

    load_llm.side_effect = blocked_load

    def ensure():
        barrier.wait(timeout=2)
        rag.ensure_llm()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(ensure) for _ in range(4)]
        try:
            assert started.wait(timeout=2)
        finally:
            release.set()
        for future in futures:
            future.result(timeout=2)
    load_llm.assert_called_once_with()
    assert rag.llm is llm
    assert rag.chain is not None


@pytest.mark.parametrize("failure_stage", ["llm", "chain"])
def test_initialization_failure_retries_without_reloading_embeddings(isolated_rag, monkeypatch, failure_stage):
    load_store, load_llm = isolated_rag
    llm = load_llm.return_value
    if failure_stage == "llm":
        load_llm.side_effect = [RuntimeError("test initialization failure"), llm]
    else:
        chain = core_rag.CampusRAG.__new__(core_rag.CampusRAG)._build_chain(llm)
        monkeypatch.setattr(core_rag.CampusRAG, "_build_chain", Mock(side_effect=[
            RuntimeError("test chain failure"), chain,
        ]))

    async def scenario():
        # Even a failed first query preserves the already loaded retrieval model.
        with pytest.raises(RuntimeError):
            await api.get_or_init_rag(load_llm=True)
        failed = api.rag_instance
        assert failed is not None
        assert failed.llm is None
        assert failed.chain is None
        ready = await api.get_or_init_rag(load_llm=True)
        assert ready is failed
        assert ready.llm is llm
        assert ready.chain is not None

    asyncio.run(scenario())
    load_store.assert_called_once_with()
    assert load_llm.call_count == 2


@pytest.mark.parametrize("endpoint", ["query", "retrieve"])
def test_slow_sync_request_keeps_health_responsive(monkeypatch, endpoint):
    started = threading.Event()
    release = threading.Event()
    worker_threads = []
    rag = Mock()
    rag.vectorstore._collection.count.return_value = 1
    rag.llm = object()

    def slow_work(question, top_k):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        if endpoint == "query":
            return {"answer": "공식 안내", "sources": [], "status": "success"}
        return []

    getattr(rag, endpoint).side_effect = slow_work
    monkeypatch.setattr(api, "rag_instance", rag)

    async def scenario():
        event_loop_thread = threading.get_ident()
        request_task = asyncio.create_task(getattr(api, endpoint)(QueryRequest(question="공식 안내", top_k=1)))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert not request_task.done()
            health = await asyncio.wait_for(api.health_check(), timeout=0.5)
            assert health.status == "ok"
            assert health.doc_count == 1
            assert len(worker_threads) == 1
            assert worker_threads[0] != event_loop_thread
        finally:
            release.set()
            await request_task

    asyncio.run(scenario())


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "models/gemini-3.8-flash", "gemini-2.0-flash"])
def test_gemini_generation_config_is_serialized_without_api_call(monkeypatch, model):
    import langchain_google_genai.chat_models as google_chat

    sdk_client = Mock()
    sdk_client.models.generate_content.side_effect = AssertionError("Offline test must not call an API")
    constructor = Mock(return_value=sdk_client)
    monkeypatch.setattr(google_chat, "Client", constructor)
    monkeypatch.setattr(core_rag.config, "GEMINI_API_KEY", "offline-test-key")
    monkeypatch.setattr(core_rag.config, "GEMINI_MODEL", model)

    llm = core_rag.CampusRAG.__new__(core_rag.CampusRAG)._load_gemini_llm()
    if "gemini-3.8-" in model:
        chat = llm.bound
        params = chat._prepare_params(None, **llm.kwargs).model_dump(exclude_none=True)
        assert all(name not in params for name in ("temperature", "top_p", "top_k", "candidate_count"))
        assert params["thinking_config"]["thinking_level"] == "LOW"
        assert "thinking_budget" not in params["thinking_config"]
    else:
        chat = llm
        params = chat._prepare_params(None).model_dump(exclude_none=True)
        assert params["temperature"] == 0.3
        assert "thinking_config" not in params
    assert chat.max_retries == 0
    assert chat.timeout == core_rag.config.GEMINI_TIMEOUT_SECONDS
    constructor.assert_called_once()
    sdk_client.models.generate_content.assert_not_called()
