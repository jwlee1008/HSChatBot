import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

from eval_builder_common import (
    DOC_BY_ID, DOC_BY_URL, verify_quote,
    make_single_question, make_multi_question, make_abstain_question,
    normalize_text, snapshot
)

doc_6225 = next(d for d in snapshot if '/6225/subview.do' in d.get('url', ''))
doc_6226 = next(d for d in snapshot if '/6226/subview.do' in d.get('url', ''))
doc_6227 = next(d for d in snapshot if '/6227/subview.do' in d.get('url', ''))
doc_6228 = next(d for d in snapshot if '/6228/subview.do' in d.get('url', ''))
doc_6229 = next(d for d in snapshot if '/6229/subview.do' in d.get('url', ''))
doc_6224 = next(d for d in snapshot if '/6224/subview.do' in d.get('url', ''))
doc_6223 = next(d for d in snapshot if '/6223/subview.do' in d.get('url', ''))
doc_6230 = next(d for d in snapshot if '/6230/subview.do' in d.get('url', ''))
doc_6104 = next(d for d in snapshot if '/6104/subview.do' in d.get('url', ''))

n_canc_26_2 = next(d for d in snapshot if '폐강' in d.get('title', '') and '2026' in d.get('title', '') and '2학기' in d.get('title', ''))
n_drop_26_2 = next(d for d in snapshot if '수강포기' in d.get('title', '') and '2026' in d.get('title', '') and '2학기' in d.get('title', ''))
n_basket_26_2 = next(d for d in snapshot if '장바구니' in d.get('title', '') and '2026' in d.get('title', '') and '2학기' in d.get('title', ''))
n_elearn_26_2 = next(d for d in snapshot if '군 이러닝' in d.get('title', '') and '26년도' in d.get('title', ''))
n_kmooc_26_2 = next(d for d in snapshot if 'K-MOOC' in d.get('title', '') and '2026' in d.get('title', '') and '2학기' in d.get('title', ''))
n_summer_exch = next(d for d in snapshot if '여름계절학기 학점교류' in d.get('title', '') and '2026' in d.get('title', ''))
n_winter_exch = next(d for d in snapshot if '겨울계절학기 학점교류' in d.get('title', '') and '2026' in d.get('title', ''))

faq_eng_exemp = next(d for d in snapshot if '영어커뮤니케이션 이수 면제' in d.get('title', ''))
faq_attend_std = next(d for d in snapshot if '수업별로 출석기준' in d.get('title', ''))
faq_same_subj = next(d for d in snapshot if '동일교과목은 어디서 조회' in d.get('title', ''))
faq_sang_grade = next(d for d in snapshot if '상상더학기’ 성적은 어떻게 처리' in d.get('title', ''))
faq_sang_fee = next(d for d in snapshot if '상상더학기’는 누가 신청 할 수 있으며 수업료' in d.get('title', ''))
faq_sang_time = next(d for d in snapshot if '상상더학기’는 언제 수강신청' in d.get('title', ''))
faq_sang_what = next(d for d in snapshot if '상상더학기’가 무엇인가요' in d.get('title', ''))
faq_leave_s_term = next(d for d in snapshot if '계절학기는 휴학생도 수강이 가능한가요' in d.get('title', ''))
faq_s_term_schol = next(d for d in snapshot if '계절학기 수업에서 취득한 학점이 장학생 선발' in d.get('title', ''))
faq_s_term_grade = next(d for d in snapshot if '계절학기에 취득한 과목의 성적은 어떻게 처리' in d.get('title', ''))
faq_for_fresh = next(d for d in snapshot if '외국인 유학생 신입생의 수강신청 방법' in d.get('title', ''))
faq_for_cred = next(d for d in snapshot if '외국인 유학생 수강신청 가능 학점' in d.get('title', ''))
faq_cyber_att = next(d for d in snapshot if '사이버강좌 출석인정을 받으려면' in d.get('title', ''))

print("All Course reference documents resolved successfully.")
