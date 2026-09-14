"""Public official guidance discovery and incremental collection; never opens a DB.

python -m crawler.official_site --force --max-pages 150
Default: daily checks for calendar pages, 14-day checks for guidance.
Failed fetches preserve previous documents and do not advance last_checked_at.
"""
import argparse
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.hansung.ac.kr"
SEED = BASE + "/hansung/6231/subview.do"
AGENT = "CampusRAG/0.1 (public academic guidance collection)"
LOG = logging.getLogger(__name__)


def canonical(url, base=BASE):
    p = urlsplit(urljoin(base, url))
    if p.scheme not in {"http", "https"} or p.hostname not in {"www.hansung.ac.kr", "hansung.ac.kr"}:
        return None
    if p.port not in (None, 80, 443) or p.username or p.password:
        return None
    if not re.fullmatch(r"/hansung/\d+/subview.do", p.path):
        return None
    return BASE + p.path


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def discover(html):
    """Inventory includes external links but only public main-site subviews are fetched."""
    soup = BeautifulSoup(html, "html.parser")
    inventory = {}
    for root in soup.select('#menuUItop li.li_1'):
        top = root.find('a', recursive=False)
        if not top or clean(top.get_text()) not in {"교육정보", "대학생활", "한성소식"}:
            continue
        for a in root.select('a[href]'):
            path = []
            for parent in reversed(list(a.parents)):
                if parent.name == 'li':
                    heading = parent.find('a', recursive=False)
                    if heading:
                        path.append(clean(heading.get_text()))
            raw = urljoin(BASE, a['href'])
            url = canonical(raw)
            key = url or raw
            item = {"url": key, "title": clean(a.get_text()), "menu_path": path,
                    "kind": "guidance", "interval_days": 1 if "학사일정" in ' '.join(path) else 14,
                    "collection_status": "pending" if url else "external_or_dynamic_review"}
            if key not in inventory or len(path) > len(inventory[key]['menu_path']):
                inventory[key] = item
    return list(inventory.values())


def table_text(table):
    """Expand row/column spans so each row retains shared grading ratios/notes."""
    grid = {}
    max_col = 0
    for r, row in enumerate(table.find_all('tr')):
        col = 0
        for cell in row.find_all(['td', 'th'], recursive=False):
            while (r, col) in grid:
                col += 1
            value = clean(cell.get_text(' ', strip=True))
            # Bounded spans prevent malformed markup from growing the matrix without limit.
            rs = min(100, max(1, int(cell.get('rowspan', 1))))
            cs = min(30, max(1, int(cell.get('colspan', 1))))
            for rr in range(r, r + rs):
                for cc in range(col, col + cs):
                    grid[rr, cc] = value
            col += cs
            max_col = max(max_col, col)
    rows = max((r for r, _ in grid), default=-1) + 1
    return '\n'.join(' | '.join(grid.get((r, c), '') for c in range(max_col)) for r in range(rows))


def extract_page(html, item):
    soup = BeautifulSoup(html, 'html.parser')
    tabs = [{"url": canonical(a['href'], item['url']), "title": clean(a.get_text())}
            for a in soup.select('#menuUItab a[href]') if canonical(a['href'], item['url'])]
    content = soup.select_one('#_contentBuilder')
    if content is None:
        raise ValueError('content_container_missing')
    # Board pages are inventoried separately; listing text is never treated as guidance.
    board_links = sorted({urljoin(item['url'], a['href']) for a in content.select('a[href]')
                          if re.search(r'/bbs/[^/]+/\d+/(?:artclList|\d+/artclView)\.do', a['href'])})
    boards = sorted({re.sub(r'/\d+/artclView\.do.*$', '/artclList.do', u).split('?')[0] for u in board_links})
    attachments = [{"url": urljoin(item['url'], a['href']), "name": clean(a.get_text())}
                   for a in content.select('a[href]')
                   if 'download.do' in a['href'] or re.search(r'\.(pdf|hwp|hwpx)(?:\?|$)', a['href'], re.I)]
    related = [{"url": urljoin(item['url'], a['href']), "title": clean(a.get_text())}
               for a in content.select('a[href]') if a['href'].startswith(('http', '/'))]
    images = [{"url": urljoin(item['url'], i['src']), "alt": i.get('alt', '')}
              for i in content.select('img[src]')]
    contact = soup.select_one('.wrap-contact')
    match = re.search(r'최종 수정일\s*:\s*(\d{4})[.\-/](\d{2})[.\-/](\d{2})', contact.get_text(' ',strip=True) if contact else '')
    updated = '-'.join(match.groups()) if match else ''
    contact_text = clean(contact.get_text(' ', strip=True)) if contact else ''
    for node in content.select('script, style, nav, form, .hidden'):
        node.decompose()
    for table in list(content.select('table')):
        if table.parent:
            rendered = soup.new_tag('pre')
            rendered.string = table_text(table)
            table.replace_with(rendered)
    text = '\n'.join(line.strip() for line in content.get_text('\n', strip=True).splitlines() if line.strip())
    title = item['title']
    active = next((t['title'] for t in tabs if t['url'] == item['url']), None)
    if active:
        title = active
    coverage = "html_text_only"
    if attachments or images:
        coverage = "html_text_with_unextracted_media"
    if any(word in title for word in ("학사일정", "식단", "식당", "아침밥")) or content.select('iframe'):
        coverage = "dynamic_content_requires_review"
    return {"coverage_status": coverage, "id": hashlib.sha256(item['url'].encode()).hexdigest(), "title": title,
            "url": item['url'], "content": text, "content_status": "text" if text else "empty",
            "source": "한성대학교 공식 홈페이지", "category": ' / '.join(item['menu_path']),
            "source_type": "guidance", "menu_path": item['menu_path'], "date": updated,
            "source_updated_at": updated, "contact": contact_text,
            "content_hash": hashlib.sha256((title+'\n'+text).encode()).hexdigest(),
            "attachments": attachments, "images": images, "related_links": related,
            "tabs": tabs, "boards": boards}


class Fetcher:
    def __init__(self, delay=1.0):
        self.delay = max(0.5, delay)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['User-Agent'] = AGENT
        self.last = 0.0
        r = self.session.get(BASE+'/robots.txt', timeout=(5, 25), allow_redirects=False)
        r.raise_for_status()
        if r.status_code != 200:
            raise RuntimeError('robots_unavailable')
        self.robots = RobotFileParser()
        self.robots.parse(r.text.splitlines())

    def get(self, url):
        parsed = urlsplit(url)
        board = (parsed.scheme == "https" and parsed.netloc == "www.hansung.ac.kr"
                 and re.fullmatch(r"/bbs/hansung/\d+/(?:artclList|\d+/artclView)\.do", parsed.path))
        if not (canonical(url) or board) or not self.robots.can_fetch(AGENT, url):
            raise ValueError('URL not permitted')
        time.sleep(max(0, self.delay - (time.monotonic()-self.last)))
        self.last = time.monotonic()
        # Redirects are recorded as failures instead of following to login or other hosts.
        with self.session.get(url, timeout=(5, 25), allow_redirects=False, stream=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f'HTTP {r.status_code}')
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > 5*1024*1024:
                    raise ValueError('HTML exceeds 5MB')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8', errors='replace')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    # Damaged HWP text can contain isolated UTF-16 surrogates. Keep valid UTF-8 JSON.
    payload = re.sub(r"[\ud800-\udfff]", "\ufffd", payload)
    tmp.write_text(payload+'\n', encoding='utf-8')
    tmp.replace(path)


def collect(output, inventory_path, max_pages=150, force=False, delay=1.0):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    old = json.loads(Path(output).read_text()) if Path(output).exists() else []
    documents = {d['url']: d for d in old}
    fetch = Fetcher(delay)
    html = fetch.get(SEED)
    targets = discover(html)
    policy_path = Path(__file__).with_name('source_policies.json')
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    def interval(item):
        value = policy.get('interval_overrides', {}).get(item['url'],
            1 if '학사일정' in ' '.join(item['menu_path']) else policy.get('default_guidance_interval_days', 14))
        if not isinstance(value, int) or value < 1:
            raise ValueError('collection interval must be a positive day count')
        return value
    for target in targets:
        target['interval_days'] = interval(target)
    targets_by_url = {t['url']: t for t in targets}
    queue = [t for t in targets if canonical(t['url'])]
    # Explicitly include grading, even if navigation changes.
    if SEED not in targets_by_url:
        t = {'url': SEED, 'title': '시험 및 성적평가', 'menu_path': ['교육정보','성적/졸업','시험 및 성적평가'], 'interval_days':14, 'kind':'guidance'}
        queue.insert(0,t);targets_by_url[SEED]=t
    visited, attempted, errors = set(), 0, []
    for item in queue:
        url = item['url']
        if url in visited:
            continue
        visited.add(url)
        if url in policy.get('manual_review_urls', {}):
            item['collection_status'] = 'requires_manual_review'
            item['reason'] = policy['manual_review_urls'][url]
            continue
        prev = documents.get(url)
        checked = datetime.fromisoformat(prev['last_checked_at']) if prev and prev.get('last_checked_at') else None
        due = not checked or now-checked >= timedelta(days=item['interval_days'])
        if not force and not due:
            item['collection_status'] = 'not_due'
            # Keep previously discovered tabs in scope even when parent is not fetched.
            tabs = prev.get('tabs', [])
        elif attempted >= max_pages:
            item['collection_status'] = 'deferred_limit'
            tabs = []
        else:
            attempted += 1
            try:
                page = html if url == SEED else fetch.get(url)
                record = extract_page(page,item)
                tabs = record['tabs']
                item['boards'] = record['boards']
                if record['boards']:
                    item['collection_status'] = 'board_requires_notice_crawler'
                elif not record['content']:
                    raise ValueError('empty_content_requires_review')
                else:
                    changed = not prev or record['content_hash'] != prev.get('content_hash')
                    record['last_checked_at'] = stamp
                    record['last_changed_at'] = stamp if changed else prev.get('last_changed_at', stamp)
                    record['interval_days'] = item['interval_days']
                    documents[url] = record
                    item['collection_status'] = 'changed' if changed else 'unchanged'
                LOG.info('%s %s',item['collection_status'],item['title'])
            except Exception as e:
                item['collection_status'] = 'failed'
                item['error'] = str(e)
                errors.append({'url':url,'error':str(e)})
                tabs = prev.get('tabs',[]) if prev else []
                LOG.warning('failed %s: %s',url,e)
            # Checkpoint each fetch, preserving existing successful documents on interruption.
            atomic_json(output, list(documents.values()))
        for tab in tabs:
            if tab['url'] not in targets_by_url:
                child = {"url":tab['url'],"title":tab['title'],"menu_path":item['menu_path']+[tab['title']],
                         "kind":"guidance","interval_days":item['interval_days'],"collection_status":"pending"}
                child['interval_days'] = interval(child)
                targets_by_url[tab['url']] = child
                queue.append(child)
    report = {'checked_at':stamp, 'scope':['교육정보','대학생활','한성소식'], 'documents':len(documents),
              'attempted':attempted, 'errors':errors, 'targets':list(targets_by_url.values())}
    atomic_json(inventory_path,report)
    atomic_json(output,list(documents.values()))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='data/official_pages.json')
    p.add_argument('--inventory',default='data/official_site_inventory.json')
    p.add_argument('--max-pages',type=int,default=150)
    p.add_argument('--force',action='store_true')
    p.add_argument('--delay',type=float,default=1.0)
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    report=collect(a.output,a.inventory,a.max_pages,a.force,a.delay)
    print(json.dumps({k:v for k,v in report.items() if k!='targets'},ensure_ascii=False))
    if report['errors']:
        raise SystemExit(1)

if __name__=='__main__':
    main()
