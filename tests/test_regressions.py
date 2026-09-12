"""샘플 혼입, 중복 적재, 출처/답변 불일치 회귀 테스트 (모델 다운로드 없음)."""
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableLambda
from fastapi.testclient import TestClient

from core import embedder
from core.rag import CampusRAG
from crawler.hansung_pw import HansungPlaywrightCrawler


class TinyEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def test_upsert_and_replace_remove_legacy_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(embedder, 'get_embedding_model', lambda: TinyEmbeddings())
    def ingest(docs, **kwargs):
        return embedder.ingest_to_chroma(docs, str(tmp_path), 'regression', **kwargs)
    old = Document(page_content='가짜 국가장학금', metadata={'id': 'sample', 'url': 'https://example.com/sample'})
    store = ingest([old])
    # 기존 구현이 발급한 랜덤 ID도 제거되어야 한다.
    store.add_documents([old], ids=['legacy-random-id'])
    real = Document(page_content='신청 기간 본문', metadata={'id': 'page-1', 'url': 'https://example.com/real'})
    ingest([real, real], replace=True)
    assert store._collection.count() == 1
    real.page_content = '변경된 신청 기간'
    real.metadata['id'] = 'page-2'
    ingest([real])
    assert store._collection.count() == 1
    assert store.get()['documents'] == ['변경된 신청 기간']
    with pytest.raises(ValueError):
        ingest([], replace=True)
    assert store._collection.count() == 1


def test_query_uses_exactly_same_documents_for_context_and_cards():
    rag = CampusRAG.__new__(CampusRAG)
    doc = Document(page_content='신청 기간은 8월 12일부터 9월 9일까지', metadata={'title': '국가장학금 신청 안내', 'url': 'https://example.com/real'})
    rag.retrieve = Mock(return_value=[doc])
    prompts = []
    def answer(prompt):
        prompts.append(prompt.to_string())
        return '국가장학금 신청 공지를 찾았습니다.'
    rag.llm = RunnableLambda(answer)
    rag.chain = rag._build_chain()
    result = rag.query('국가장학금 공지 알려줘', top_k=1)
    rag.retrieve.assert_called_once_with('국가장학금 공지 알려줘', top_k=1)
    assert doc.page_content in prompts[0]
    assert result['sources'][0]['url'] in prompts[0]
    assert '본문에서 세부 내용을 확인할 수 없습니다' in prompts[0]


def test_empty_retrieval_does_not_generate():
    rag = CampusRAG.__new__(CampusRAG)
    rag.llm = Mock()
    rag.chain = Mock()
    rag.retrieve = Mock(return_value=[])
    assert rag.query('없는 공지')['sources'] == []
    rag.chain.invoke.assert_not_called()


def test_api_query_forwards_top_k(monkeypatch):
    import backend.main as api
    rag = Mock()
    rag.query.return_value = {'answer': '확인한 공지', 'sources': []}
    monkeypatch.setattr(api, 'rag_instance', rag)
    client = TestClient(api.app)
    response = client.post('/api/query', json={'question': '국가장학금', 'top_k': 1})
    assert response.status_code == 200
    rag.query.assert_called_once_with('국가장학금', top_k=1)


def test_crawler_resolves_relative_links_and_stable_ids():
    crawler = HansungPlaywrightCrawler()
    row = Mock()
    cells = [Mock() for _ in range(6)]
    row.query_selector_all.return_value = cells
    link = cells[1].query_selector.return_value
    link.inner_text.return_value = '국가장학금 신청 안내'
    link.get_attribute.return_value = '223971/artclView.do'
    cells[4].inner_text.return_value = '2026.08.12'
    cells[2].inner_text.return_value = '학생복지팀'
    base = 'https://www.hansung.ac.kr/bbs/hansung/2127/artclList.do'
    first = crawler._parse_row(row, '학교본부', '장학', 1, 0, base)
    later = crawler._parse_row(row, '학교본부', '장학', 2, 5, base)
    assert first.url == 'https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do'
    assert first.id == later.id
    link.get_attribute.return_value = 'javascript:open()'
    assert crawler._parse_row(row, '학교본부', '장학', 1, 0, base) is None


def test_crawler_rejects_http_error_and_excludes_attachment_text():
    crawler = HansungPlaywrightCrawler()
    page = Mock()
    page.goto.return_value.ok = False
    assert crawler._fetch_detail(page, 'https://example.com/missing') is None
    page.query_selector.assert_not_called()
    page.goto.return_value.ok = True
    page.query_selector.return_value.inner_text.return_value = ''
    assert crawler._fetch_detail(page, 'https://example.com/image') == ''
    page.query_selector.assert_called_once_with('.view.viewCont .txt')


def test_image_only_notice_is_found_but_does_not_invent_deadlines():
    rag = CampusRAG.__new__(CampusRAG)
    rag.llm = Mock()
    rag.chain = Mock()
    rag.retrieve = Mock(return_value=[Document(
        page_content='2026년 2학기 국가장학금 2차 신청 안내',
        metadata={'title': '2026년 2학기 국가장학금 2차 신청 안내',
                  'date': '2026-08-12', 'source': '학생복지팀',
                  'content_status': 'title_only', 'url': 'https://example.com/notice'},
    )])
    result = rag.query('국가장학금 신청 기간이 언제야?')
    assert '찾지 못했습니다' not in result['answer']
    assert '세부 내용을 확인할 수 없습니다' in result['answer']
    assert '국가장학금' in result['answer']
    assert len(result['sources']) == 1
    rag.chain.invoke.assert_not_called()
