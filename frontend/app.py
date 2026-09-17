"""
CampusRAG Streamlit 프론트엔드 챗봇 UI

기능:
  - 자연어 대화형 챗봇 인터페이스
  - 검색 결과 출처 카드 렌더링 (제목, 출처, 날짜, 원문 링크)
  - 검색 전용 / RAG 전체 모드 선택

실행:
  streamlit run frontend/app.py
"""

import os
import requests
import streamlit as st

# ── 페이지 설정 ──────────────────────────────
st.set_page_config(
    page_title="CampusRAG 🎓",
    page_icon="🎓",
    layout="centered",
)

# ── 상수 ─────────────────────────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


# ── 스타일 주입 (모바일 반응형 및 카드 디자인) ────────
CUSTOM_CSS = """
<style>
/* 모바일 뷰포트 (<=600px) 대응 */
@media (max-width: 600px) {
    .stApp {
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
    }
    .source-card {
        padding: 10px 12px !important;
        margin-bottom: 6px !important;
    }
    .source-card-title {
        font-size: 13px !important;
    }
    .source-card-meta {
        font-size: 11px !important;
        gap: 4px !important;
    }
    .source-card-link {
        font-size: 11px !important;
    }
    .stChatMessage {
        padding: 8px 10px !important;
    }
}

.source-card {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
    background-color: #f8fafc;
    transition: all 0.2s ease-in-out;
}
.source-card:hover {
    background-color: #f1f5f9;
    border-color: #cbd5e1;
}
.source-card-title {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
    line-height: 1.4;
    word-break: break-word;
}
.source-card-meta {
    font-size: 12px;
    color: #64748b;
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.source-card-link {
    display: inline-block;
    margin-top: 8px;
    font-size: 12px;
    color: #2563eb;
    text-decoration: none;
    font-weight: 500;
}
.source-card-link:hover {
    text-decoration: underline;
}
.retry-banner {
    border: 1px solid #fecaca;
    background-color: #fef2f2;
    color: #991b1b;
    padding: 10px 14px;
    border-radius: 6px;
    font-size: 13px;
    margin-top: 8px;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def check_server_health() -> dict | None:
    """백엔드 서버 상태를 확인한다."""
    try:
        resp = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except requests.ConnectionError:
        return None
    return None


def call_retrieve(question: str, top_k: int = 3) -> dict | None:
    """검색 전용 API를 호출한다."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/retrieve",
            json={"question": question, "top_k": top_k},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"API 오류: {resp.status_code} - {resp.text}")
    except requests.ConnectionError:
        st.markdown(
            """<div class="retry-banner">
            ❌ <strong>백엔드 서버 연결 불가</strong>: API 서버가 실행 중인지 확인하세요.<br>
            <code>uvicorn backend.main:app --port 8000</code>
            </div>""",
            unsafe_allow_html=True,
        )
    return None


def call_query(question: str, top_k: int = 3) -> dict | None:
    """RAG 전체 파이프라인 API를 호출한다."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/query",
            json={"question": question, "top_k": top_k},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"API 오류: {resp.status_code} - {resp.text}")
    except requests.ConnectionError:
        st.markdown(
            """<div class="retry-banner">
            ❌ <strong>백엔드 서버 연결 불가</strong>: API 서버가 실행 중인지 확인하세요.<br>
            <code>uvicorn backend.main:app --port 8000</code>
            </div>""",
            unsafe_allow_html=True,
        )
    except requests.Timeout:
        st.warning("⏱ LLM 응답 시간 초과. 모델 연산에 시간이 더 필요할 수 있습니다.")
    return None


def get_source_card_html(source: dict, index: int = 0) -> str:
    """출처 카드 HTML 문자열을 반환한다."""
    title = source.get("title", "제목 없음")
    dept = source.get("source", "")
    cat = source.get("category", "")
    date = source.get("date", "")
    url = source.get("url", "#")

    meta_parts = []
    if dept:
        meta_parts.append(f"🏛 {dept}")
    if cat:
        meta_parts.append(f"📂 {cat}")
    if date:
        meta_parts.append(f"📅 {date}")
    meta_str = " · ".join(meta_parts)

    return f"""
    <div class="source-card">
        <div class="source-card-title">📌 {title}</div>
        <div class="source-card-meta">{meta_str}</div>
        <a class="source-card-link" href="{url}" target="_blank">🔗 원문 보기 →</a>
    </div>
    """


def render_source_card(source: dict, index: int = 0):
    """출처 카드를 렌더링한다."""
    st.markdown(get_source_card_html(source, index), unsafe_allow_html=True)


# ── 사이드바 ─────────────────────────────────
with st.sidebar:
    st.title("⚙️ 설정")

    # 서버 상태
    health = check_server_health()
    if health:
        st.success("✅ 서버 연결됨")
        st.caption(f"LLM: `{health.get('llm_provider', 'N/A')}`")
        st.caption(f"적재 문서: `{health.get('doc_count', 0)}`건")
    else:
        st.error("❌ 서버 연결 안 됨")
        st.caption("서버 실행: `uvicorn backend.main:app --port 8000`")

    st.divider()

    mode = st.radio(
        "응답 모드",
        ["🔍 검색만 (빠름)", "🤖 AI 답변 + 검색 (RAG)"],
        index=0,
        help="검색만: 관련 공지 목록만 반환\nAI 답변: LLM이 요약 답변 생성",
    )

    top_k = st.slider("검색 결과 수", 1, 10, 3)

    st.divider()
    with st.expander("⚖️ 오픈소스 및 저작권 고지"):
        st.markdown(
            """
            **🎓 프로젝트 라이선스**
            - CampusRAG: MIT License
            - Copyright (c) 2026 CampusRAG Team
            
            **🤖 AI 모델**
            - `ko-sroberta-multitask`: CC BY-SA 4.0 (정훈 간)
            - `Qwen2.5-1.5B-Instruct`: Apache-2.0 (Alibaba Cloud)
            
            **🛠 주요 오픈소스 SW**
            - Tesseract OCR (Apache-2.0)
            - LangChain (MIT), ChromaDB (Apache-2.0)
            - FastAPI (MIT), Streamlit (Apache-2.0)
            
            **⚠️ 데이터 출처 및 면책 안내**
            - 한성대학교 비공식 캡스톤디자인 연구 프로젝트
            - 공지 원저작권: 한성대학교 (Hansung University)
            - 중요 일정은 공식 공지 원문 링크를 확인하세요.
            """
        )
    st.caption("CampusRAG v1.0 | 한성대학교 캡스톤디자인")

# ── 메인 영역 ────────────────────────────────
st.title("🎓 CampusRAG")
st.caption("한성대학교 학내 공지사항 AI 검색 챗봇")

# 채팅 히스토리 초기화
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "안녕하세요! 한성대학교 공지사항에 대해 궁금한 것을 물어보세요. 🎓",
        }
    ]

# 히스토리 렌더링 (연속 질문 시 격리된 컨테이너)
for msg_idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.container():
                for src_idx, src in enumerate(msg["sources"]):
                    render_source_card(src, src_idx)

# 사용자 입력
if prompt := st.chat_input("궁금한 것을 물어보세요 (예: 수강신청 정정 기간이 언제야?)"):
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 어시스턴트 응답
    with st.chat_message("assistant"):
        if not health:
            error_msg = "❌ 백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."
            st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        elif "검색만" in mode:
            with st.spinner("🔍 공지사항을 검색하고 있습니다..."):
                result = call_retrieve(prompt, top_k)
            if result:
                sources = result.get("results", [])
                if sources:
                    content_text = f"**{len(sources)}건의 관련 공지를 찾았습니다:**"
                    st.markdown(content_text)
                    with st.container():
                        for i, src in enumerate(sources):
                            render_source_card(src, i)
                else:
                    content_text = "관련 공지를 찾지 못했습니다."
                    st.markdown(content_text)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": content_text,
                        "sources": sources,
                    }
                )
        else:  # RAG 모드
            with st.spinner("🤖 AI가 답변을 생성하고 있습니다..."):
                result = call_query(prompt, top_k)
            if result:
                ans_text = result.get("answer", "")
                sources = result.get("sources", [])
                status = result.get("status", "success")
                error_type = result.get("error_type")

                if status == "api_error":
                    if error_type == "rate_limit":
                        st.warning("⚠️ AI 서비스 요청 한도(Rate Limit)에 도달하여 일시 안내가 표시됩니다.")
                    elif error_type == "service_unavailable":
                        st.warning("⚠️ AI 서비스 일시적 서버 혼잡(503)으로 재시도 후 장애 안내가 표시됩니다.")
                    elif error_type == "auth_error":
                        st.error("🔒 AI 서비스 인증/권한 오류가 발생했습니다.")
                    else:
                        st.warning("⚠️ AI 서비스 일시 장애가 발생했습니다.")

                st.markdown(ans_text)
                if sources:
                    st.markdown("---")
                    st.markdown("**📎 참고 공지사항:**")

                    with st.container():
                        for i, src in enumerate(sources):
                            render_source_card(src, i)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": ans_text,
                        "sources": sources,
                    }
                )
