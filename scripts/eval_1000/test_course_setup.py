import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

from eval_builder_common import (
    DOC_BY_ID, DOC_BY_URL, verify_quote,
    make_single_question, make_multi_question, make_abstain_question,
    normalize_text, snapshot
)

print("Building 200 questions for 수강신청...")

# Find relevant documents
doc_6225 = next(d for d in snapshot if '/6225/subview.do' in d.get('url', ''))
doc_6226 = next(d for d in snapshot if '/6226/subview.do' in d.get('url', ''))
doc_6227 = next(d for d in snapshot if '/6227/subview.do' in d.get('url', ''))
doc_6228 = next(d for d in snapshot if '/6228/subview.do' in d.get('url', ''))
doc_6229 = next(d for d in snapshot if '/6229/subview.do' in d.get('url', ''))
doc_6222 = next(d for d in snapshot if '/6222/subview.do' in d.get('url', ''))
doc_6223 = next(d for d in snapshot if '/6223/subview.do' in d.get('url', ''))
doc_6224 = next(d for d in snapshot if '/6224/subview.do' in d.get('url', ''))
doc_6230 = next(d for d in snapshot if '/6230/subview.do' in d.get('url', ''))
doc_6104 = next(d for d in snapshot if '/6104/subview.do' in d.get('url', ''))
doc_6105 = next(d for d in snapshot if '/6105/subview.do' in d.get('url', ''))

# Notice docs
notice_canc = next(d for d in snapshot if '폐강' in d.get('title', '') and '2026' in d.get('title', ''))
notice_drop = next(d for d in snapshot if '수강포기' in d.get('title', '') and '2026' in d.get('title', ''))
notice_basket = next(d for d in snapshot if '장바구니' in d.get('title', '') and '2026' in d.get('title', ''))
notice_info = next(d for d in snapshot if '수강신청 정보' in d.get('title', '') and '2026' in d.get('title', ''))

# Course FAQs
course_faqs = [d for d in snapshot if d.get('source_type') == 'faq' and any(k in d.get('category', '') for k in ['수강', '계절', '수업'])]

print(f"Found {len(course_faqs)} course FAQs, key guidances, and notices.")
