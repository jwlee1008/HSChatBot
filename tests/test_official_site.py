from pathlib import Path
from bs4 import BeautifulSoup
from crawler.official_site import canonical, extract_page, discover, table_text, collect, atomic_json, SEED

FIXTURE = Path(__file__).parent/'fixtures/hansung_grading.html'
ITEM = {'url':SEED,'title':'시험 및 성적평가','menu_path':['교육정보','성적/졸업'],'interval_days':14}


def test_real_grading_preserves_table_rules_tabs_and_dates():
    record = extract_page(FIXTURE.read_text(), ITEM)
    assert record['source_updated_at'] == '2026-02-26'
    assert '반올림하지 않음' in record['content']
    assert '30% 이내' in record['content'] and '70%' in record['content']
    assert '4.5' in record['content'] and '매 학기 수업시간의 1/4' in record['content']
    assert len(record['tabs']) == 3
    assert record['tabs'][1]['url'].endswith('/6232/subview.do')
    assert 'COPYRIGHT' not in record['content']


def test_spanning_cells_are_carried_into_each_row():
    soup = BeautifulSoup('<table><tr><th>등급</th><th>비율</th></tr><tr><td>A</td><td rowspan="2">70%</td></tr><tr><td>B</td></tr></table>','html.parser')
    assert table_text(soup.table).splitlines()[-1] == 'B | 70%'


def test_url_scope():
    assert canonical('/hansung/6231/subview.do#tab') == SEED
    for url in ['https://evil.test/hansung/6231/subview.do','http://127.0.0.1/','/topLogin/login.do','javascript:alert(1)']:
        assert canonical(url) is None


def test_discovery_keeps_deepest_breadcrumb_and_flags_external():
    html='<nav id="menuUItop"><li class="li_1"><a href="/hansung/6231/subview.do">교육정보</a><ul><li><a href="/hansung/6231/subview.do">성적평가</a></li><li><a href="https://external.test">규정</a></li></ul></li></nav>'
    items=discover(html)
    assert items[0]['menu_path'] == ['교육정보','성적평가']
    assert items[1]['collection_status'] == 'external_or_dynamic_review'


def test_failed_refresh_preserves_old_content_and_success_timestamp(tmp_path, monkeypatch):
    out=tmp_path/'pages.json'
    previous = {**ITEM, 'id':'old','content':'기존 본문','last_checked_at':'2020-01-01T00:00:00+00:00'}
    atomic_json(out,[previous])
    class FakeFetcher:
        def __init__(self,*a): pass
        def get(self,url): return '<html>maintenance</html>'
    monkeypatch.setattr('crawler.official_site.Fetcher',FakeFetcher)
    report=collect(out,tmp_path/'inventory.json',force=True)
    import json
    assert json.loads(out.read_text())[0] == previous
    assert report['errors']


def test_notice_archive_pinned_old_rows_do_not_end_backfill():
    from crawler.notice_archive import parse_listing
    def row(date, cls, id):
        return f'<tr class="{cls}"><td class="td-title"><a href="/bbs/hansung/2127/{id}/artclView.do">공지</a></td><td class="td-date">{date}</td></tr>'
    html='<table><tbody>'+row('2020.01.01','notice',1)+row('2026.09.14','',2)+'</tbody></table>'
    notices, done=parse_listing(html,2127,'2023-09-14')
    assert len(notices)==1 and not done


def test_guidance_provenance_survives_chunking():
    from core.embedder import split_notice_into_chunks
    record=extract_page(FIXTURE.read_text(), ITEM)
    record['last_checked_at']='2026-09-14T00:00:00+00:00'
    chunks=split_notice_into_chunks(record)
    assert len(chunks)>1
    assert all(c.metadata['source_type']=='guidance' for c in chunks)
    assert all(c.metadata['date']=='2026-02-26' for c in chunks)
    assert all(c.metadata['last_checked_at']==record['last_checked_at'] for c in chunks)


def test_atomic_json_handles_damaged_document_unicode(tmp_path):
    import json
    path=tmp_path/'out.json'
    atomic_json(path,{'text':'앞\ud800뒤'})
    assert json.loads(path.read_text(encoding='utf-8'))['text']=='앞\ufffd뒤'
