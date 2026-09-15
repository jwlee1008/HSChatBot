"""Run eight real Gemini RAG probes on a disposable copy of the stopped demo DB.

Stores answers and retrieved evidence for manual review, not keyword-based PASS rates.
API use is intentional; retries are disabled. A 503 is recorded and the next probe
continues; other API errors stop the run. --resume skips all previously attempted IDs.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    source = ROOT / 'data/verify_demo_chroma_db'
    output = ROOT / 'data/gemini_smoke_results.json'
    if not source.is_dir():
        raise SystemExit('Demo DB missing; prepare it before running this probe')
    questions = [
        ('dev-md-05', '국가전문자격시험 합격생 장학금 대상에 공인회계사랑 세무사도 포함돼?'),
        ('test-md-07', '2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간이 언제야?'),
        ('test-md-09', '한성대 기숙사 우촌학사 야간 통금 시간이 몇 시야?'),
        ('dev-md-06', '제26회 TOPCIT 정기평가 한성대 단체접수 마감일이 언제까지로 연장됐어?'),
        ('test-md-01', '편입생 전적대학 학점 재인정 신청 대상자가 누구야?'),
        ('scholarship-dates', '2026년 2학기 국가장학금 2차 신청 마감과 가구원 동의 마감은 각각 언제야?'),
        ('short-query', 'TOPCIT 평가'),
        ('irrelevant', '파이썬으로 이진 탐색 트리 구현하는 코드 짜줘'),
    ]
    with tempfile.TemporaryDirectory(prefix='campusrag-gemini-') as temporary:
        target = Path(temporary) / 'db'
        shutil.copytree(source, target)
        os.environ['CHROMA_PERSIST_DIR'] = str(target)
        os.environ['CHROMA_COLLECTION_NAME'] = 'campus_notices'
        import config
        from core.rag import CampusRAG
        if config.LLM_PROVIDER.lower() != 'gemini' or not config.GEMINI_API_KEY:
            raise SystemExit('Set Gemini provider and key in .env first')
        report = {'executed_at': datetime.now(timezone.utc).isoformat(),
                  'provider': config.LLM_PROVIDER, 'model': config.GEMINI_MODEL,
                  'source_db': str(source.relative_to(ROOT)),
                  'source_sqlite_sha256': hashlib.sha256((source/'chroma.sqlite3').read_bytes()).hexdigest(),
                  'scope': 'Real RAG invocation on copied demo DB; manual answer review required', 'results': []}
        if args.resume and output.exists():
            previous = json.loads(output.read_text())
            for field in ('provider', 'model', 'source_sqlite_sha256'):
                if previous[field] != report[field]:
                    raise SystemExit('Resume refused: model or source DB changed')
            report = previous
        attempted = {entry['id'] for entry in report['results']}
        rag = CampusRAG(load_llm=True)
        rag.llm.max_retries = 0
        rag.llm.timeout = 45
        report['chunks'] = rag.vectorstore._collection.count()
        for question_id, question in questions:
            if question_id in attempted:
                continue
            started = time.monotonic()
            try:
                evidence = rag.retrieve(question)
                result = rag.query(question)
                entry = {'id': question_id, 'question': question, **result,
                         'evidence': [{'text': d.page_content, 'metadata': d.metadata} for d in evidence],
                         'status': 'executed', 'seconds': round(time.monotonic()-started, 3)}
            except Exception as exc:
                entry = {'id': question_id, 'question': question, 'status': 'error',
                         'error': str(exc).replace(config.GEMINI_API_KEY, '[REDACTED]')[:2000]}
            report['results'].append(entry)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(question_id, entry['status'], entry.get('seconds'), flush=True)
            if entry['status'] == 'error' and '503' not in entry['error']:
                raise SystemExit('API probe stopped; see sanitized result file')


if __name__ == '__main__':
    main()
