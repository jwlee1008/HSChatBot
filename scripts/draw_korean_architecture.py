"""
CampusRAG 한글 기술스택 구조도 이미지 고해상도(1920x1080) 렌더링 스크립트
Pillow와 Apple SD Gothic Neo 폰트를 사용하여 100% 정밀하고 선명한 한국어 텍스트로 아키텍처 다이어그램을 생성합니다.
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

def render_korean_architecture(output_path="CampusRAG_기술스택_구조도.jpg"):
    # 1920 x 1080 Widescreen (16:9)
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=(11, 19, 43)) # #0B132B 딥 네이비 배경
    draw = ImageDraw.Draw(img)

    font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
    
    # 폰트 로드 (크기별)
    f_title = ImageFont.truetype(font_path, 34, index=0)
    f_sub = ImageFont.truetype(font_path, 16, index=0)
    f_badge = ImageFont.truetype(font_path, 14, index=0)
    f_layer_h = ImageFont.truetype(font_path, 21, index=0)
    f_card_h = ImageFont.truetype(font_path, 16, index=0)
    f_body = ImageFont.truetype(font_path, 13, index=0)
    f_body_bold = ImageFont.truetype(font_path, 13, index=0)
    f_flow = ImageFont.truetype(font_path, 15, index=0)

    # 색상 정의
    C_BG = (11, 19, 43)
    C_HEADER_BAR = (19, 31, 63)
    C_CARD_BG = (16, 27, 56)
    C_INNER_BG = (22, 38, 77)
    
    C_WHITE = (255, 255, 255)
    C_MUTED = (160, 175, 200)
    C_CYAN = (0, 240, 255)       # 포인트 시안
    C_BLUE = (59, 130, 246)      # 블루
    C_GREEN = (16, 185, 129)     # 오픈소스 그린
    C_PURPLE = (139, 92, 246)    # 임베딩 퍼플
    C_AMBER = (245, 158, 11)     # RAG 코어 앰버

    # 1. 상단 헤더 영역
    draw_rounded_rect(draw, (40, 30, W - 40, 120), radius=12, fill=C_HEADER_BAR, outline=(30, 50, 95), width=2)
    
    # 오픈소스 배지
    draw_rounded_rect(draw, (60, 48, 300, 80), radius=6, fill=(16, 185, 129), outline=None)
    draw.text((75, 52), "OPEN SOURCE AI & SW PROJECT", font=f_badge, fill=C_WHITE)

    # 메인 타이틀
    draw.text((320, 43), "CampusRAG: 오픈소스 학내 공지 AI 챗봇 시스템 아키텍처", font=f_title, fill=C_WHITE)
    draw.text((323, 86), "분산된 학사 공지 수집부터 비정형 문서 자체 파싱, 도메인 특화 검색, 하이브리드 LLM 서빙까지", font=f_sub, fill=C_CYAN)

    # 2. 4대 핵심 계층 카드 (2x2 Grid)
    # Layer 1: Top-Left (40, 140, 930, 550)
    # Layer 2: Bottom-Left (40, 570, 930, 950)
    # Layer 3: Bottom-Right (960, 570, 1880, 950)
    # Layer 4: Top-Right (960, 140, 1880, 550)

    # ── 계층 1: 데이터 수집 및 비정형 문서 파싱 ──
    draw_rounded_rect(draw, (40, 140, 930, 550), radius=14, fill=C_CARD_BG, outline=C_CYAN, width=2)
    draw_rounded_rect(draw, (40, 140, 930, 195), radius=14, fill=(15, 45, 85))
    draw.text((65, 155), "1. 데이터 수집 및 비정형 문서 추출 계층 (Data Engine)", font=f_layer_h, fill=C_WHITE)
    draw_rounded_rect(draw, (770, 153, 910, 182), radius=5, fill=C_GREEN)
    draw.text((782, 157), "100% OPEN SOURCE", font=f_badge, fill=C_WHITE)

    # 계층 1 내부 카드들 (3개 서브 블록)
    # 1-1. 동적 크롤러
    draw_rounded_rect(draw, (60, 215, 910, 295), radius=8, fill=C_INNER_BG, outline=(35, 60, 110), width=1)
    draw_rounded_rect(draw, (75, 225, 185, 248), radius=4, fill=(30, 64, 175))
    draw.text((82, 229), "동적 크롤러", font=f_badge, fill=C_WHITE)
    draw.text((195, 227), "Playwright & BeautifulSoup4 웹 수집기", font=f_card_h, fill=C_CYAN)
    draw.text((80, 257), "• 대학 본부, 단과대, 학사 FAQ(179건), 학사 서식(57건), 연간 학사일정 자동 수집", font=f_body, fill=C_WHITE)
    draw.text((80, 275), "• 공지 아카이브(960건) 및 최신 공지 변경 시 타임스탬프 기반 정정본 자동 반영", font=f_body, fill=C_MUTED)

    # 1-2. 자체 문서 파서
    draw_rounded_rect(draw, (60, 310, 910, 440), radius=8, fill=C_INNER_BG, outline=C_BLUE, width=1)
    draw_rounded_rect(draw, (75, 320, 205, 343), radius=4, fill=(14, 116, 144))
    draw.text((82, 324), "자체 문서 파서", font=f_badge, fill=C_WHITE)
    draw.text((215, 322), "비정형 문서 추출 파이프라인 (상용 프로그램 종속 탈피)", font=f_card_h, fill=C_CYAN)
    draw.text((80, 350), "• HWP 5.0 : olefile 기반 OLE 스트림 파싱 + raw deflate(zlib) 해제 + 태그 레코드(67) 추출", font=f_body, fill=C_WHITE)
    draw.text((80, 370), "• HWPX : 표준 KS X 6101 규격 기반 순수 XML 무손실 텍스트 파싱", font=f_body, fill=C_WHITE)
    draw.text((80, 390), "• PDF : 텍스트 레이어 초고속 추출(pypdf) + 스캔형 PDF 자동 감지 및 렌더링(pypdfium2)", font=f_body, fill=C_WHITE)
    draw.text((80, 410), "• 이미지/포스터 : Tesseract OCR 한국어/영어(kor+eng) 로컬 엔진 결합", font=f_body, fill=C_WHITE)

    # 1-3. 보안 & 자원 격리
    draw_rounded_rect(draw, (60, 455, 910, 530), radius=8, fill=C_INNER_BG, outline=(35, 60, 110), width=1)
    draw_rounded_rect(draw, (75, 465, 195, 488), radius=4, fill=(6, 95, 70))
    draw.text((82, 469), "보안 및 캐싱", font=f_badge, fill=C_WHITE)
    draw.text((205, 467), "파이프라인 보안 및 안정성 엔지니어링", font=f_card_h, fill=C_GREEN)
    draw.text((80, 495), "• SSRF 사설망(127.0.0.1, 10.0.0.0/8 등) 차단  |  20MB 용량 상한  |  SHA-256 해시 중복 캐시", font=f_body, fill=C_MUTED)

    # ── 계층 2: 임베딩 및 벡터 데이터베이스 ──
    draw_rounded_rect(draw, (40, 570, 930, 960), radius=14, fill=C_CARD_BG, outline=C_PURPLE, width=2)
    draw_rounded_rect(draw, (40, 570, 930, 625), radius=14, fill=(45, 25, 80))
    draw.text((65, 585), "2. 임베딩 및 벡터 데이터베이스 (Vector Store)", font=f_layer_h, fill=C_WHITE)
    draw_rounded_rect(draw, (770, 583, 910, 612), radius=5, fill=C_PURPLE)
    draw.text((785, 587), "LOCAL STORAGE", font=f_badge, fill=C_WHITE)

    # 2-1. 임베딩 모델
    draw_rounded_rect(draw, (60, 645, 910, 735), radius=8, fill=C_INNER_BG, outline=(60, 40, 110), width=1)
    draw_rounded_rect(draw, (75, 655, 185, 678), radius=4, fill=(109, 40, 217))
    draw.text((82, 659), "임베딩 모델", font=f_badge, fill=C_WHITE)
    draw.text((195, 657), "한국어 특화 임베딩 (jhgan/ko-sroberta-multitask)", font=f_card_h, fill=C_PURPLE)
    draw.text((80, 687), "• HuggingFace Sentence-BERT 기반 한국어 어휘 밀집 벡터화 (768차원)", font=f_body, fill=C_WHITE)
    draw.text((80, 707), "• 질문과 학사 공지 문장 간 의미적 맥락 유사도를 정밀하게 인덱싱", font=f_body, fill=C_MUTED)

    # 2-2. 오픈소스 벡터 DB
    draw_rounded_rect(draw, (60, 750, 910, 840), radius=8, fill=C_INNER_BG, outline=(60, 40, 110), width=1)
    draw_rounded_rect(draw, (75, 760, 175, 783), radius=4, fill=(88, 28, 135))
    draw.text((82, 764), "벡터 DB", font=f_badge, fill=C_WHITE)
    draw.text((185, 762), "오픈소스 임베딩 저장소 (ChromaDB)", font=f_card_h, fill=C_PURPLE)
    draw.text((80, 792), "• 외부 클라우드 종속 없는 로컬 디렉터리 기반 영구 저장 (온프레미스 인프라)", font=f_body, fill=C_WHITE)
    draw.text((80, 812), "• 코사인 유사도 고속 검색 및 검증/운영 DB 경로 격리(PermissionError 방어)", font=f_body, fill=C_MUTED)

    # 2-3. 메타데이터 구조
    draw_rounded_rect(draw, (60, 855, 910, 940), radius=8, fill=C_INNER_BG, outline=(60, 40, 110), width=1)
    draw_rounded_rect(draw, (75, 865, 185, 888), radius=4, fill=(55, 48, 163))
    draw.text((82, 869), "메타데이터", font=f_badge, fill=C_WHITE)
    draw.text((195, 867), "다차원 속성 태깅 및 필터링 인덱스", font=f_card_h, fill=C_PURPLE)
    draw.text((80, 897), "• 등록일자(date), 출처분류(guidance/faq/form/notice), 본문상태(complete/title_only)", font=f_body, fill=C_WHITE)
    draw.text((80, 917), "• 공지 원문 URL 매핑으로 요약 답변 생성 시 정확한 공식 출처 카드 즉시 반환", font=f_body, fill=C_MUTED)

    # ── 계층 3: 학사 도메인 특화 RAG 엔진 ──
    draw_rounded_rect(draw, (960, 570, 1880, 960), radius=14, fill=C_CARD_BG, outline=C_AMBER, width=2)
    draw_rounded_rect(draw, (960, 570, 1880, 625), radius=14, fill=(65, 45, 15))
    draw.text((985, 585), "3. 학사 도메인 특화 RAG 엔진 (Domain RAG Core)", font=f_layer_h, fill=C_WHITE)
    draw_rounded_rect(draw, (1700, 583, 1860, 612), radius=5, fill=C_AMBER)
    draw.text((1722, 587), "CORE ENGINE", font=f_badge, fill=C_WHITE)

    # 3-1. LangChain
    draw_rounded_rect(draw, (980, 645, 1860, 725), radius=8, fill=C_INNER_BG, outline=(90, 65, 20), width=1)
    draw_rounded_rect(draw, (995, 655, 1105, 678), radius=4, fill=(180, 83, 9))
    draw.text((1002, 659), "파이프라인", font=f_badge, fill=C_WHITE)
    draw.text((1115, 657), "LangChain LCEL 체인 오케스트레이션", font=f_card_h, fill=C_AMBER)
    draw.text((1000, 687), "• LCEL(LangChain Expression Language) 체인 구조로 프롬프트 주입 및 생성 제어", font=f_body, fill=C_WHITE)
    draw.text((1000, 705), "• 503 서버 혼잡 시 지수 백오프 1회 재시도 및 429 한도 초과 시 정제된 사용자 안내", font=f_body, fill=C_MUTED)

    # 3-2. 휴리스틱 리랭커
    draw_rounded_rect(draw, (980, 740, 1860, 855), radius=8, fill=C_INNER_BG, outline=C_AMBER, width=1)
    draw_rounded_rect(draw, (995, 750, 1115, 773), radius=4, fill=(217, 119, 6))
    draw.text((1002, 754), "규칙 리랭커", font=f_badge, fill=C_WHITE)
    draw.text((1125, 752), "학사 도메인 특화 휴리스틱 순위 보정 엔진", font=f_card_h, fill=C_AMBER)
    draw.text((1000, 780), "• 연도/학기/차수 정합성 : 쿼리 연도와 상충하는 과거 공지 감점(-0.40) & 최근 3개월 우대(+0.22)", font=f_body, fill=C_WHITE)
    draw.text((1000, 800), "• 상시안내 정책 분리 : 학사일정·FAQ·서식 등 상시 문서는 연도 불일치/경과일수 감점 전면 면제", font=f_body, fill=C_WHITE)
    draw.text((1000, 820), "• 전문 약어 구제 : TOPCIT, CPA, TOEIC, IPP 등 학내 고유 약어 질문 어휘 가산점(+0.08)", font=f_body, fill=C_WHITE)

    # 3-3. 오프토픽 필터
    draw_rounded_rect(draw, (980, 870, 1860, 940), radius=8, fill=C_INNER_BG, outline=(90, 65, 20), width=1)
    draw_rounded_rect(draw, (995, 880, 1095, 903), radius=4, fill=(154, 52, 18))
    draw.text((1002, 884), "가드레일", font=f_badge, fill=C_WHITE)
    draw.text((1105, 882), "비학사 오프토픽(Off-Topic) 조기 차단", font=f_card_h, fill=C_AMBER)
    draw.text((1000, 910), "• 순수 코딩 과제 요청('파이썬 코드 짜줘')은 조기 0건 차단, 교내 기술 교육은 정상 통과", font=f_body, fill=C_MUTED)

    # ── 계층 4: 서빙 및 하이브리드 LLM 계층 ──
    draw_rounded_rect(draw, (960, 140, 1880, 550), radius=14, fill=C_CARD_BG, outline=C_BLUE, width=2)
    draw_rounded_rect(draw, (960, 140, 1880, 195), radius=14, fill=(15, 35, 75))
    draw.text((985, 155), "4. 서빙 및 하이브리드 LLM 계층 (Serving & Interface)", font=f_layer_h, fill=C_WHITE)
    draw_rounded_rect(draw, (1700, 153, 1860, 182), radius=5, fill=C_BLUE)
    draw.text((1715, 157), "FULL-STACK READY", font=f_badge, fill=C_WHITE)

    # 4-1. FastAPI 비동기 백엔드
    draw_rounded_rect(draw, (980, 215, 1860, 295), radius=8, fill=C_INNER_BG, outline=(35, 60, 110), width=1)
    draw_rounded_rect(draw, (995, 225, 1105, 248), radius=4, fill=(29, 78, 216))
    draw.text((1002, 229), "백엔드 API", font=f_badge, fill=C_WHITE)
    draw.text((1115, 227), "FastAPI 비동기 고성능 RESTful 서버", font=f_card_h, fill=C_CYAN)
    draw.text((1000, 257), "• REST 엔드포인트: /health (헬스체크), /api/retrieve (고속 검색), /api/query (요약 질의)", font=f_body, fill=C_WHITE)
    draw.text((1000, 275), "• 쿠버네티스 Startup Probe를 0.1초 만에 통과시키는 비차단 지연 로딩 아키텍처", font=f_body, fill=C_MUTED)

    # 4-2. 하이브리드 LLM 스위칭
    draw_rounded_rect(draw, (980, 310, 1860, 420), radius=8, fill=C_INNER_BG, outline=C_GREEN, width=1)
    draw_rounded_rect(draw, (995, 320, 1115, 343), radius=4, fill=(5, 150, 105))
    draw.text((1002, 324), "하이브리드 LLM", font=f_badge, fill=C_WHITE)
    draw.text((1125, 322), "오픈소스 SLM & 상용 클라우드 모델 스위칭", font=f_card_h, fill=C_GREEN)
    draw.text((1000, 350), "• [오픈소스 로컬 SLM] : HuggingFace Qwen 2.5-1.5B / Gemma 2-2B (데이터 프라이버시 보장)", font=f_body, fill=C_WHITE)
    draw.text((1000, 372), "• [클라우드 상용 API] : Google Gemini 2.0/3.8 Flash & OpenAI GPT-4o-mini 연동 지원", font=f_body, fill=C_WHITE)
    draw.text((1000, 394), "• 환경 변수(LLM_PROVIDER) 설정 하나로 로컬/클라우드 모델 즉시 무중단 전환", font=f_body, fill=C_MUTED)

    # 4-3. 클라이언트 인터페이스
    draw_rounded_rect(draw, (980, 435, 1860, 530), radius=8, fill=C_INNER_BG, outline=(35, 60, 110), width=1)
    draw_rounded_rect(draw, (995, 445, 1115, 468), radius=4, fill=(2, 132, 199))
    draw.text((1002, 449), "클라이언트 UI", font=f_badge, fill=C_WHITE)
    draw.text((1125, 447), "모바일 반응형 웹 및 대시보드", font=f_card_h, fill=C_CYAN)
    draw.text((1000, 475), "• React 18 + TypeScript + Vite + Tailwind CSS 모바일 반응형 웹 프론트엔드", font=f_body, fill=C_WHITE)
    draw.text((1000, 497), "• 2~3줄 핵심 요약 + 공식 공지사항 원문 링크/등록일 카드 즉시 렌더링", font=f_body, fill=C_MUTED)

    draw_rounded_rect(draw, (40, 980, W - 40, 1050), radius=10, fill=(15, 25, 50), outline=C_CYAN, width=1)
    draw_rounded_rect(draw, (55, 998, 145, 1032), radius=4, fill=(14, 116, 144))
    draw.text((63, 1006), "엔드투엔드", font=f_badge, fill=C_WHITE)
    draw.text((155, 1004), "실시간 처리 흐름 :", font=f_card_h, fill=C_CYAN)
    
    steps = [
        "1. 학생 자연어 질문",
        "2. 엔티티/약어 추출",
        "3. ChromaDB 밀집 검색",
        "4. 학사 규칙 리랭킹",
        "5. 하이브리드 LLM 요약",
        "6. 모바일 카드 응답"
    ]
    x_cur = 310
    for i, step in enumerate(steps):
        draw_rounded_rect(draw, (x_cur, 998, x_cur + int(f_body.getlength(step)) + 20, 1032), radius=6, fill=C_INNER_BG, outline=(50, 75, 125))
        draw.text((x_cur + 10, 1007), step, font=f_body, fill=C_WHITE)
        x_cur += int(f_body.getlength(step)) + 28
        
        if i < len(steps) - 1:
            # 깔끔한 화살표 폴리곤 그리기
            ax = x_cur
            ay = 1015
            draw.polygon([(ax, ay - 6), (ax + 10, ay), (ax, ay + 6)], fill=C_CYAN)
            x_cur += 22

    # 저장
    img.save(output_path, quality=95)
    print(f"Korean Architecture diagram successfully saved to {output_path}")

if __name__ == "__main__":
    render_korean_architecture()
