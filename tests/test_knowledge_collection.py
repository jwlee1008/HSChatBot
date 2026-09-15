from pathlib import Path
from bs4 import BeautifulSoup
from crawler.official_site import extract_page, table_text
from crawler.faq import parse_faq
from core.extractor.knowledge import KnowledgeEnricher, aggregate_status, detect_format

ROOT=Path(__file__).parent/'fixtures'
ITEM={'url':'https://www.hansung.ac.kr/hansung/6332/subview.do','title':'식단','menu_path':['대학생활','식단']}


def test_diet_table_inside_form_is_preserved_with_dates():
    record=extract_page((ROOT/'hansung_diet.html').read_text(),ITEM)
    assert '치즈치킨까스카레동' in record['content']
    assert '2026.09.15' in record['content']
    assert record['coverage_status']=='current_week_diet_html'


def test_viewer_download_found_without_file_extension():
    record=extract_page((ROOT/'hansung_viewer.html').read_text(),{**ITEM,'title':'장학제도'})
    assert any(a['url'].endswith('/viewer/hansung/187/307/fileDown.do') for a in record['attachments'])


def test_calendar_events_survive_html_cleanup():
    html='<article id="_contentBuilder"><div id="schdulWrap">'+(ROOT/'hansung_calendar_year.html').read_text()+'</div></article>'
    record=extract_page(html,{**ITEM,'title':'학부학사일정'})
    assert '2026.01.02' in record['content'] and '시무식' in record['content']
    assert '2026.09.14' in record['content'] and '초과학기자 등록' in record['content']


def test_media_detected_by_bytes_not_download_button_label(tmp_path):
    pdf=tmp_path/'fileDown.do';pdf.write_bytes(b'%PDF-1.7\n')
    assert detect_format(pdf,'https://www.hansung.ac.kr/viewer/hansung/187/307/fileDown.do')=='pdf'


def test_enrichment_rebuilds_from_html_and_retains_partial(monkeypatch):
    enricher=KnowledgeEnricher.__new__(KnowledgeEnricher)
    monkeypatch.setattr(enricher,'extract',lambda a:{**a,'text':'새 신청 기간 9월 20일','status':'partial','format':'pdf'})
    old={'title':'안내','content':'HTML\n\n옛 신청 기간 9월 10일','html_content':'HTML',
         'attachments':[{'url':'https://www.hansung.ac.kr/a.pdf','name':'첨부'}]}
    new=enricher.enrich(old)
    assert '9월 10일' not in new['content']
    assert new['content'].count('9월 20일')==1
    assert new['media_extraction_status']=='partial'
    assert enricher.enrich(new)['content']==new['content']


def test_failed_or_unsupported_media_not_marked_complete():
    assert aggregate_status([{'status':'failed','text':''}])=='failed_or_unsupported'
    assert aggregate_status([{'status':'success','text':'근거'},{'status':'failed','text':''}])=='partial'


def test_faq_inline_answer_and_tables_preserved():
    html='<div class="faq-list"><ul><li><a class="question"><span class="cate-name">성적</span> 반올림?</a><div class="answer"><p>반올림하지 않음</p><table><tr><td>A+</td><td>4.5</td></tr></table></div></li></ul></div><span class="_totPage">18</span>'
    docs,total=parse_faq(html,'https://www.hansung.ac.kr/bbs/hansung/2148/artclList.do?page=1')
    assert total==18
    assert docs[0]['source_type']=='faq' and docs[0]['date']==''
    assert '반올림하지 않음' in docs[0]['content'] and 'A+ | 4.5' in docs[0]['content']
    shifted,_=parse_faq(html,'https://www.hansung.ac.kr/bbs/hansung/2148/artclList.do?page=2')
    assert docs[0]['id']==shifted[0]['id']


def test_enrichment_cli_preserves_prior_success_on_refresh_failure(tmp_path, monkeypatch):
    import json
    from scripts import enrich_official_pages as cli
    raw=tmp_path/'raw.json';out=tmp_path/'enriched.json'
    doc={'url':ITEM['url'],'title':'안내','content':'현재 HTML'}
    old={**doc,'content':'이전에 성공한 PDF 근거','html_content':'이전 HTML',
         'media_extraction_status':'complete','media_attempted_at':'2026-01-01T00:00:00+00:00'}
    raw.write_text(json.dumps([doc]));out.write_text(json.dumps([old]))
    class Failed:
        def __init__(self,**kwargs):pass
        def enrich(self,record):return {**record,'html_content':record['content'],'media_extraction_status':'failed_or_unsupported'}
    monkeypatch.setattr(cli,'KnowledgeEnricher',Failed)
    monkeypatch.setattr('sys.argv',['enrich','--input',str(raw),'--output',str(out)])
    cli.main()
    saved=json.loads(out.read_text())[0]
    assert saved['content']==old['content']
    assert saved['media_attempted_at']==old['media_attempted_at']
    assert saved['media_refresh_status']=='failed_or_unsupported'
    report=json.loads(Path(str(out)+'.report.json').read_text())
    assert report['documents'][0]['status']=='failed_or_unsupported'
    assert report['documents'][0]['previous_result_retained']


def test_hwpx_download_handler_detected_from_archive(tmp_path):
    import zipfile
    file=tmp_path/'download.do'
    with zipfile.ZipFile(file,'w') as z:
        z.writestr('Contents/section0.xml','<section/>')
        z.writestr('Contents/content.hpf','<package/>')
    assert detect_format(file,'https://www.hansung.ac.kr/bbs/hansung/2195/1/download.do')=='hwpx'


def test_notice_collector_rejects_faq_even_with_answer_tables():
    import pytest
    from crawler.notice_archive import parse_listing
    with pytest.raises(ValueError, match='FAQ accordion'):
        parse_listing('<div class="faq-list"><table><tbody><tr><td>answer</td></tr></tbody></table></div>',2148,'2023-09-14')


def test_backfill_resume_rejects_ambiguous_multiple_boards(tmp_path):
    import pytest
    from crawler.notice_archive import collect
    with pytest.raises(ValueError, match='exactly one board'):
        collect([2127,2195],tmp_path/'archive.json','2023-09-14',start_page=34)
    assert not (tmp_path/'archive.json').exists()
