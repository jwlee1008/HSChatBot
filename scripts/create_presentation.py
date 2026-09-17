"""
CampusRAG 5~10분 발표용 PowerPoint(PPTX) 자동 생성 스크립트
- 16:9 와이드스크린 레이아웃
- 오픈소스 AI·SW 프로젝트 관점 강조
- 기술 50% : 서비스 50% 하이브리드 개선방향 반영
- 세련되고 깔끔한 카드형 디자인
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_deck(output_path="CampusRAG_발표자료.pptx"):
    prs = Presentation()
    # 16:9 Widescreen 설정 (13.333 x 7.5 inches)
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]

    # 컬러 팔레트
    C_BG_LIGHT = RGBColor(248, 250, 252)       # #F8FAFC
    C_DARK = RGBColor(15, 23, 42)              # #0F172A (주 텍스트 / 네이비)
    C_PRIMARY = RGBColor(30, 64, 175)          # #1E40AF (메인 블루)
    C_SECONDARY = RGBColor(59, 130, 246)       # #3B82F6 (서브 블루)
    C_OPENSOURCE = RGBColor(16, 185, 129)      # #10B981 (오픈소스 에메랄드 그린)
    C_CARD_BG = RGBColor(255, 255, 255)        # #FFFFFF (카드 배경)
    C_CARD_BORDER = RGBColor(226, 232, 240)    # #E2E8F0 (카드 테두리)
    C_MUTED = RGBColor(100, 116, 139)          # #64748B (보조 텍스트)
    C_ACCENT_BG = RGBColor(238, 242, 255)      # #EEF2FF (연한 블루 박스)

    def set_slide_background(slide, color=C_BG_LIGHT):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = color
        bg.line.fill.background()
        return bg

    def add_header(slide, title, category="CampusRAG | 오픈소스 AI·SW 프로젝트", badge="OPEN SOURCE"):
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.45), Inches(8.0), Inches(0.4))
        tf = cat_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = category.upper()
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = C_SECONDARY

        if badge:
            badge_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(11.0), Inches(0.4), Inches(1.53), Inches(0.35))
            badge_box.fill.solid()
            badge_box.fill.fore_color.rgb = C_OPENSOURCE
            badge_box.line.fill.background()
            btf = badge_box.text_frame
            bp = btf.paragraphs[0]
            bp.text = badge
            bp.font.size = Pt(10)
            bp.font.bold = True
            bp.font.color.rgb = RGBColor(255, 255, 255)
            bp.alignment = PP_ALIGN.CENTER

        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(11.5), Inches(0.8))
        tf2 = title_box.text_frame
        tf2.word_wrap = True
        p2 = tf2.paragraphs[0]
        p2.text = title
        p2.font.size = Pt(24)
        p2.font.bold = True
        p2.font.color.rgb = C_DARK

    def add_card(slide, left, top, width, height, title, items, subtitle=None, border_color=C_CARD_BORDER, bg_color=C_CARD_BG, title_color=C_PRIMARY):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1.2)

        tb = slide.shapes.add_textbox(Inches(left + 0.25), Inches(top + 0.2), Inches(width - 0.5), Inches(height - 0.4))
        tf = tb.text_frame
        tf.word_wrap = True

        p_title = tf.paragraphs[0]
        p_title.text = title
        p_title.font.size = Pt(16)
        p_title.font.bold = True
        p_title.font.color.rgb = title_color

        if subtitle:
            p_sub = tf.add_paragraph()
            p_sub.text = subtitle
            p_sub.font.size = Pt(11)
            p_sub.font.color.rgb = C_MUTED
            p_sub.space_after = Pt(8)
        else:
            p_title.space_after = Pt(8)

        for item in items:
            p = tf.add_paragraph()
            p.text = item
            p.font.size = Pt(12)
            p.font.color.rgb = C_DARK
            p.space_after = Pt(5)
            p.level = 0

    # =========================================================================
    # SLIDE 1: 표지
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    set_slide_background(s1, C_DARK)

    b_box = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), Inches(1.8), Inches(2.8), Inches(0.45))
    b_box.fill.solid()
    b_box.fill.fore_color.rgb = C_OPENSOURCE
    b_box.line.fill.background()
    bp = b_box.text_frame.paragraphs[0]
    bp.text = "OPEN SOURCE AI & SW PROJECT"
    bp.font.size = Pt(11)
    bp.font.bold = True
    bp.font.color.rgb = RGBColor(255, 255, 255)
    bp.alignment = PP_ALIGN.CENTER

    tb1 = s1.shapes.add_textbox(Inches(1.0), Inches(2.5), Inches(11.3), Inches(3.0))
    tf1 = tb1.text_frame
    tf1.word_wrap = True

    p = tf1.paragraphs[0]
    p.text = "CampusRAG"
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = RGBColor(255, 255, 255)
    p.space_after = Pt(10)

    p_sub = tf1.add_paragraph()
    p_sub.text = "한성대학교 학내 공지사항 통합 RAG 챗봇 시스템"
    p_sub.font.size = Pt(22)
    p_sub.font.bold = True
    p_sub.font.color.rgb = C_SECONDARY
    p_sub.space_after = Pt(15)

    p_desc = tf1.add_paragraph()
    p_desc.text = "오픈소스 파이프라인(Tesseract·ChromaDB·HuggingFace·FastAPI) 기반\n분산된 학사 공지 통합 검색 및 신뢰형 AI 요약 서비스"
    p_desc.font.size = Pt(14)
    p_desc.font.color.rgb = RGBColor(203, 213, 225)

    tb_meta = s1.shapes.add_textbox(Inches(1.0), Inches(5.8), Inches(10.0), Inches(0.8))
    tf_m = tb_meta.text_frame
    p_m = tf_m.paragraphs[0]
    p_m.text = "발표 내용: 프로젝트 구조 | 오픈소스 구현 현황 | 향후 개선방향 (기술 50% : 서비스 50%)"
    p_m.font.size = Pt(12)
    p_m.font.color.rgb = C_MUTED

    # =========================================================================
    # SLIDE 2: 문제 정의 및 프로젝트 목적
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    set_slide_background(s2)
    add_header(s2, "문제 정의: 왜 학내 공지에 RAG와 오픈소스가 필요한가?")

    add_card(s2, 0.8, 1.8, 3.6, 5.0, "1. 극단적으로 분산된 공지", [
        "• 본부 홈페이지, 단과대, 학과, 장학, 취업 등 수십 개 게시판 파편화",
        "• 학생들은 필요한 일정을 찾기 위해 여러 사이트를 직접 순회 검색",
        "• 매 학기 수강신청, 국가장학금 등 핵심 학사 일정 놓침 빈번"
    ], subtitle="공지 파편화로 인한 탐색 피로도")

    add_card(s2, 4.8, 1.8, 3.6, 5.0, "2. 첨부파일의 검색 사각지대", [
        "• 공지 본문은 비어 있고 '붙임 참조'인 경우가 40% 이상",
        "• 세부 자격/일정은 HWP, PDF, 포스터 이미지 안에만 은닉",
        "• 기존 대학 포털의 단순 제목 키워드 검색으로는 원천 검색 불가"
    ], subtitle="비정형 파일 속 핵심 데이터 고립")

    add_card(s2, 8.8, 1.8, 3.7, 5.0, "3. CampusRAG 해결책 & 오픈소스", [
        "• 자연어 질문 1회 → 2~3줄 핵심 요약 + 공식 원문 카드 제공",
        "• HWP/PDF/이미지 속 본문까지 자체 오픈소스 엔진으로 파싱",
        "• 오픈소스 기반 구축으로 상용 종속 탈피 & 프라이버시 보호"
    ], subtitle="검증 가능한 오픈소스 RAG 서비스", border_color=C_SECONDARY, bg_color=C_ACCENT_BG)

    # =========================================================================
    # SLIDE 3: 오픈소스 기반 시스템 아키텍처 (구조도 이미지 삽입)
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    set_slide_background(s3, C_DARK)
    add_header(s3, "시스템 아키텍처: 100% 오픈소스 에코시스템 결합", category="CampusRAG | 시스템 아키텍처")

    # 고해상도 아키텍처 구조도 이미지 삽입 (16:9 비율 유지)
    import os
    img_path = "CampusRAG_기술스택_구조도.jpg"
    if os.path.exists(img_path):
        s3.shapes.add_picture(img_path, Inches(0.8), Inches(1.55), Inches(11.733), Inches(5.5))
    else:
        add_card(s3, 0.8, 1.8, 2.7, 5.0, "1. 데이터 수집 & 파싱", [
            "• Playwright 동적 크롤링",
            "• Tesseract OCR (한/영)",
            "• olefile (HWP 스트림 파싱)",
            "• pypdf / pypdfium2",
            "• SSRF 방어 & 파일 캐싱"
        ], subtitle="Data Engine")

    # =========================================================================
    # SLIDE 4: [오픈소스 핵심 기술 1] 비정형 문서 자체 파싱 파이프라인
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    set_slide_background(s4)
    add_header(s4, "오픈소스 핵심 기술 ①: HWP·PDF·이미지 자체 추출 파이프라인")

    add_card(s4, 0.8, 1.8, 5.6, 5.0, "순수 오픈소스 기반 비정형 문서 파서", [
        "• HWP (한글 5.0): 상용 소프트웨어 없이 olefile 기반 zlib 압축 해제 및 레코드 태그(HWPTAG_PARA_TEXT) 파싱",
        "• HWPX (개방형 한글): 표준 KS X 6101 XML 파싱으로 서식 무손실 텍스트 추출",
        "• PDF 이원화 파이프라인:",
        "  - 텍스트 PDF: pypdf 고속 텍스트 레이어 추출",
        "  - 스캔형 PDF: pypdfium2 고해상도 렌더링 후 Tesseract OCR 폴백",
        "• 본문 이미지/포스터: Tesseract OCR (kor+eng) 로컬 실행"
    ], subtitle="외부 유료 API 의존 없는 완전 로컬 추출")

    add_card(s4, 6.8, 1.8, 5.7, 5.0, "엔지니어링 안정성 및 보안 설계", [
        "• SSRF(서버 측 요청 위조) 원천 방어:",
        "  - 사설 IP(127.0.0.1, 10.0.0.0/8, 192.168.0.0/16 등) 접근 및 리다이렉트 차단",
        "• 암호화/배포용 문서 예외 격리:",
        "  - 암호화 HWP는 unsupported_encrypted로 기록하여 파이프라인 중단 방지",
        "• 중복 방지 캐시 & 리소스 제어:",
        "  - SHA-256 해시 기반 다운로드 캐시, 20MB 상한, 타임아웃 적용"
    ], subtitle="프로덕션 레벨의 데이터 파이프라인 안정성", border_color=C_PRIMARY)

    # =========================================================================
    # SLIDE 5: [오픈소스 핵심 기술 2] 학사 도메인 특화 휴리스틱 리랭킹
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    set_slide_background(s5)
    add_header(s5, "오픈소스 핵심 기술 ②: 학사 도메인 특화 검색 리랭커")

    add_card(s5, 0.8, 1.8, 3.7, 5.0, "1. 연도·학기·차수 정합성", [
        "• 문제: '국가장학금' 질의 시 매년 동일 제목 공지로 인해 과거 공지 혼선",
        "• 해결: 정규식 기반 엔티티 추출",
        "• '2026년 1학기' 질문 시 타 연도 공지 강력 감점(-0.40)",
        "• 당해 학기 최근 3개월 공지 가산점(+0.22) 부여"
    ], subtitle="시의성 오류 원천 차단")

    add_card(s5, 4.8, 1.8, 3.7, 5.0, "2. 상시안내 vs 공지 이원화", [
        "• 문제: 학사일정, FAQ, 서식 등은 날짜가 오래되어도 여전히 유효함",
        "• 해결: source_type (guidance, faq, form) 메타데이터 분기",
        "• 상시 문서는 연도 불일치 및 경과 일수 감점을 전면 면제"
    ], subtitle="지식 유형별 검색 정책 분리")

    add_card(s5, 8.8, 1.8, 3.7, 5.0, "3. 약어 구제 & 오프토픽 가드", [
        "• 전문 약어 구제: TOPCIT, CPA, TOEIC, IPP 등 단축 쿼리 어휘 보너스(+0.08)",
        "• 오프토픽 차단: 순수 코딩 과제 요청('파이썬 코드 짜줘')은 조기 0건 처리",
        "• 학내 기술 교육('파이썬 특강 신청')은 정상 통과하는 정밀 의도 감지"
    ], subtitle="환각 및 불필요 API 비용 차단")

    # =========================================================================
    # SLIDE 6: 현재 진행 상황 및 성과
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    set_slide_background(s6)
    add_header(s6, "현재 진행 상황: 정합성 검증과 모바일 웹 구축 완료")

    add_card(s6, 0.8, 1.8, 3.6, 5.0, "데이터 수집 및 구축 현황", [
        "• 상시 안내: 144건 (학사일정, 식단)",
        "• 학사 FAQ: 179건 (18페이지 전수 수집)",
        "• 학사 서식: 57건 (오래된 유효 서식 포함)",
        "• 공지 아카이브: 960건 (우선순위 게시판)",
        "• 통합 매니페스트(unified_manifest) 기반 문서 충돌 해결 이력 투명 기록"
    ], subtitle="총 1,340여 건 학사 지식베이스")

    add_card(s6, 4.8, 1.8, 3.6, 5.0, "검증 및 품질 무결성", [
        "• 130개 단위/통합 테스트 100% 통과",
        "• Mock/Fixture 격리 테스트로 Gemini API 429 쿼터(20 RPD) 소진 극복",
        "• 운영 DB 침범 방지(PermissionError) 및 디렉터리 안전성 엄격 보장",
        "• API 에러 시 내부 키/토큰 노출 방지"
    ], subtitle="130 Passed Tests (무결성 확보)", border_color=C_OPENSOURCE)

    add_card(s6, 8.8, 1.8, 3.7, 5.0, "서빙 & 클라이언트 구축", [
        "• FastAPI 비동기 백엔드 연동",
        "• Kubernetes Startup Probe 통과를 위한 0.1초 지연로딩 아키텍처",
        "• React 18 + Vite + Tailwind CSS 기반 모바일 친화형 웹 클라이언트",
        "• Streamlit 개발자 검증 대시보드"
    ], subtitle="Full-Stack Web Serving Ready")

    # =========================================================================
    # SLIDE 7: 향후 개선방향 (1) 기술적 고도화 (Tech 50%)
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    set_slide_background(s7)
    add_header(s7, "앞으로의 개선방향 ①: 기술 고도화 (Tech 50% - Open-Source AI)")

    add_card(s7, 0.8, 1.8, 3.7, 5.0, "1. 하이브리드 검색 (BM25+Dense)", [
        "• 한계: Dense 임베딩만으로는 특정 학과명/교수명/특수 규정 검색 누락 가능",
        "• 개선: 한국어 형태소 분석기(Kiwi) 기반 BM25 키워드 검색 병행",
        "• RRF(Reciprocal Rank Fusion)를 통한 Dense + Sparse 순위 융합",
        "• 오픈소스 BGE-Reranker 교차 평가 도입"
    ], subtitle="검색 재현율 및 정확도 극대화")

    add_card(s7, 4.8, 1.8, 3.7, 5.0, "2. 복합 표(Table) 구조 보존", [
        "• 한계: 납부 일정표, 장학금 지급 기준 등 표 데이터 텍스트 평탄화 시 관계 왜곡",
        "• 개선: HWP/PDF 내부 표를 Markdown/HTML 구조로 보존 청킹",
        "• VLM(Vision-Language Model)을 활용한 저화질 공지 포스터 배치 요약 파이프라인"
    ], subtitle="표 형식 일정·기준의 환각 박멸")

    add_card(s7, 8.8, 1.8, 3.7, 5.0, "3. 스트리밍 & 시맨틱 캐싱", [
        "• 응답 지연 단축: FastAPI SSE(Server-Sent Events) 스트리밍으로 첫 토큰 0.5초 구현",
        "• 시맨틱 캐시(Semantic Cache): '수강신청 언제야' 등 빈발 중복 질문은 임베딩 캐시로 0.1초 즉시 응답 (비용 80% 절감)",
        "• vLLM/Ollama 기반 순수 오픈소스 SLM(Qwen2.5-7B) 고속 서빙 구축"
    ], subtitle="속도 최적화 & 완전 독립 온프레미스")

    # =========================================================================
    # SLIDE 8: 향후 개선방향 (2) 서비스 및 사용자 확장 (Service 50%)
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    set_slide_background(s8)
    add_header(s8, "앞으로의 개선방향 ②: 서비스 확장 (Service 50% - Campus Adoption)")

    add_card(s8, 0.8, 1.8, 3.7, 5.0, "1. 카카오톡 챗봇 채널 연동", [
        "• 접근성 혁신: 별도 웹사이트 방문 없이 학생들이 매일 쓰는 카카오톡에서 즉시 대화",
        "• 카카오 i 오픈빌더 기반 챗봇 스킬 서버로 FastAPI 백엔드 연동",
        "• 모바일 최적화 원문 링크 카드 즉시 렌더링"
    ], subtitle="접속 허들 제로화 (실사용자 확보)")

    add_card(s8, 4.8, 1.8, 3.7, 5.0, "2. 맞춤형 구독 & D-Day 알림", [
        "• 학생 프로필 설정: 소속 단과대, 학과, 학년(졸업예정자 등) 선택",
        "• 마감 임박 알림: '국가장학금 신청 마감 D-3', '컴퓨터공학과 졸업작품 접수 시작'",
        "• 수동 검색을 넘어 능동형 학사 비서로 진화"
    ], subtitle="개인화된 능동형 푸시 서비스")

    add_card(s8, 8.8, 1.8, 3.7, 5.0, "3. 피드백 루프 & 오픈소스 배포", [
        "• 사용자 피드백 플라이휠: 답변별 👍/👎 및 '틀린 정보 제보' 수집",
        "• 오답 데이터 기반 RAG 평가셋 자동 누적",
        "• 타 대학 확산: HWP/공지 수집 및 RAG 파이프라인을 패키지화하여 오픈소스(GitHub) 기여"
    ], subtitle="자가 발전 시스템 & 생태계 확산")

    # =========================================================================
    # SLIDE 9: 결론 및 오픈소스 프로젝트로서의 기대효과
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    set_slide_background(s9, C_DARK)

    tb9 = s9.shapes.add_textbox(Inches(1.0), Inches(0.8), Inches(11.3), Inches(1.2))
    tf9 = tb9.text_frame
    tf9.word_wrap = True
    p9 = tf9.paragraphs[0]
    p9.text = "결론: 오픈소스 AI로 완성하는 지능형 스마트 캠퍼스"
    p9.font.size = Pt(26)
    p9.font.bold = True
    p9.font.color.rgb = RGBColor(255, 255, 255)

    add_card(s9, 1.0, 2.2, 5.3, 4.5, "기술적 의의 (Open-Source Tech)", [
        "• 완전한 오픈소스 소프트웨어 스택으로 데이터 프라이버시 및 비용 절감 실현",
        "• HWP/PDF/이미지 비정형 첨부문서 자체 파싱 파이프라인 정립",
        "• 학사 도메인에 특화된 연도·학기 가중치 리랭킹 엔진 독자 구현",
        "• 130개 자동화 테스트로 증명된 코드 재현성과 신뢰성"
    ], subtitle="탄탄한 공학적 완성도", bg_color=RGBColor(30, 41, 59), border_color=C_SECONDARY, title_color=RGBColor(147, 197, 253))

    add_card(s9, 7.0, 2.2, 5.3, 4.5, "서비스적 가치 (Campus Service)", [
        "• 정보 탐색 시간 90% 절감 및 중요 학사 일정 누락 방지",
        "• 카카오톡 연동과 맞춤형 D-Day 알림으로 실질적인 학생 복지 기여",
        "• 대학 행정팀의 반복적 단순 문의 전화 업무 경감",
        "• 타 대학 및 공공기관으로 확장 가능한 범용 학사 어시스턴트 모델"
    ], subtitle="체감도 높은 실용적 가치", bg_color=RGBColor(30, 41, 59), border_color=C_OPENSOURCE, title_color=RGBColor(110, 231, 183))

    prs.save(output_path)
    print(f"Presentation saved successfully to: {output_path}")

if __name__ == "__main__":
    create_deck()
