"""
CampusRAG Streamlit 프론트엔드 챗봇 UI

기능:
  - 자연어 대화형 챗봇 인터페이스
  - 검색 결과 출처 카드 렌더링 (제목, 출처, 날짜, 원문 링크)
  - 검색 전용 / RAG 전체 모드 선택

실행:
  streamlit run frontend/app.py
"""

import requests
import streamlit as st

# ── 페이지 설정 ──────────────────────────────
st.set_page_config(
    page_title="CampusRAG 🎓",
    page_icon="🎓",
    layout="centered",
)

# ── 상수 ─────────────────────────────────────
API_BASE_URL = "http://localhost:8000"


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
        st.error("❌ 백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
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
        st.error("❌ 백엔드 서버에 연결할 수 없습니다.")
    except requests.Timeout:
        st.error("⏱ 응답 시간 초과. LLM 처리에 시간이 걸릴 수 있습니다.")
    return None


def render_source_card(source: dict, index: int):
    """출처 카드를 렌더링한다."""
    with st.container():
        st.markdown(
            f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px 16px;
                margin-bottom: 8px;
                background-color: #f8f9fa;
            ">
                <div style="font-size: 14px; font-weight: 600; color: #1a1a1a;">
                    📌 {source.get('title', '제목 없음')}
                </div>
                <div style="font-size: 12px; color: #666; margin-top: 4px;">
                    🏛 {source.get('source', '')} · 📂 {source.get('category', '')} · 📅 {source.get('date', '')}
                </div>
                <div style="margin-top: 6px;">
                    <a href="{source.get('url', '#')}" target="_blank"
                       style="font-size: 12px; color: #1a73e8; text-decoration: none;">
                        🔗 원문 보기 →
                    </a>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── 사이드바 ─────────────────────────────────
with st.sidebar:
    st.title("⚙️ 설정")

    # 서버 상태
    health = check_server_health()
    if health:
        st.success(f"✅ 서버 연결됨")
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
    st.caption("CampusRAG v1.0")
    st.caption("한성대학교 캡스톤디자인")

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

# 히스토리 렌더링
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg:
            for i, src in enumerate(msg["sources"]):
                render_source_card(src, i)

# 사용자 입력
if prompt := st.chat_input("궁금한 것을 물어보세요 (예: 수강신청 일정이 언제야?)"):
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 어시스턴트 응답
    with st.chat_message("assistant"):
        if not health:
            st.error("❌ 백엔드 서버에 연결할 수 없습니다.")
            st.session_state.messages.append(
                {"role": "assistant", "content": "❌ 서버 연결 오류"}
            )
        elif "검색만" in mode:
            with st.spinner("🔍 검색 중..."):
                result = call_retrieve(prompt, top_k)
            if result:
                st.markdown(f"**{len(result['results'])}건의 관련 공지를 찾았습니다:**")
                sources = result["results"]
                for i, src in enumerate(sources):
                    render_source_card(src, i)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": f"{len(sources)}건의 관련 공지를 찾았습니다:",
                        "sources": sources,
                    }
                )
        else:  # RAG 모드
            with st.spinner("🤖 AI가 답변을 생성하고 있습니다..."):
                result = call_query(prompt, top_k)
            if result:
                st.markdown(result["answer"])
                if result.get("sources"):
                    st.markdown("---")
                    st.markdown("**📎 참고 공지사항:**")
                    for i, src in enumerate(result["sources"]):
                        render_source_card(src, i)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "sources": result.get("sources", []),
                    }
                )
