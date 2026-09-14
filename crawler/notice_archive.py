"""Resumable, bounded notice backfill. Public HTML only; attachment extraction is explicit.

Writes a separate archive, keeps existing records on HTTP failure, inventories missing
bodies and attachments, and checkpoints each completed notice. Does not touch Chroma.
"""
import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from crawler.official_site import BASE, Fetcher, atomic_json, clean


def parse_listing(html, board, since):
    soup=BeautifulSoup(html,'html.parser')
    rows=soup.select('table tbody tr')
    if not rows:
        raise ValueError('listing_rows_missing')
    notices=[]
    regular_dates=[]
    for row in rows:
        link=row.select_one('td.td-title a[href]')
        date=row.select_one('td.td-date')
        if not link or not date:
            continue
        url=urljoin(BASE,link['href'])
        if not re.fullmatch(r'https://www\.hansung\.ac\.kr/bbs/hansung/\d+/\d+/artclView\.do',url):
            continue
        date=clean(date.get_text()).replace('.','-')[:10]
        if 'notice' not in row.get('class',[]):
            regular_dates.append(date)
        if date < since:
            continue
        writer=row.select_one('.td-write')
        title=clean(link.get_text())
        notices.append({'id':hashlib.sha256(url.encode()).hexdigest(),'url':url,'title':title,
                        'date':date,'source':clean(writer.get_text()) if writer else '학교본부',
                        'category':'공지','source_type':'notice','board_id':str(board)})
    return notices, bool(regular_dates) and max(regular_dates) < since


def collect(board_ids, output, since, max_pages=30, max_notices=300, refresh=False, enrich=False):
    from core.extractor.pipeline import NoticeEnricher
    fetch=Fetcher()
    enricher=NoticeEnricher() if enrich else None
    link_parser=NoticeEnricher.__new__(NoticeEnricher)
    documents={d['url']:d for d in json.loads(Path(output).read_text())} if Path(output).exists() else {}
    status={'started_at':datetime.now(timezone.utc).isoformat(),'since':since,'boards':{},'errors':[],
            'attempted_details':0,'enrich_attachments':enrich,'limit_reached':False}
    seen=set()
    for board in board_ids:
        info={'pages':0,'reached_since':False,'list_complete':False}
        status['boards'][str(board)]=info
        last_urls=None
        for page in range(1,max_pages+1):
            listing=f'{BASE}/bbs/hansung/{int(board)}/artclList.do?page={page}'
            try:
                found,reached=parse_listing(fetch.get(listing),board,since)
                info['pages']=page
                urls={n['url'] for n in found}
                if last_urls is not None and urls == last_urls:
                    info['list_complete']=True
                    break
                last_urls=urls
                for notice in found:
                    url=notice['url']
                    if url in seen or (not refresh and documents.get(url,{}).get('last_checked_at')):
                        continue
                    if status['attempted_details'] >= max_notices:
                        status['limit_reached']=True
                        break
                    seen.add(url)
                    status['attempted_details']+=1
                    try:
                        html=fetch.get(url)
                        soup=BeautifulSoup(html,'html.parser')
                        body=soup.select_one('.view.viewCont .txt')
                        if body is None:
                            raise ValueError('detail_container_missing')
                        _,images,attachments=link_parser.extract_links_from_html(html,url)
                        notice.update(content=body.get_text('\n',strip=True),images=[{'url':u} for u in images],attachments=attachments)
                        notice['content_status']='text' if notice['content'] else 'title_only'
                        notice['attachment_extraction_status']='pending' if images or attachments else 'not_applicable'
                        if enricher:
                            notice=enricher.enrich_notice(notice,detail_html=html)
                            notice['attachment_extraction_status']='attempted'
                        notice['last_checked_at']=datetime.now(timezone.utc).isoformat()
                        documents[url]=notice
                        logging.info('collected %d %s',status['attempted_details'],notice['title'])
                    except Exception as e:
                        status['errors'].append({'url':url,'error':str(e)})
                    atomic_json(output,list(documents.values()))
                if reached:
                    info['reached_since']=True
                    break
                if status['limit_reached']:
                    break
            except Exception as e:
                status['errors'].append({'url':listing,'error':str(e)})
                break
        if status['limit_reached']:
            break
    status['stored_notices']=len(documents)
    status['finished_at']=datetime.now(timezone.utc).isoformat()
    atomic_json(str(output)+'.report.json',status)
    atomic_json(output,list(documents.values()))
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--boards',type=int,nargs='+',default=[2127])
    p.add_argument('--output',default='data/notice_archive.json')
    p.add_argument('--since',default='2023-09-14')
    p.add_argument('--max-pages',type=int,default=30)
    p.add_argument('--max-notices',type=int,default=300)
    p.add_argument('--refresh',action='store_true')
    p.add_argument('--enrich-attachments',action='store_true')
    a=p.parse_args()
    datetime.strptime(a.since,'%Y-%m-%d')
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    report=collect(a.boards,a.output,a.since,a.max_pages,a.max_notices,a.refresh,a.enrich_attachments)
    print(json.dumps(report,ensure_ascii=False))
    if report['errors']:raise SystemExit(1)

if __name__=='__main__':main()
