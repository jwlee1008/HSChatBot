"""Extract guidance PDF/HWP/images to a separate checkpointed JSON; no database writes."""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from crawler.official_site import atomic_json
from core.extractor.knowledge import KnowledgeEnricher


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='data/official_pages.json')
    p.add_argument('--output',default='data/official_pages_enriched.json')
    p.add_argument('--max-pages',type=int,default=10,help='Maximum PDF pages per attachment')
    p.add_argument('--reuse-media',action='store_true',help='Reuse previous media results without a new download; refresh HTML only')
    a=p.parse_args()
    if Path(a.input).resolve()==Path(a.output).resolve():
        raise SystemExit('Raw input must be preserved; use a separate output')
    pages=json.loads(Path(a.input).read_text())
    enricher=KnowledgeEnricher(max_pdf_pages=a.max_pages)
    previous={d['url']:d for d in json.loads(Path(a.output).read_text())} if Path(a.output).exists() else {}
    if a.reuse_media:
        for doc in previous.values():
            for asset in doc.get('images',[])+doc.get('attachments',[]):
                enricher.memo[asset['url']]=asset
    results=[]
    report={'started_at':datetime.now(timezone.utc).isoformat(),'input':a.input,'documents':[],'max_pdf_pages':a.max_pages}
    for page in pages:
        enriched=enricher.enrich(page)
        attempted_at=datetime.now(timezone.utc).isoformat()
        old=previous.get(page['url'])
        if a.reuse_media and old:
            enriched['media_attempted_at']=old.get('media_attempted_at',old.get('media_checked_at',''))
            enriched['media_reused_without_revalidation']=True
        else:
            enriched['media_attempted_at']=attempted_at
        # A transient outage must not silently replace a prior full extraction with less text.
        refresh_status=enriched['media_extraction_status']
        if old and old.get('media_extraction_status')=='complete' and refresh_status not in ('complete','not_applicable'):
            enriched={**old,'media_refresh_status':refresh_status,'media_last_failed_attempt_at':attempted_at}
            enriched['coverage_status']='previous_media_retained_after_refresh_failure'
        results.append(enriched)
        report['documents'].append({'url':page['url'],'title':page['title'],
            'status':refresh_status,'previous_result_retained':enriched.get('coverage_status')=='previous_media_retained_after_refresh_failure',
            'images':len(enriched.get('images',[])),
            'attachments':len(enriched.get('attachments',[])),
            'added_chars':len(enriched['content'])-len(enriched['html_content'])})
        atomic_json(a.output,results)
        atomic_json(a.output+'.report.json',report)
        logging.info('%s %s',enriched['media_extraction_status'],page['title'])
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    atomic_json(a.output+'.report.json',report)
    print('Processed',len(results),'documents')

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    main()
