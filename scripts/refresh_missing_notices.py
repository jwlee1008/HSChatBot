"""Revisit title-only notices and run existing OCR/attachment extraction into a separate JSON."""
import argparse
import json
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bs4 import BeautifulSoup
from crawler.official_site import Fetcher, atomic_json
from core.extractor.pipeline import NoticeEnricher


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='data/crawled_notices.json')
    p.add_argument('--output',default='data/missing_notices_refreshed.json')
    a=p.parse_args()
    if Path(a.input).resolve()==Path(a.output).resolve():
        raise SystemExit('Separate output path required')
    docs=json.loads(Path(a.input).read_text())
    report=[]
    fetch=Fetcher()
    enricher=NoticeEnricher()
    for i,doc in enumerate(docs):
        if doc.get('content') and doc['content']!=doc['title'] and doc.get('content_status')!='title_only':
            continue
        try:
            html=fetch.get(doc['url'])
            soup=BeautifulSoup(html,'html.parser')
            body=soup.select_one('.view.viewCont .txt')
            if body is None:raise ValueError('detail_container_missing')
            fresh={**doc,'content':body.get_text('\n',strip=True)}
            result=enricher.enrich_notice(fresh,detail_html=html)
            docs[i]=result
            report.append({'url':doc['url'],'title':doc['title'],'status':result['content_status'],
                'html_text_chars':len(fresh['content']),'images':len(result.get('images',[])),
                'attachments':len(result.get('attachments',[])),
                'extraction_summary':result.get('extraction_summary')})
            logging.info('%s %s',result['content_status'],doc['title'])
        except Exception as e:
            report.append({'url':doc['url'],'status':'failed','error':str(e)})
            logging.warning('%s %s',doc['url'],e)
        atomic_json(a.output,docs)
        atomic_json(a.output+'.report.json',report)
    print(json.dumps({'attempted':len(report),'statuses':{s:sum(r['status']==s for r in report) for s in set(r['status'] for r in report)}},ensure_ascii=False))

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    main()
