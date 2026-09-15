"""Collect the public academic FAQ accordion, whose answers are in the list HTML.

This is an explicit official FAQ board, not student Q&A or complaints. No publication
or effective date is invented when the page does not supply one.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
from crawler.official_site import BASE, Fetcher, atomic_json, clean, table_text


def parse_faq(html, page_url):
    soup=BeautifulSoup(html,'html.parser')
    faq=soup.select_one('.faq-list')
    if faq is None:
        raise ValueError('FAQ container missing')
    documents=[]
    for row in faq.select(':scope > ul > li'):
        question=row.select_one('.question')
        answer=row.select_one('.answer')
        if not question or not answer:
            continue
        title=clean(question.get_text(' ',strip=True))
        category=question.select_one('.cate-name')
        for table in list(answer.select('table')):
            pre=soup.new_tag('pre');pre.string=table_text(table);table.replace_with(pre)
        text='\n'.join(clean(line) for line in answer.get_text().splitlines() if clean(line))
        if not title or not text:
            raise ValueError('FAQ question or answer empty')
        stable_id=hashlib.sha256(('hansung-faq-2148:'+title).encode()).hexdigest()
        documents.append({'id':stable_id,'url':page_url,'title':title,'content':text,
            'date':'','source':'한성대학교 공식 학사 FAQ','source_type':'faq',
            'category':clean(category.get_text()) if category else '학사 FAQ',
            'content_status':'text','last_checked_at':datetime.now(timezone.utc).isoformat(),
            'content_hash':hashlib.sha256((title+'\n'+text).encode()).hexdigest()})
    total=soup.select_one('._totPage')
    return documents,int(total.get_text()) if total else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='data/official_faq.json')
    p.add_argument('--max-pages',type=int,default=30)
    p.add_argument('--force',action='store_true')
    args=p.parse_args()
    if Path(args.output).exists() and not args.force:
        previous=json.loads(Path(args.output).read_text())
        checked=[datetime.fromisoformat(d['last_checked_at']) for d in previous if d.get('last_checked_at')]
        if previous and len(checked)==len(previous) and datetime.now(timezone.utc)-min(checked)<timedelta(days=14):
            print('FAQ refresh not due (14-day interval); existing successful snapshot retained')
            return
    fetch=Fetcher();documents={};total=1;report={'errors':[],'pages':0}
    for page in range(1,args.max_pages+1):
        url=f'{BASE}/bbs/hansung/2148/artclList.do?page={page}'
        try:
            found,total=parse_faq(fetch.get(url),url)
            if not found:
                raise ValueError('Expected FAQ questions missing')
            documents.update({d['id']:d for d in found})
            report['pages']=page
        except Exception as e:
            report['errors'].append({'url':url,'error':str(e)})
            break
        if page>=total:
            break
    report.update(documents=len(documents),expected_pages=total,complete=not report['errors'] and report['pages']>=total)
    atomic_json(args.output+'.report.json',report)
    # Publish a full FAQ snapshot only after every advertised page has been checked.
    if report['complete']:
        atomic_json(args.output,list(documents.values()))
    else:
        atomic_json(args.output+'.partial.json',list(documents.values()))
        raise SystemExit(1)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
