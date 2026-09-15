import { useState, useRef, useEffect } from "react";

interface SourceItem {
  badge?: string;
  category?: string;
  source?: string;
  title: string;
  date?: string;
  meta?: string;
  url?: string;
}

interface Message {
  id: number;
  role: "user" | "bot";
  text: string;
  chips?: string[];
  sources?: SourceItem[];
  isError?: boolean;
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: 0,
    role: "bot",
    text: "안녕하세요! 한성대학교 공지 챗봇 CampusRAG입니다. 🎓\n학사, 장학, 학교 생활에 대해 궁금한 점을 물어보세요.",
    chips: [
      "2026학년도 수강신청 일정 알려줘",
      "국가장학금 신청 기간과 가구원 동의 기간",
      "전공연계 멘토링 참가자 신청",
    ],
  },
];

function BotBubble({ msg, onChip }: { msg: Message; onChip?: (t: string) => void }) {
  const lines = msg.text.split("\n");
  return (
    <div className="flex items-start gap-2.5 w-full animate-fadein">
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 mt-0.5 shadow-sm"
        style={{ background: "#EFF6FF", border: "1px solid #DBEAFE" }}
      >
        🎓
      </div>
      <div className="flex-1 min-w-0 flex flex-col gap-2">
        {/* 요약 답변 말풍선 */}
        <div
          className="px-4 py-3 rounded-2xl rounded-tl-sm text-[14px] leading-relaxed break-words"
          style={{
            background: msg.isError ? "#FEF2F2" : "#FFFFFF",
            border: `1px solid ${msg.isError ? "#FECACA" : "#E2E8F0"}`,
            color: msg.isError ? "#991B1B" : "#0F172A",
            boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
          }}
        >
          {lines.map((line, i) => {
            if (line.startsWith("•") || line.startsWith("-")) {
              const content = line.slice(1).trim();
              return (
                <div key={i} className="flex items-start gap-2 mt-1.5 first:mt-0">
                  <span className="text-blue-600 font-bold leading-relaxed">•</span>
                  <span className="leading-relaxed">{content}</span>
                </div>
              );
            }
            return (
              <p key={i} className="leading-relaxed mb-1 last:mb-0">
                {line}
              </p>
            );
          })}
        </div>

        {/* 퀵 질문 칩 */}
        {msg.chips && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {msg.chips.map((c) => (
              <button
                key={c}
                onClick={() => onChip?.(c)}
                className="text-xs font-medium px-3 py-1.5 rounded-full transition-all active:scale-95 hover:bg-blue-100 cursor-pointer text-left"
                style={{
                  background: "#EFF6FF",
                  color: "#2563EB",
                  border: "1px solid #BFDBFE",
                }}
              >
                {c}
              </button>
            ))}
          </div>
        )}

        {/* 공지사항 출처 카드들 (RAG 핵심 카드) */}
        {msg.sources && msg.sources.length > 0 && (
          <div className="flex flex-col gap-2 mt-1">
            <div className="text-[12px] font-semibold text-slate-500 px-1 flex items-center gap-1">
              <span>📎</span>
              <span>참고 공식 공지 ({msg.sources.length}건)</span>
            </div>
            {msg.sources.map((src, idx) => (
              <div
                key={idx}
                className="w-full rounded-2xl overflow-hidden transition-all hover:border-blue-300"
                style={{
                  border: "1px solid #E2E8F0",
                  background: "#FFFFFF",
                  boxShadow: "0 2px 5px rgba(0,0,0,0.04)",
                }}
              >
                <div
                  className="px-3.5 py-1.5 flex items-center justify-between"
                  style={{ background: "#F8FAFC", borderBottom: "1px solid #F1F5F9" }}
                >
                  <span
                    className="text-[11px] font-semibold px-2 py-0.5 rounded-md"
                    style={{ background: "#EFF6FF", color: "#1E40AF" }}
                  >
                    {src.category || src.badge || "학내공지"}
                  </span>
                  <span className="text-[11px] text-slate-400">공식 공지</span>
                </div>
                <div className="px-4 py-3">
                  <p className="text-[13px] font-semibold leading-snug text-slate-900 mb-1.5 break-words">
                    {src.title}
                  </p>
                  <p className="text-[11px] text-slate-500 mb-2.5">
                    {src.meta || `${src.date || ""} | ${src.source || "한성대학교"}`}
                  </p>
                  {src.url ? (
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700"
                    >
                      공지 원문 바로가기
                      <svg width="12" height="12" viewBox="0 0 13 13" fill="none">
                        <path
                          d="M3 10L10 3M10 3H5.5M10 3V7.5"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </a>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="flex items-center gap-2.5 animate-fadein">
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0"
        style={{ background: "#EFF6FF", border: "1px solid #DBEAFE" }}
      >
        🎓
      </div>
      <div
        className="px-4 py-3 rounded-2xl rounded-tl-sm flex gap-1.5 items-center shadow-sm"
        style={{ background: "#FFFFFF", border: "1px solid #E2E8F0" }}
      >
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
      </div>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || typing) return;

    const userMsg: Message = { id: Date.now(), role: "user", text: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setTyping(true);

    try {
      // 실제 FastAPI 백엔드 (/api/query) 호출
      const resp = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, top_k: 3 }),
      });

      if (!resp.ok) {
        throw new Error(`서버 응답 오류 (${resp.status})`);
      }

      const data = await resp.json();
      const botAnswer = data.answer || "답변을 가져오지 못했습니다.";
      const rawSources = data.sources || [];

      const mappedSources: SourceItem[] = rawSources.map((s: any) => ({
        title: s.title || "제목 없음",
        category: s.category || "공지사항",
        source: s.source || "한성대학교",
        date: s.date || "",
        url: s.url || "",
        meta: `${s.date || ""} | ${s.source || "한성대학교"}`,
      }));

      const isApiError = data.status === "api_error";

      const botMsg: Message = {
        id: Date.now() + 1,
        role: "bot",
        text: botAnswer,
        sources: mappedSources,
        isError: isApiError,
      };

      setMessages((prev) => [...prev, botMsg]);
    } catch (err: any) {
      console.error("질의 요청 실패:", err);
      const fallbackMsg: Message = {
        id: Date.now() + 1,
        role: "bot",
        text: "⚠️ 백엔드 서버(FastAPI)와 통신할 수 없습니다. 서버가 8000번 포트에서 켜져 있는지 확인해 주세요.",
        isError: true,
      };
      setMessages((prev) => [...prev, fallbackMsg]);
    } finally {
      setTyping(false);
    }
  }

  function reset() {
    setMessages(INITIAL_MESSAGES);
    setInput("");
    setTyping(false);
  }

  return (
    <div className="flex flex-col w-full h-[100dvh] max-w-full overflow-hidden bg-slate-50 select-none">
      {/* 상단 헤더 */}
      <header
        className="flex items-center justify-between px-4 py-3.5 flex-shrink-0 z-10"
        style={{
          background: "rgba(255, 255, 255, 0.95)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid #E2E8F0",
          paddingTop: "max(12px, env(safe-area-inset-top))",
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight text-slate-900">CampusRAG</span>
          <span className="text-base">🎓</span>
          <span className="text-[10px] font-semibold bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded border border-blue-200">
            한성대 공지봇
          </span>
        </div>
        <button
          onClick={reset}
          className="w-8 h-8 rounded-full flex items-center justify-center transition-colors hover:bg-slate-100 text-slate-500 cursor-pointer"
          title="대화 초기화"
        >
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path
              d="M13 8A5 5 0 0 1 3.4 10.8M3 8A5 5 0 0 1 12.6 5.2"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            <path d="M12 5H14V3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4 11H2v2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </header>

      {/* 대화 메시지 목록 */}
      <main className="flex-1 overflow-y-auto chat-scroll px-4 py-4 flex flex-col gap-3.5">
        {messages.map((msg) =>
          msg.role === "bot" ? (
            <BotBubble key={msg.id} msg={msg} onChip={send} />
          ) : (
            <div key={msg.id} className="flex justify-end w-full animate-fadein">
              <div
                className="px-4 py-2.5 rounded-2xl rounded-tr-sm text-[14px] leading-relaxed text-white font-medium max-w-[80%] break-words"
                style={{
                  background: "#2563EB",
                  boxShadow: "0 2px 6px rgba(37,99,235,0.22)",
                }}
              >
                {msg.text}
              </div>
            </div>
          )
        )}
        {typing && <TypingBubble />}
        <div ref={bottomRef} />
      </main>

      {/* 하단 메시지 입력창 */}
      <footer
        className="px-4 py-3 flex-shrink-0 z-10"
        style={{
          background: "#FFFFFF",
          borderTop: "1px solid #E2E8F0",
          paddingBottom: "max(12px, env(safe-area-inset-bottom))",
        }}
      >
        <div
          className="flex items-center gap-2 px-3.5 py-2 rounded-2xl transition-all"
          style={{
            background: "#F8FAFC",
            border: `1.5px solid ${input.trim() ? "#2563EB" : "#E2E8F0"}`,
            boxShadow: input.trim() ? "0 0 0 3px rgba(37,99,235,0.08)" : "none",
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="공지사항에 대해 질문하세요..."
            className="flex-1 bg-transparent text-[14px] outline-none placeholder-slate-400 text-slate-900 min-w-0"
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || typing}
            className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-transform active:scale-90 disabled:opacity-40 cursor-pointer"
            style={{
              background: input.trim() && !typing ? "#2563EB" : "#94A3B8",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
              <path
                d="M7 12V2M7 2L3 6M7 2l4 4"
                stroke="white"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </footer>
    </div>
  );
}
