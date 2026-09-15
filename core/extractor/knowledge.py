"""Enrich guidance using the existing bounded downloader and local extractors.

HTML, media text and individual extraction states stay separate. Each run rebuilds
content from HTML plus current successful media, never appending to previous OCR.
"""
import hashlib
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from core.extractor.downloader import SafeDownloader
from core.extractor.hwp import extract_document_text
from core.extractor.ocr import extract_image_text
from core.extractor.pdf import extract_pdf_text


def detect_format(path, url):
    with Path(path).open('rb') as f:
        magic = f.read(16)
    if magic.startswith(b'%PDF-'):
        return 'pdf'
    if magic.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        return 'hwp'
    ext = Path(unquote(urlsplit(url).path)).suffix.lower().lstrip('.')
    if magic.startswith(b'PK'):
        # Download handlers often have a .do suffix. Inspect archive structure, not its URL.
        try:
            with zipfile.ZipFile(path) as archive:
                names=set(archive.namelist())
                if len(names) <= 10000 and 'Contents/section0.xml' in names and 'Contents/content.hpf' in names:
                    return 'hwpx'
        except zipfile.BadZipFile:
            pass
        if ext == 'hwpx':
            return 'hwpx'
    if magic.startswith((b'\xff\xd8\xff', b'\x89PNG', b'GIF8', b'BM', b'II*\x00', b'MM\x00*')) or (magic.startswith(b'RIFF') and magic[8:12] == b'WEBP'):
        return 'image'
    return 'unsupported'


def aggregate_status(results):
    if not results:
        return 'not_applicable'
    if all(r['status'] in ('success', 'empty') for r in results):
        return 'complete'
    if any(r.get('text') for r in results):
        return 'partial'
    return 'failed_or_unsupported'


class KnowledgeEnricher:
    def __init__(self, downloader=None, max_pdf_pages=10):
        self.downloader = downloader or SafeDownloader()
        self.max_pdf_pages = max_pdf_pages
        self.memo = {}

    def extract(self, asset):
        url = asset['url']
        if url in self.memo:
            return {**self.memo[url], 'name':asset.get('name',asset.get('alt',''))}
        result = {'url':url,'name':asset.get('name',asset.get('alt','')),'text':'','status':'failed'}
        try:
            # URL basename instead of display text: '한글파일 다운로드' has no extension.
            hint = Path(unquote(urlsplit(url).path)).name
            path, status, meta = self.downloader.download_file(url, filename_hint=hint, validate_cache=True)
            result['download_status'] = status
            if not path or status not in ('downloaded','cached'):
                result.update(status=status,error=meta.get('error','download unavailable'))
            else:
                kind = detect_format(path,url)
                result['format'] = kind
                result['sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if kind == 'pdf':
                    text, state, error, detail = extract_pdf_text(path,max_pages=self.max_pdf_pages)
                    result.update(text=text,status=state,error=error,details=detail)
                elif kind in ('hwp','hwpx'):
                    text,state,error,detail = extract_document_text(path,filename_hint='document.'+kind)
                    result.update(text=text,status=state,error=error,details=detail)
                elif kind == 'image':
                    text,state,error = extract_image_text(path)
                    result.update(text=text,status=state,error=error)
                else:
                    result.update(status='unsupported_format',error='Unknown file bytes; not treated as extracted text')
        except Exception as e:
            result.update(status='failed',error=str(e))
        # Per-run memo avoids duplicate campus icons/files; failures are retried on the next run.
        result['text'] = re.sub(r'[\ud800-\udfff]', '\ufffd', result['text'])
        self.memo[url] = dict(result)
        return result

    def enrich(self, record):
        result = dict(record)
        # Legacy first pass uses raw content. An already enriched record MUST retain html_content.
        base = record.get('html_content',record.get('content',''))
        result['html_content'] = base
        image_results = [self.extract(a) for a in record.get('images',[])]
        attachment_results = [self.extract(a) for a in record.get('attachments',[])]
        assets = image_results + attachment_results
        sections, seen = [base], set()
        for asset in assets:
            text = asset.get('text','').strip()
            if text and text not in seen:
                seen.add(text)
                sections.append(f"[자료: {asset['name'] or asset['url']}]\n{text}")
        result['content'] = '\n\n'.join(s for s in sections if s.strip())
        result['images'] = image_results
        result['attachments'] = attachment_results
        result['has_ocr'] = any(a.get('text') and a.get('format')=='image' for a in assets)
        result['has_attachment'] = any(a.get('text') for a in attachment_results)
        result['media_extraction_status'] = aggregate_status(assets)
        if assets:
            result['coverage_status'] = 'html_and_media_'+result['media_extraction_status']
        result['content_status'] = ('mixed' if seen and base else 'attachment' if seen else 'text' if base else 'title_only')
        result['content_hash'] = hashlib.sha256((result['title']+'\n'+result['content']).encode('utf-8')).hexdigest()
        return result
