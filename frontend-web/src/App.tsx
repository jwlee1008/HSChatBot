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

function InfoLicenseModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<"about" | "models" | "oss">("about");

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3.5 sm:p-4 bg-slate-900/50 backdrop-blur-xs animate-fadein"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-lg rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] overflow-hidden select-text"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 모달 상단 헤더 */}
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between bg-white">
          <div className="flex items-center gap-2">
            <span className="text-base">🎓</span>
            <h2 className="font-bold text-slate-900 text-[14px]">CampusRAG 안내 및 오픈소스 라이선스</h2>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer text-sm font-bold"
            title="닫기"
          >
            ✕
          </button>
        </div>

        {/* 탭 네비게이션 */}
        <div className="flex border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-600">
          <button
            onClick={() => setActiveTab("about")}
            className={`flex-1 py-2.5 px-2 text-center border-b-2 transition-all cursor-pointer ${
              activeTab === "about"
                ? "border-blue-600 text-blue-600 font-semibold bg-white"
                : "border-transparent hover:text-slate-900"
            }`}
          >
            프로젝트 & 면책
          </button>
          <button
            onClick={() => setActiveTab("models")}
            className={`flex-1 py-2.5 px-2 text-center border-b-2 transition-all cursor-pointer ${
              activeTab === "models"
                ? "border-blue-600 text-blue-600 font-semibold bg-white"
                : "border-transparent hover:text-slate-900"
            }`}
          >
            AI 모델 & 폰트
          </button>
          <button
            onClick={() => setActiveTab("oss")}
            className={`flex-1 py-2.5 px-2 text-center border-b-2 transition-all cursor-pointer ${
              activeTab === "oss"
                ? "border-blue-600 text-blue-600 font-semibold bg-white"
                : "border-transparent hover:text-slate-900"
            }`}
          >
            오픈소스 SW
          </button>
        </div>

        {/* 모달 본문 내용 */}
        <div className="flex-1 overflow-y-auto p-4 text-xs text-slate-700 leading-relaxed space-y-3 chat-scroll">
          {activeTab === "about" && (
            <div className="space-y-3">
              <div className="bg-blue-50/80 border border-blue-100 rounded-xl p-3 text-blue-950">
                <div className="font-bold text-[13px] mb-1 flex items-center gap-1.5">
                  <span>📌</span>
                  <span>한성대학교 학내 공지 통합 RAG 챗봇</span>
                </div>
                <p className="text-[12px] leading-relaxed text-blue-900">
                  CampusRAG는 여러 게시판에 분산된 학내 공지사항과 첨부파일(PDF, HWP, HWPX, 이미지) 속 텍스트를 로컬 인공지능으로 분석하여, 핵심 요약과 공식 원문 링크 카드를 제공하는 캡스톤디자인 연구 프로젝트입니다.
                </p>
              </div>

              <div className="bg-amber-50/80 border border-amber-200 rounded-xl p-3 text-amber-950">
                <div className="font-bold text-[13px] mb-1.5 flex items-center gap-1.5 text-amber-900">
                  <span>⚠️</span>
                  <span>비공식 서비스 안내 및 면책 조항</span>
                </div>
                <ul className="list-disc list-inside space-y-1.5 text-[11.5px] leading-normal text-amber-800">
                  <li>본 시스템은 한성대학교 캡스톤디자인 비영리 학술 연구 목적으로 제작되었으며, 한성대학교의 공식 서비스가 아닙니다.</li>
                  <li>AI 생성 답변의 특성상 최신 행정 변경 사항 누락이나 왜곡(Hallucination)이 발생할 수 있습니다.</li>
                  <li>장학금 신청, 수강신청, 졸업요건 등 중요한 학사 일정은 반드시 답변 하단의 <strong>공식 공지 원문 바로가기</strong>를 확인하시기 바랍니다.</li>
                </ul>
              </div>

              <div className="bg-slate-50 border border-slate-200 rounded-xl p-3">
                <div className="font-bold text-slate-900 mb-1 text-[12px]">학내 공지 데이터 저작권</div>
                <p className="text-[11.5px] text-slate-600">
                  색인 및 검색에 활용된 공지사항 본문 및 첨부파일 데이터의 모든 저작권은 <strong>한성대학교(Hansung University)</strong>에 귀속됩니다. (Copyright © Hansung University. All Rights Reserved.)
                </p>
              </div>
            </div>
          )}

          {activeTab === "models" && (
            <div className="space-y-2.5">
              <div className="border border-slate-200 rounded-xl p-3 bg-white shadow-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold text-slate-900 text-[12.5px]">ko-sroberta-multitask</span>
                  <span className="px-1.5 py-0.5 bg-blue-100 text-blue-800 rounded text-[10px] font-semibold">CC BY-SA 4.0</span>
                </div>
                <p className="text-[11px] text-slate-500 mb-1">한국어 특화 문장 임베딩 모델 (KLUE RoBERTa 기반 파인튜닝)</p>
                <div className="text-[11px] text-slate-600 bg-slate-50 p-2 rounded border border-slate-100">
                  <strong>저작자:</strong> 정훈 간 (jhgan) / <a href="https://huggingface.co/jhgan/ko-sroberta-multitask" target="_blank" rel="noreferrer" className="text-blue-600 underline">HuggingFace 모델</a>
                </div>
              </div>

              <div className="border border-slate-200 rounded-xl p-3 bg-white shadow-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold text-slate-900 text-[12.5px]">Qwen2.5-1.5B-Instruct</span>
                  <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-800 rounded text-[10px] font-semibold">Apache-2.0</span>
                </div>
                <p className="text-[11px] text-slate-500 mb-1">경량 로컬 생성 언어 모델 (SLM)</p>
                <div className="text-[11px] text-slate-600 bg-slate-50 p-2 rounded border border-slate-100">
                  <strong>저작자:</strong> Alibaba Cloud (Qwen Team) / Copyright (c) Alibaba Cloud
                </div>
              </div>

              <div className="border border-slate-200 rounded-xl p-3 bg-white shadow-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold text-slate-900 text-[12.5px]">Pretendard (웹 폰트)</span>
                  <span className="px-1.5 py-0.5 bg-purple-100 text-purple-800 rounded text-[10px] font-semibold">SIL OFL 1.1</span>
                </div>
                <p className="text-[11px] text-slate-500 mb-1">현대적이고 가독성이 뛰어난 오픈소스 본문 글꼴</p>
                <div className="text-[11px] text-slate-600 bg-slate-50 p-2 rounded border border-slate-100">
                  <strong>저작자:</strong> 길형진 (Kil Hyung-jin, orioncactus) / Copyright (c) 2021 Kil Hyung-jin
                </div>
              </div>
            </div>
          )}

          {activeTab === "oss" && (
            <div className="space-y-2.5">
              <div className="border border-slate-200 rounded-xl p-3 bg-white">
                <div className="font-bold text-slate-900 mb-1 text-[12.5px]">CampusRAG 자체 라이선스</div>
                <p className="text-[11.5px] text-slate-600">
                  MIT License | Copyright (c) 2026 CampusRAG Team (Hansung University Capstone Project)
                </p>
              </div>

              <div className="border border-slate-200 rounded-xl p-3 bg-slate-50 text-[11px] text-slate-700 space-y-1.5">
                <div className="font-bold text-slate-900 text-[12px] mb-1">주요 오픈소스 소프트웨어 라이선스</div>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1">
                  <div>• <strong>LangChain</strong>: MIT</div>
                  <div>• <strong>ChromaDB</strong>: Apache-2.0</div>
                  <div>• <strong>FastAPI</strong>: MIT</div>
                  <div>• <strong>Uvicorn</strong>: BSD-3-Clause</div>
                  <div>• <strong>Sentence-Transformers</strong>: Apache-2.0</div>
                  <div>• <strong>Transformers</strong>: Apache-2.0</div>
                  <div>• <strong>Tesseract OCR</strong>: Apache-2.0</div>
                  <div>• <strong>pypdf / pypdfium2</strong>: BSD-3-Clause</div>
                  <div>• <strong>React & ReactDOM</strong>: MIT</div>
                  <div>• <strong>TailwindCSS / Vite</strong>: MIT</div>
                </div>
              </div>

              <p className="text-[10.5px] text-slate-400 text-center pt-1">
                상세 라이선스 전문 및 NOTICE 문서는 저장소의 <code>OPEN_SOURCE_LICENSES.md</code>를 참조하세요.
              </p>
            </div>
          )}
        </div>

        {/* 모달 하단 닫기 */}
        <div className="px-4 py-2.5 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-[11px] text-slate-500">
          <span>한성대학교 캡스톤디자인</span>
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 font-semibold rounded-lg transition-colors cursor-pointer"
          >
            확인
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);
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
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowInfoModal(true)}
            className="w-8 h-8 rounded-full flex items-center justify-center transition-colors hover:bg-slate-100 text-slate-600 hover:text-blue-600 cursor-pointer"
            title="정보 및 오픈소스 라이선스 고지"
          >
            <span className="text-[15px]">⚖️</span>
          </button>
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
        </div>
      </header>

      {/* 정보 및 라이선스 모달 */}
      <InfoLicenseModal isOpen={showInfoModal} onClose={() => setShowInfoModal(false)} />

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
