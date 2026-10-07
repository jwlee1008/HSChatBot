import { useState, useRef, useEffect, useMemo } from "react";

// ── 타입 정의 ──────────────────────────────────────────

interface SourceItem {
  badge?: string;
  category?: string;
  source?: string;
  title: string;
  date?: string;
  meta?: string;
  url?: string;
  content?: string;
}

interface Message {
  id: number;
  role: "user" | "bot";
  text: string;
  chips?: string[];
  sources?: SourceItem[];
  isError?: boolean;
}

export type ScheduleKind =
  | "ALL_DAY_EVENT"
  | "DATE_ONLY_DEADLINE"
  | "TIME_CONFIRMED_DEADLINE"
  | "TIME_CONFIRMED_EVENT"
  | "SINGLE_POINT_APPOINTMENT";

export type Priority = "HIGH" | "MEDIUM" | "LOW";

export interface ScheduleItem {
  id: string;
  user_id: string;
  title: string;
  description?: string | null;
  course_name?: string | null;
  schedule_kind: ScheduleKind;
  is_all_day: boolean;
  is_time_confirmed: boolean;
  start_date?: string | null;
  end_date?: string | null;
  start_datetime?: string | null;
  end_datetime?: string | null;
  timezone: string;
  source_url?: string | null;
  source_title?: string | null;
  extracted_quote?: string | null;
  is_completed: boolean;
  priority: Priority;
  user_confirmed_at: string;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCandidate {
  title: string;
  schedule_kind?: string;
  start_date?: string | null;
  end_date?: string | null;
  start_datetime?: string | null;
  end_datetime?: string | null;
  extracted_date?: string | null;
  is_all_day?: boolean;
  is_time_confirmed?: boolean;
  unconfirmed_fields?: string[];
  is_ambiguous?: boolean;
  ambiguity_reason?: string | null;
  requires_user_confirmation?: boolean;
  source_quote?: string;
  source_quotes?: string[] | null;
  interpretation_options?: string[] | null;
  action?: "create" | "cancel";
  is_cancellation?: boolean;
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: 0,
    role: "bot",
    text: "안녕하세요! 한성대학교 공지 챗봇 CampusMate입니다. 🎓\n학사, 장학, 학교 생활에 대해 궁금한 점을 물어보세요. 공지 속 일정은 [📅 일정 추출] 버튼을 눌러 확인 후 캘린더에 바로 저장할 수 있습니다.",
    chips: [
      "2026학년도 수강신청 일정 알려줘",
      "국가장학금 신청 기간과 가구원 동의 기간",
      "전공연계 멘토링 참가자 신청",
    ],
  },
];

// ── 유틸 함수 ──────────────────────────────────────────

function getTodaySeoul(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function calculateDDay(targetDateStr?: string | null): { text: string; isUrgent: boolean } | null {
  if (!targetDateStr) return null;
  const dateOnly = targetDateStr.slice(0, 10);
  const today = getTodaySeoul();

  const d1 = new Date(today);
  const d2 = new Date(dateOnly);
  const diffDays = Math.ceil((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays < 0) {
    return { text: `D+${Math.abs(diffDays)}`, isUrgent: false };
  } else if (diffDays === 0) {
    return { text: "D-Day (오늘)", isUrgent: true };
  } else if (diffDays <= 3) {
    return { text: `D-${diffDays}`, isUrgent: true };
  } else {
    return { text: `D-${diffDays}`, isUrgent: false };
  }
}

/**
 * UTC ISO 문자열(예: 2026-11-20T00:00:45.123456Z)을 Asia/Seoul 기준 날짜(YYYY-MM-DD)와 시각(HH:mm)으로 정확히 파싱.
 * 9시간 역방향 밀림 및 자정 경계 오작동 방지.
 */
function parseUtcToSeoulParts(isoStr: string | null | undefined): { date: string; time: string } {
  if (!isoStr) return { date: "", time: "" };
  if (!isoStr.includes("T")) {
    return { date: isoStr.slice(0, 10), time: "" };
  }
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) {
      const [dPart, tPart = ""] = isoStr.split("T");
      return { date: dPart.slice(0, 10), time: tPart.slice(0, 5) };
    }
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(d);
    const p = (t: string) => parts.find((x) => x.type === t)?.value || "";
    return {
      date: `${p("year")}-${p("month")}-${p("day")}`,
      time: `${p("hour")}:${p("minute")}`,
    };
  } catch {
    const [dPart, tPart = ""] = isoStr.split("T");
    return { date: dPart.slice(0, 10), time: tPart.slice(0, 5) };
  }
}

function formatSeoulTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "";
  return parseUtcToSeoulParts(isoStr).time;
}

// ── 말풍선 컴포넌트 ──────────────────────────────────────

function BotBubble({
  msg,
  onChip,
  onExtract,
}: {
  msg: Message;
  onChip?: (t: string) => void;
  onExtract?: (text: string, url?: string, title?: string) => void;
}) {
  const lines = msg.text.split("\n");
  return (
    <div className="flex items-start gap-2.5 w-full animate-fadein">
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 mt-0.5 shadow-xs"
        style={{ background: "#EFF6FF", border: "1px solid #DBEAFE" }}
      >
        🎓
      </div>
      <div className="flex-1 min-w-0 flex flex-col gap-2">
        {/* 요약 답변 말풍선 */}
        <div
          className="px-4 py-3 rounded-2xl rounded-tl-xs text-[14px] leading-relaxed break-words"
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

          {/* 답변 본문 일정 추출 버튼 */}
          {!msg.isError && (
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex justify-end">
              <button
                onClick={() => onExtract?.(msg.text)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors border border-blue-200 cursor-pointer"
                title="답변 텍스트에서 일정을 추출하여 캘린더 등록 확인"
              >
                <span>📅</span>
                <span>답변에서 일정 추출</span>
              </button>
            </div>
          )}
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

        {/* 공지사항 출처 카드들 */}
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
                  <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-50">
                    {src.url ? (
                      <a
                        href={src.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700"
                      >
                        공지 원문
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
                    ) : <span />}
                    <button
                      onClick={() => {
                        const bodyContent = (src.content || "").trim();
                        if (bodyContent) {
                          onExtract?.(bodyContent, src.url, src.title);
                        } else {
                          const userInput = prompt(
                            `「${src.title}」의 공지 본문 내용이 없습니다.\n일정 추출을 위해 공지 본문 텍스트(접수 기간, 마감 일시 등)를 입력해 주세요:`
                          );
                          if (userInput && userInput.trim()) {
                            onExtract?.(userInput.trim(), src.url, src.title);
                          }
                        }
                      }}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors border border-emerald-200 cursor-pointer"
                    >
                      <span>📅</span>
                      <span>일정 추출</span>
                    </button>
                  </div>
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
        className="px-4 py-3 rounded-2xl rounded-tl-xs flex gap-1.5 items-center shadow-xs"
        style={{ background: "#FFFFFF", border: "1px solid #E2E8F0" }}
      >
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
      </div>
    </div>
  );
}

// ── Zero-Auto-Save 확인 및 캘린더 저장 모달 ──────────────

interface ConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  candidate: ScheduleCandidate | null;
  candidatesList?: ScheduleCandidate[];
  selectedIndex?: number;
  onSelectCandidateIndex?: (idx: number) => void;
  sourceUrl?: string;
  sourceTitle?: string;
  token: string | null;
  onSaveSuccess: () => void;
}

function ScheduleConfirmationModal({
  isOpen,
  onClose,
  candidate,
  candidatesList,
  selectedIndex = 0,
  onSelectCandidateIndex,
  sourceUrl,
  sourceTitle,
  token,
  onSaveSuccess,
}: ConfirmationModalProps) {
  const [title, setTitle] = useState("");
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>("TIME_CONFIRMED_DEADLINE");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [priority, setPriority] = useState<Priority>("MEDIUM");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (candidate) {
      setTitle(candidate.title || "");
      setErrorMsg(null);

      // 일정 종류 매핑 (PERIOD_SCHEDULE 보존 매핑)
      const rawKind = candidate.schedule_kind || "";
      if (rawKind === "ALL_DAY_EVENT") {
        setScheduleKind("ALL_DAY_EVENT");
      } else if (rawKind === "DATE_ONLY_DEADLINE") {
        setScheduleKind("DATE_ONLY_DEADLINE");
      } else if (rawKind === "TIME_CONFIRMED_EVENT") {
        setScheduleKind("TIME_CONFIRMED_EVENT");
      } else if (rawKind === "SINGLE_POINT_APPOINTMENT") {
        setScheduleKind("SINGLE_POINT_APPOINTMENT");
      } else if (rawKind === "PERIOD_SCHEDULE") {
        if (candidate.is_time_confirmed || (candidate.start_datetime && candidate.end_datetime)) {
          setScheduleKind("TIME_CONFIRMED_EVENT");
        } else {
          setScheduleKind("ALL_DAY_EVENT");
        }
      } else if (candidate.is_all_day) {
        setScheduleKind("ALL_DAY_EVENT");
      } else {
        setScheduleKind("TIME_CONFIRMED_DEADLINE");
      }

      // 날짜/시간 파싱 (원문에 없는 임의 날짜/시각 자동 보충 금지, 서울 시각 기준 파싱)
      const rawStart = candidate.start_datetime || candidate.start_date || "";
      const rawEnd = candidate.end_datetime || candidate.end_date || "";

      const sParts = parseUtcToSeoulParts(rawStart);
      const eParts = parseUtcToSeoulParts(rawEnd);

      setStartDate(sParts.date);
      setStartTime(sParts.time);
      setEndDate(eParts.date);
      setEndTime(eParts.time);
    }
  }, [candidate]);

  const isFormValid = useMemo(() => {
    if (!title.trim()) return false;
    if (scheduleKind === "ALL_DAY_EVENT") {
      return Boolean(startDate && endDate);
    }
    if (scheduleKind === "DATE_ONLY_DEADLINE") {
      return Boolean(endDate);
    }
    if (scheduleKind === "TIME_CONFIRMED_DEADLINE") {
      return Boolean(endDate && endTime);
    }
    if (scheduleKind === "TIME_CONFIRMED_EVENT") {
      return Boolean(startDate && startTime && endDate && endTime);
    }
    if (scheduleKind === "SINGLE_POINT_APPOINTMENT") {
      return Boolean(startDate && startTime);
    }
    return false;
  }, [title, scheduleKind, startDate, endDate, startTime, endTime]);

  if (!isOpen || !candidate) return null;

  async function handleConfirmAndSave() {
    if (!token) {
      setErrorMsg("로그인이 필요합니다. 먼저 로그인해 주세요.");
      return;
    }
    if (!title.trim()) {
      setErrorMsg("제목을 입력해 주세요.");
      return;
    }
    if (!isFormValid) {
      setErrorMsg("일정 저장을 위해 필수 날짜/시각을 모두 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      // 5대 유형 계약에 맞게 페이로드 빌드 (is_all_day, is_time_confirmed 제거)
      let payload: Record<string, any> = {
        title: title.trim(),
        schedule_kind: scheduleKind,
        priority: priority,
        timezone: "Asia/Seoul",
        confirmed: true, // Zero-Auto-Save 필수
        source_url: sourceUrl || null,
        source_title: sourceTitle || null,
        extracted_quote: candidate?.source_quote || null,
      };

      if (scheduleKind === "ALL_DAY_EVENT") {
        payload.start_date = startDate;
        payload.end_date = endDate;
        payload.start_datetime = null;
        payload.end_datetime = null;
      } else if (scheduleKind === "DATE_ONLY_DEADLINE") {
        payload.start_date = null;
        payload.end_date = endDate;
        payload.start_datetime = null;
        payload.end_datetime = null;
      } else if (scheduleKind === "TIME_CONFIRMED_DEADLINE") {
        const eTime = endTime.length === 5 ? `${endTime}:00` : endTime;
        payload.start_date = null;
        payload.end_date = endDate;
        payload.start_datetime = null;
        payload.end_datetime = `${endDate}T${eTime}+09:00`;
      } else if (scheduleKind === "TIME_CONFIRMED_EVENT") {
        const sTime = startTime.length === 5 ? `${startTime}:00` : startTime;
        const eTime = endTime.length === 5 ? `${endTime}:00` : endTime;
        payload.start_date = startDate;
        payload.end_date = endDate;
        payload.start_datetime = `${startDate}T${sTime}+09:00`;
        payload.end_datetime = `${endDate}T${eTime}+09:00`;
      } else if (scheduleKind === "SINGLE_POINT_APPOINTMENT") {
        const sTime = startTime.length === 5 ? `${startTime}:00` : startTime;
        payload.start_date = startDate;
        payload.end_date = null;
        payload.start_datetime = `${startDate}T${sTime}+09:00`;
        payload.end_datetime = null;
      }

      const res = await fetch("/api/v1/schedules", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail?.[0]?.msg || data.detail || `저장 실패 (${res.status})`);
      }

      onSaveSuccess();
      onClose();
    } catch (err: any) {
      console.error("일정 확정 저장 오류:", err);
      setErrorMsg(err.message || "일정 저장 중 오류가 발생했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3.5 sm:p-4 bg-slate-900/60 backdrop-blur-xs animate-fadein select-text"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-lg rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2">
            <span className="text-lg">📅</span>
            <div>
              <h2 className="font-bold text-slate-900 text-[14.5px]">일정 후보 확인 및 등록</h2>
              <p className="text-[11px] text-slate-500">
                Zero-Auto-Save: 내용 확인 후 [확인 및 캘린더 저장]을 눌러야 등록됩니다.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer text-sm font-bold"
          >
            ✕
          </button>
        </div>

        {/* 본문 폼 */}
        <div className="flex-1 overflow-y-auto p-5 text-xs text-slate-700 space-y-4 chat-scroll">
          {/* 복수 후보 선택 탭 (F5) */}
          {candidatesList && candidatesList.length > 1 && (
            <div className="bg-slate-100 p-2 rounded-xl flex items-center gap-1.5 overflow-x-auto">
              <span className="text-[11px] font-bold text-slate-500 whitespace-nowrap mr-1">후보 선택:</span>
              {candidatesList.map((c, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectCandidateIndex?.(idx)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${
                    selectedIndex === idx
                      ? "bg-blue-600 text-white shadow-xs"
                      : "bg-white text-slate-700 hover:bg-slate-200 border border-slate-200"
                  }`}
                >
                  후보 {idx + 1}: {c.title || `일정 ${idx + 1}`}
                </button>
              ))}
            </div>
          )}

          {/* 행사 취소 공지 배너 (F5) */}
          {(candidate.is_cancellation || candidate.action === "cancel") && (
            <div className="bg-rose-50 border border-rose-300 rounded-xl p-3 text-rose-900">
              <div className="font-bold text-[12.5px] flex items-center gap-1.5 mb-1 text-rose-700">
                <span>⚠️</span>
                <span>행사 취소 공지</span>
              </div>
              <p className="text-[11.5px] leading-relaxed">
                이 일정은 신규 등록 일정이 아닌 <strong>행사 취소 안내</strong>입니다. 캘린더에 취소 표기 일정으로 등록하시려면 확인 후 저장해 주세요.
              </p>
            </div>
          )}

          {/* 모호성 경고 배너 */}
          {candidate.is_ambiguous && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-amber-900">
              <div className="font-bold text-[12.5px] flex items-center gap-1.5 mb-1">
                <span>⚠️</span>
                <span>모호성 안내 (확인 필요)</span>
              </div>
              <p className="text-[11.5px] leading-relaxed">
                {candidate.ambiguity_reason || "원문에 모호한 일시 표현이 포함되어 있습니다. 필요한 일시를 직접 조정해 주세요."}
              </p>
            </div>
          )}

          {/* 원문 근거 발췌문 */}
          {candidate.source_quote && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-3">
              <span className="text-[11px] font-bold text-slate-500 block mb-1">근거 원문 발췌:</span>
              <p className="text-[12px] italic text-slate-800 bg-white p-2 rounded border border-slate-100">
                "{candidate.source_quote}"
              </p>
            </div>
          )}

          {/* 에러 메시지 */}
          {errorMsg && (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-2.5 rounded-xl text-xs font-medium">
              ⚠️ {errorMsg}
            </div>
          )}

          {/* 제목 입력 */}
          <div>
            <label className="block text-[12px] font-bold text-slate-800 mb-1">
              일정 제목 <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-[13px] outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="예: 과제 제출 마감"
            />
          </div>

          {/* 일정 유형 및 우선순위 */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-bold text-slate-800 mb-1">일정 유형</label>
              <select
                value={scheduleKind}
                onChange={(e) => setScheduleKind(e.target.value as ScheduleKind)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none bg-white"
              >
                <option value="TIME_CONFIRMED_DEADLINE">마감 (시간 포함)</option>
                <option value="DATE_ONLY_DEADLINE">마감 (날짜 전용)</option>
                <option value="ALL_DAY_EVENT">종일 행사 / 기간</option>
                <option value="TIME_CONFIRMED_EVENT">기간 행사 (시각 포함)</option>
                <option value="SINGLE_POINT_APPOINTMENT">단일 시각 약속</option>
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-bold text-slate-800 mb-1">중요도</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as Priority)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none bg-white"
              >
                <option value="HIGH">🔴 높음 (HIGH)</option>
                <option value="MEDIUM">🔵 보통 (MEDIUM)</option>
                <option value="LOW">⚪ 낮음 (LOW)</option>
              </select>
            </div>
          </div>

          {/* 날짜 및 시간 입력 (유형별) */}
          <div className="space-y-3 pt-1">
            {scheduleKind === "TIME_CONFIRMED_DEADLINE" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 날짜</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 시각</label>
                  <input
                    type="time"
                    value={endTime}
                    onChange={(e) => setEndTime(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}

            {scheduleKind === "DATE_ONLY_DEADLINE" && (
              <div>
                <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 날짜</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                />
              </div>
            )}

            {scheduleKind === "ALL_DAY_EVENT" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 날짜</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 날짜</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}

            {scheduleKind === "TIME_CONFIRMED_EVENT" && (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 날짜</label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 시각</label>
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 날짜</label>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 시각</label>
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                </div>
              </div>
            )}

            {scheduleKind === "SINGLE_POINT_APPOINTMENT" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">약속 날짜</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">약속 시각</label>
                  <input
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 필수값 미입력 안내 */}
        {!isFormValid && (
          <div className="px-5 py-2.5 bg-amber-50 border-t border-amber-200 text-amber-800 text-[11.5px] font-medium flex items-center gap-1.5">
            <span>ℹ️</span>
            <span>필수 항목(제목, 일시)을 모두 입력해야 캘린더 저장이 활성화됩니다.</span>
          </div>
        )}

        {/* 하단 버튼 액션바 */}
        <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-2.5">
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2 text-xs font-semibold rounded-xl text-slate-600 hover:bg-slate-200 transition-colors cursor-pointer"
          >
            취소
          </button>
          <button
            onClick={handleConfirmAndSave}
            disabled={isSubmitting || !isFormValid}
            className="px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition-all shadow-xs disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1.5"
          >
            {isSubmitting ? (
              <>
                <span className="inline-block animate-spin">⏳</span>
                <span>확인 및 저장 중...</span>
              </>
            ) : (
              <>
                <span>✓</span>
                <span>확인 및 캘린더 저장</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 계정 로그인/회원가입 모달 ──────────────────────────────

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLoginSuccess: (token: string, username: string) => void;
}

function AuthModal({ isOpen, onClose, onLoginSuccess }: AuthModalProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErrorMsg(null);

    try {
      const endpoint = isRegister ? "/api/v1/auth/register" : "/api/v1/auth/login";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail?.[0]?.msg || data.detail || "인증 요청에 실패했습니다.");
      }

      if (isRegister) {
        // 회원가입 성공 시 바로 로그인 수행
        const loginRes = await fetch("/api/v1/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
        const loginData = await loginRes.json();
        onLoginSuccess(loginData.access_token, username);
      } else {
        const data = await res.json();
        onLoginSuccess(data.access_token, username);
      }
      onClose();
    } catch (err: any) {
      setErrorMsg(err.message || "오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-fadein"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-sm rounded-2xl shadow-2xl border border-slate-200 p-6 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-bold text-slate-900">
            {isRegister ? "회원가입" : "로그인"}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-sm font-bold"
          >
            ✕
          </button>
        </div>

        {errorMsg && (
          <div className="bg-rose-50 text-rose-700 p-2.5 rounded-lg text-xs font-medium mb-3">
            ⚠️ {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">아이디</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none focus:border-blue-500"
              placeholder="영문, 숫자 3~50자"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">비밀번호</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none focus:border-blue-500"
              placeholder="8자 이상"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-xs transition-colors cursor-pointer mt-2"
          >
            {loading ? "처리 중..." : isRegister ? "회원가입 및 시작" : "로그인"}
          </button>
        </form>

        <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="text-blue-600 hover:underline cursor-pointer"
          >
            {isRegister ? "이미 계정이 있으신가요? 로그인" : "계정이 없으신가요? 회원가입"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 일정 내용 수정 모달 (F6: PATCH 지원) ───────────────────

interface ScheduleEditModalProps {
  isOpen: boolean;
  schedule: ScheduleItem | null;
  token: string | null;
  onClose: () => void;
  onSaveSuccess?: () => void;
  onEditSuccess?: () => void;
}

function ScheduleEditModal({
  isOpen,
  schedule,
  token,
  onClose,
  onSaveSuccess,
  onEditSuccess,
}: ScheduleEditModalProps) {
  const sPartsInit = parseUtcToSeoulParts(schedule?.start_datetime || schedule?.start_date || "");
  const ePartsInit = parseUtcToSeoulParts(schedule?.end_datetime || schedule?.end_date || "");

  const [title, setTitle] = useState(() => schedule?.title || "");
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>(() => schedule?.schedule_kind || "TIME_CONFIRMED_DEADLINE");
  const [startDate, setStartDate] = useState(() => sPartsInit.date);
  const [endDate, setEndDate] = useState(() => ePartsInit.date);
  const [startTime, setStartTime] = useState(() => sPartsInit.time);
  const [endTime, setEndTime] = useState(() => ePartsInit.time);
  const [priority, setPriority] = useState<Priority>(() => schedule?.priority || "MEDIUM");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // 초기값 추적 상태: 사용자가 변경하지 않은 필드는 PATCH 페이로드에서 제외하여
  // DB에 저장된 UTC 타임스탬프와 초·마이크로초(.123456) 정밀도를 완전히 보존함.
  const [initialKind, setInitialKind] = useState<ScheduleKind>(() => schedule?.schedule_kind || "TIME_CONFIRMED_DEADLINE");
  const [initialStartDate, setInitialStartDate] = useState(() => sPartsInit.date);
  const [initialEndDate, setInitialEndDate] = useState(() => ePartsInit.date);
  const [initialStartTime, setInitialStartTime] = useState(() => sPartsInit.time);
  const [initialEndTime, setInitialEndTime] = useState(() => ePartsInit.time);

  useEffect(() => {
    if (schedule && isOpen) {
      setTitle(schedule.title || "");
      setScheduleKind(schedule.schedule_kind);
      setInitialKind(schedule.schedule_kind);
      setPriority(schedule.priority || "MEDIUM");
      setErrorMsg(null);

      const rawStart = schedule.start_datetime || schedule.start_date || "";
      const rawEnd = schedule.end_datetime || schedule.end_date || "";

      const sParts = parseUtcToSeoulParts(rawStart);
      const eParts = parseUtcToSeoulParts(rawEnd);

      setStartDate(sParts.date);
      setStartTime(sParts.time);
      setEndDate(eParts.date);
      setEndTime(eParts.time);

      setInitialStartDate(sParts.date);
      setInitialStartTime(sParts.time);
      setInitialEndDate(eParts.date);
      setInitialEndTime(eParts.time);
    }
  }, [schedule, isOpen]);

  if (!isOpen || !schedule) return null;

  async function handleSaveEdit() {
    if (!token || !schedule) return;
    if (!title.trim()) {
      setErrorMsg("제목을 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const isKindModified = scheduleKind !== initialKind;
      const isStartModified = startDate !== initialStartDate || startTime !== initialStartTime;
      const isEndModified = endDate !== initialEndDate || endTime !== initialEndTime;

      let patchPayload: Record<string, any> = {
        confirmed: true,
        title: title.trim(),
      };

      if (priority !== schedule.priority) {
        patchPayload.priority = priority;
      }

      const formatTime = (t: string) => (t.length === 5 ? `${t}:00` : t);

      // Defect C: 유형 또는 시작/종료 일시 변경 시 필요한 필드만 정밀하게 포함.
      // 1) 유형(Kind)이 변경된 경우: 새 유형에 맞추어 모든 필수 필드를 설정하고 무관한 필드는 명시적 null 처리
      if (isKindModified) {
        patchPayload.schedule_kind = scheduleKind;

        if (scheduleKind === "ALL_DAY_EVENT") {
          patchPayload.start_date = startDate || null;
          patchPayload.end_date = endDate || startDate || null;
          patchPayload.start_datetime = null;
          patchPayload.end_datetime = null;
        } else if (scheduleKind === "DATE_ONLY_DEADLINE") {
          patchPayload.start_date = null;
          patchPayload.end_date = endDate || null;
          patchPayload.start_datetime = null;
          patchPayload.end_datetime = null;
        } else if (scheduleKind === "TIME_CONFIRMED_DEADLINE") {
          patchPayload.start_date = null;
          patchPayload.end_date = endDate || null;
          patchPayload.start_datetime = null;
          patchPayload.end_datetime =
            endDate && endTime ? `${endDate}T${formatTime(endTime)}+09:00` : null;
        } else if (scheduleKind === "TIME_CONFIRMED_EVENT") {
          patchPayload.start_date = startDate || null;
          patchPayload.end_date = endDate || startDate || null;
          patchPayload.start_datetime =
            startDate && startTime ? `${startDate}T${formatTime(startTime)}+09:00` : null;
          patchPayload.end_datetime =
            endDate && endTime ? `${endDate}T${formatTime(endTime)}+09:00` : null;
        } else if (scheduleKind === "SINGLE_POINT_APPOINTMENT") {
          patchPayload.start_date = startDate || null;
          patchPayload.end_date = null;
          patchPayload.start_datetime =
            startDate && startTime ? `${startDate}T${formatTime(startTime)}+09:00` : null;
          patchPayload.end_datetime = null;
        }
      } else {
        // 2) 유형이 동일한 경우: 사용자가 수정한 start 또는 end 필드만 선택적으로 포함.
        // 수정하지 않은 쪽은 PATCH payload에서 완전히 OMIT하여 DB의 UTC 문자열 및 마이크로초 정밀도(.123456)를 byte-for-byte 보존.
        if (scheduleKind === "TIME_CONFIRMED_EVENT") {
          if (isStartModified) {
            patchPayload.start_date = startDate || null;
            patchPayload.start_datetime =
              startDate && startTime ? `${startDate}T${formatTime(startTime)}+09:00` : null;
          }
          if (isEndModified) {
            patchPayload.end_date = endDate || null;
            patchPayload.end_datetime =
              endDate && endTime ? `${endDate}T${formatTime(endTime)}+09:00` : null;
          }
        } else if (scheduleKind === "TIME_CONFIRMED_DEADLINE") {
          if (isEndModified) {
            patchPayload.end_date = endDate || null;
            patchPayload.end_datetime =
              endDate && endTime ? `${endDate}T${formatTime(endTime)}+09:00` : null;
          }
        } else if (scheduleKind === "DATE_ONLY_DEADLINE") {
          if (isEndModified) {
            patchPayload.end_date = endDate || null;
          }
        } else if (scheduleKind === "ALL_DAY_EVENT") {
          if (isStartModified) {
            patchPayload.start_date = startDate || null;
          }
          if (isEndModified) {
            patchPayload.end_date = endDate || null;
          }
        } else if (scheduleKind === "SINGLE_POINT_APPOINTMENT") {
          if (isStartModified) {
            patchPayload.start_date = startDate || null;
            patchPayload.start_datetime =
              startDate && startTime ? `${startDate}T${formatTime(startTime)}+09:00` : null;
          }
        }
      }

      const res = await fetch(`/api/v1/schedules/${schedule.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(patchPayload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail?.[0]?.msg || data.detail || `수정 실패 (${res.status})`);
      }

      (onSaveSuccess || onEditSuccess)?.();
    } catch (err: any) {
      console.error("일정 수정 오류:", err);
      setErrorMsg(err.message || "일정 수정 중 오류가 발생했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3.5 sm:p-4 bg-slate-900/60 backdrop-blur-xs animate-fadein select-text"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-lg rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2">
            <span className="text-lg">✏️</span>
            <div>
              <h2 className="font-bold text-slate-900 text-[14.5px]">일정 내용 수정</h2>
              <p className="text-[11px] text-slate-500">일정의 제목, 일시, 중요도를 변경합니다.</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer text-sm font-bold"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 text-xs text-slate-700 space-y-4 chat-scroll">
          {errorMsg && (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-2.5 rounded-xl text-xs font-medium">
              ⚠️ {errorMsg}
            </div>
          )}

          <div>
            <label className="block text-[12px] font-bold text-slate-800 mb-1">
              일정 제목 <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-[13px] outline-none focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-bold text-slate-800 mb-1">일정 유형</label>
              <select
                value={scheduleKind}
                onChange={(e) => setScheduleKind(e.target.value as ScheduleKind)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none bg-white"
              >
                <option value="TIME_CONFIRMED_DEADLINE">마감 (시간 포함)</option>
                <option value="DATE_ONLY_DEADLINE">마감 (날짜 전용)</option>
                <option value="ALL_DAY_EVENT">종일 행사 / 기간</option>
                <option value="TIME_CONFIRMED_EVENT">기간 행사 (시각 포함)</option>
                <option value="SINGLE_POINT_APPOINTMENT">단일 시각 약속</option>
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-bold text-slate-800 mb-1">중요도</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as Priority)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-xs outline-none bg-white"
              >
                <option value="HIGH">🔴 높음 (HIGH)</option>
                <option value="MEDIUM">🔵 보통 (MEDIUM)</option>
                <option value="LOW">⚪ 낮음 (LOW)</option>
              </select>
            </div>
          </div>

          <div className="space-y-3 pt-1">
            {scheduleKind === "TIME_CONFIRMED_DEADLINE" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 날짜</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 시각</label>
                  <input
                    type="time"
                    value={endTime}
                    onChange={(e) => setEndTime(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}

            {scheduleKind === "DATE_ONLY_DEADLINE" && (
              <div>
                <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">마감 날짜</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                />
              </div>
            )}

            {scheduleKind === "ALL_DAY_EVENT" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 날짜</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 날짜</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}

            {scheduleKind === "TIME_CONFIRMED_EVENT" && (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 날짜</label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">시작 시각</label>
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 날짜</label>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">종료 시각</label>
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                    />
                  </div>
                </div>
              </div>
            )}

            {scheduleKind === "SINGLE_POINT_APPOINTMENT" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">약속 날짜</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] font-semibold text-slate-700 mb-1">약속 시각</label>
                  <input
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-2.5">
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2 text-xs font-semibold rounded-xl text-slate-600 hover:bg-slate-200 transition-colors cursor-pointer"
          >
            취소
          </button>
          <button
            onClick={handleSaveEdit}
            disabled={isSubmitting || !title.trim()}
            className="px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition-all shadow-xs disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
          >
            {isSubmitting ? "수정 중..." : "수정 완료"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 캘린더 및 일정 관리 뷰 ──────────────────────────────────

interface CalendarViewProps {
  token: string | null;
  schedules: ScheduleItem[];
  onRefresh: () => void;
  onOpenCreateModal: () => void;
}

function CalendarView({ token, schedules, onRefresh, onOpenCreateModal }: CalendarViewProps) {
  const [currentDate, setCurrentDate] = useState(() => {
    const [y, m, d] = getTodaySeoul().split("-").map(Number);
    return new Date(y, m - 1, d);
  });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<"ALL" | "INCOMPLETE" | "COMPLETED">("ALL");
  const [editingSchedule, setEditingSchedule] = useState<ScheduleItem | null>(null);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();
  const todaySeoul = getTodaySeoul();

  // 월간 날짜 그리드 계산
  const { daysInMonth, startDayOfWeek } = useMemo(() => {
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    return {
      daysInMonth: lastDay.getDate(),
      startDayOfWeek: firstDay.getDay(), // 0: 일, 1: 월 ...
    };
  }, [year, month]);

  // 날짜별 일정 매핑 (다일 기간 일정 포함)
  const schedulesByDate = useMemo(() => {
    const map = new Map<string, ScheduleItem[]>();
    for (const s of schedules) {
      const start = s.start_date ? s.start_date.slice(0, 10) : null;
      const end = s.end_date ? s.end_date.slice(0, 10) : null;

      if (start && end && start <= end) {
        // 다일 기간 일정: 시작일부터 종료일까지 매핑
        const [sY, sM, sD] = start.split("-").map(Number);
        const [eY, eM, eD] = end.split("-").map(Number);
        const cur = new Date(sY, sM - 1, sD);
        const last = new Date(eY, eM - 1, eD);
        let safety = 0;
        while (cur <= last && safety < 120) {
          const y = cur.getFullYear();
          const m = String(cur.getMonth() + 1).padStart(2, "0");
          const d = String(cur.getDate()).padStart(2, "0");
          const dateKey = `${y}-${m}-${d}`;
          const list = map.get(dateKey) || [];
          if (!list.some((item) => item.id === s.id)) {
            list.push(s);
            map.set(dateKey, list);
          }
          cur.setDate(cur.getDate() + 1);
          safety++;
        }
      } else {
        const singleDate = (end || start || "").slice(0, 10);
        if (singleDate) {
          const list = map.get(singleDate) || [];
          if (!list.some((item) => item.id === s.id)) {
            list.push(s);
            map.set(singleDate, list);
          }
        }
      }
    }
    return map;
  }, [schedules]);

  // 필터링된 일정 목록
  const displayedSchedules = useMemo(() => {
    return schedules.filter((s) => {
      // 날짜 필터 (다일 기간 일정도 선택 날짜에 걸치면 표시)
      if (selectedDate) {
        const start = s.start_date ? s.start_date.slice(0, 10) : null;
        const end = s.end_date ? s.end_date.slice(0, 10) : null;
        if (start && end && start <= end) {
          if (selectedDate < start || selectedDate > end) return false;
        } else {
          const single = (end || start || "").slice(0, 10);
          if (single !== selectedDate) return false;
        }
      }
      // 완료 상태 필터
      if (filterType === "INCOMPLETE" && s.is_completed) return false;
      if (filterType === "COMPLETED" && !s.is_completed) return false;
      return true;
    });
  }, [schedules, selectedDate, filterType]);

  // 완료 토글
  async function handleToggleCompleted(s: ScheduleItem) {
    if (!token) return;
    try {
      await fetch(`/api/v1/schedules/${s.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          is_completed: !s.is_completed,
          confirmed: true,
        }),
      });
      onRefresh();
    } catch (err) {
      console.error("완료 상태 변경 실패:", err);
    }
  }

  // 삭제
  async function handleDelete(s: ScheduleItem) {
    if (!token) return;
    if (!window.confirm(`'${s.title}' 일정을 삭제하시겠습니까?`)) return;

    try {
      await fetch(`/api/v1/schedules/${s.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      onRefresh();
    } catch (err) {
      console.error("삭제 실패:", err);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 select-text">
      {/* 캘린더 네비게이션 헤더 */}
      <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-xs">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="font-bold text-slate-900 text-base">
              {year}년 {month + 1}월
            </h2>
            <button
              onClick={() => setSelectedDate(null)}
              className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors cursor-pointer"
            >
              전체 보기
            </button>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentDate(new Date(year, month - 1, 1))}
              className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-slate-100 text-slate-600 cursor-pointer"
            >
              ‹
            </button>
            <button
              onClick={() => {
                const [y, m, d] = todaySeoul.split("-").map(Number);
                setCurrentDate(new Date(y, m - 1, d));
                setSelectedDate(todaySeoul);
              }}
              className="px-2 py-1 text-xs font-semibold rounded-lg hover:bg-slate-100 text-slate-700 cursor-pointer"
            >
              오늘
            </button>
            <button
              onClick={() => setCurrentDate(new Date(year, month + 1, 1))}
              className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-slate-100 text-slate-600 cursor-pointer"
            >
              ›
            </button>
          </div>
        </div>

        {/* 요일 헤더 */}
        <div className="grid grid-cols-7 text-center text-[11px] font-bold text-slate-400 mb-1">
          <span className="text-rose-500">일</span>
          <span>월</span>
          <span>화</span>
          <span>수</span>
          <span>목</span>
          <span>금</span>
          <span className="text-blue-500">토</span>
        </div>

        {/* 날짜 그리드 */}
        <div className="grid grid-cols-7 gap-1 text-center text-xs">
          {Array.from({ length: startDayOfWeek }).map((_, i) => (
            <div key={`empty-${i}`} className="h-8" />
          ))}

          {Array.from({ length: daysInMonth }).map((_, i) => {
            const dayNum = i + 1;
            const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
            const isSelected = selectedDate === dateStr;
            const daySchedules = schedulesByDate.get(dateStr) || [];
            const hasSchedules = daySchedules.length > 0;
            const isToday = dateStr === todaySeoul;

            return (
              <button
                key={dayNum}
                onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                className={`h-9 rounded-xl flex flex-col items-center justify-center relative transition-all cursor-pointer ${
                  isSelected
                    ? "bg-blue-600 text-white font-bold shadow-xs"
                    : isToday
                    ? "bg-blue-50 text-blue-700 font-bold border border-blue-200"
                    : "hover:bg-slate-100 text-slate-800"
                }`}
              >
                <span>{dayNum}</span>
                {hasSchedules && (
                  <span
                    className={`w-1.5 h-1.5 rounded-full mt-0.5 ${
                      isSelected ? "bg-white" : "bg-blue-600"
                    }`}
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 일정 목록 상단 액션바 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1 bg-slate-200/70 p-0.5 rounded-xl text-xs font-semibold">
          <button
            onClick={() => setFilterType("ALL")}
            className={`px-3 py-1 rounded-lg transition-all cursor-pointer ${
              filterType === "ALL" ? "bg-white text-slate-900 shadow-xs" : "text-slate-600"
            }`}
          >
            전체 ({schedules.length})
          </button>
          <button
            onClick={() => setFilterType("INCOMPLETE")}
            className={`px-3 py-1 rounded-lg transition-all cursor-pointer ${
              filterType === "INCOMPLETE" ? "bg-white text-slate-900 shadow-xs" : "text-slate-600"
            }`}
          >
            미완료
          </button>
          <button
            onClick={() => setFilterType("COMPLETED")}
            className={`px-3 py-1 rounded-lg transition-all cursor-pointer ${
              filterType === "COMPLETED" ? "bg-white text-slate-900 shadow-xs" : "text-slate-600"
            }`}
          >
            완료
          </button>
        </div>

        <button
          onClick={onOpenCreateModal}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-600 text-white font-bold text-xs hover:bg-blue-700 transition-colors shadow-xs cursor-pointer"
        >
          <span>➕</span>
          <span>새 일정</span>
        </button>
      </div>

      {/* 일정 카드 목록 */}
      <div className="flex flex-col gap-2.5">
        {displayedSchedules.length === 0 ? (
          <div className="bg-white rounded-2xl p-8 text-center text-slate-400 border border-slate-200">
            <span className="text-3xl block mb-2">📋</span>
            <p className="text-xs font-medium">등록된 일정이 없습니다.</p>
            <p className="text-[11px] text-slate-400 mt-1">
              챗봇 공지에서 [📅 일정 추출]을 누르거나 직접 등록해 보세요.
            </p>
          </div>
        ) : (
          displayedSchedules.map((s) => {
            const dday = calculateDDay(s.end_date || s.start_date);
            return (
              <div
                key={s.id}
                className={`bg-white rounded-2xl p-4 border transition-all shadow-xs flex items-start gap-3 ${
                  s.is_completed ? "border-slate-200 opacity-60" : "border-slate-200 hover:border-blue-300"
                }`}
              >
                {/* 완료 체크박스 */}
                <input
                  type="checkbox"
                  checked={s.is_completed}
                  onChange={() => handleToggleCompleted(s)}
                  className="w-4 h-4 rounded mt-0.5 text-blue-600 cursor-pointer accent-blue-600"
                />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        s.priority === "HIGH"
                          ? "bg-rose-100 text-rose-700"
                          : s.priority === "MEDIUM"
                          ? "bg-blue-100 text-blue-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {s.priority}
                    </span>

                    {dday && !s.is_completed && (
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          dday.isUrgent
                            ? "bg-amber-100 text-amber-800 animate-pulse"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {dday.text}
                      </span>
                    )}

                    <span className="text-[11px] text-slate-400">
                      {s.schedule_kind === "TIME_CONFIRMED_DEADLINE"
                        ? "마감"
                        : s.schedule_kind === "DATE_ONLY_DEADLINE"
                        ? "날짜마감"
                        : s.schedule_kind === "ALL_DAY_EVENT"
                        ? "종일"
                        : s.schedule_kind === "TIME_CONFIRMED_EVENT"
                        ? "기간"
                        : "약속"}
                    </span>
                  </div>

                  <h3
                    className={`font-bold text-[13.5px] leading-snug mb-1 text-slate-900 break-words ${
                      s.is_completed ? "line-through text-slate-400" : ""
                    }`}
                  >
                    {s.title}
                  </h3>

                  <p className="text-[11.5px] text-slate-500 flex items-center gap-1.5">
                    <span>🕒</span>
                    <span>
                      {s.start_date || ""}
                      {s.start_datetime ? ` ${formatSeoulTime(s.start_datetime)}` : ""}
                      {s.end_date ? ` ~ ${s.end_date}` : ""}
                      {s.end_datetime ? ` ${formatSeoulTime(s.end_datetime)}` : ""}
                    </span>
                  </p>

                  {s.extracted_quote && (
                    <p className="text-[11px] text-slate-400 bg-slate-50 p-2 rounded-lg mt-2 italic">
                      "{s.extracted_quote}"
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setEditingSchedule(s)}
                    className="text-slate-400 hover:text-blue-600 p-1 rounded-lg transition-colors cursor-pointer text-sm"
                    title="일정 수정"
                  >
                    ✏️
                  </button>
                  <button
                    onClick={() => handleDelete(s)}
                    className="text-slate-300 hover:text-rose-600 p-1 rounded-lg transition-colors cursor-pointer text-sm"
                    title="일정 삭제"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 일정 수정 모달 */}
      {editingSchedule && (
        <ScheduleEditModal
          isOpen={true}
          onClose={() => setEditingSchedule(null)}
          schedule={editingSchedule}
          token={token}
          onSaveSuccess={() => {
            setEditingSchedule(null);
            onRefresh();
          }}
        />
      )}
    </div>
  );
}

// ── 메인 App 컴포넌트 ───────────────────────────────────

export default function App() {
  const [viewTab, setViewTab] = useState<"chat" | "calendar">("chat");
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);

  // 계정 세션 상태
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("campusmate_token"));
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem("campusmate_username"));

  // 일정 목록 상태
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);

  // Zero-Auto-Save 모달 상태
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [candidatesList, setCandidatesList] = useState<ScheduleCandidate[]>([]);
  const [selectedCandidateIndex, setSelectedCandidateIndex] = useState(0);
  const [candidateSourceUrl, setCandidateSourceUrl] = useState<string | undefined>();
  const [candidateSourceTitle, setCandidateSourceTitle] = useState<string | undefined>();

  const currentCandidate = candidatesList[selectedCandidateIndex] || null;

  const bottomRef = useRef<HTMLDivElement>(null);

  // 세션 복원 및 탭 전환 시 일정 로드
  useEffect(() => {
    if (token) {
      loadSchedules(token);
    }
  }, [token, viewTab]);

  useEffect(() => {
    const handleRefresh = () => {
      if (token) loadSchedules(token);
    };
    window.addEventListener("refresh-schedules", handleRefresh);
    return () => window.removeEventListener("refresh-schedules", handleRefresh);
  }, [token]);

  // 대화 스크롤
  useEffect(() => {
    if (viewTab === "chat") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, typing, viewTab]);

  async function loadSchedules(authToken: string) {
    try {
      let allItems: ScheduleItem[] = [];
      let offset = 0;
      const limit = 50;
      let total = 0;

      do {
        const res = await fetch(`/api/v1/schedules?offset=${offset}&limit=${limit}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (res.status === 401) {
          handleLogout();
          return;
        }
        if (!res.ok) {
          break;
        }
        const data = await res.json();
        const items: ScheduleItem[] = data.items || [];
        allItems = allItems.concat(items);
        total = data.total || 0;
        offset += items.length;
        if (items.length === 0) break;
      } while (offset < total);

      setSchedules(allItems);
    } catch (err) {
      console.error("일정 목록 로드 실패:", err);
    }
  }

  function handleLoginSuccess(newToken: string, newUsername: string) {
    setToken(newToken);
    setUsername(newUsername);
    localStorage.setItem("campusmate_token", newToken);
    localStorage.setItem("campusmate_username", newUsername);
    loadSchedules(newToken);
  }

  async function handleLogout() {
    if (token) {
      try {
        await fetch("/api/v1/auth/logout", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch (err) {
        console.error("서버 로그아웃 호출 실패:", err);
      }
    }
    setToken(null);
    setUsername(null);
    localStorage.removeItem("campusmate_token");
    localStorage.removeItem("campusmate_username");
    setSchedules([]);
  }

  // 브라우저 Notification 권한 및 마감 알림
  const urgentCount = useMemo(() => {
    return schedules.filter((s) => {
      if (s.is_completed) return false;
      const dday = calculateDDay(s.end_date || s.start_date);
      return dday?.isUrgent;
    }).length;
  }, [schedules]);

  async function requestNotificationPermission() {
    if ("Notification" in window) {
      const perm = await Notification.requestPermission();
      if (perm === "granted" && urgentCount > 0) {
        new Notification("CampusMate 마감 알림", {
          body: `오늘 또는 3일 이내 마감되는 일정이 ${urgentCount}건 있습니다.`,
          icon: "/favicon.ico",
        });
      }
    }
  }

  // 일정 추출 핸들러 (Zero-Auto-Save 트리거)
  async function handleExtractSchedule(text: string, url?: string, title?: string) {
    if (!token) {
      setShowAuthModal(true);
      return;
    }

    try {
      const res = await fetch("/api/v1/schedules/extract", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          text: text.trim(),
          source_url: url || null,
          source_title: title || null,
        }),
      });

      if (res.status === 401) {
        handleLogout();
        setShowAuthModal(true);
        return;
      }

      if (!res.ok) {
        throw new Error(`일정 추출 실패 (${res.status})`);
      }

      const data = await res.json();
      if (!data.candidates || data.candidates.length === 0) {
        alert("선택하신 텍스트/공지에서 추출 가능한 일정 정보를 찾지 못했습니다.");
        return;
      }

      // 후보 목록 설정 및 모달 오픈 (Zero-Auto-Save 확인 단계)
      setCandidatesList(data.candidates);
      setSelectedCandidateIndex(0);
      setCandidateSourceUrl(url);
      setCandidateSourceTitle(title);
      setConfirmModalOpen(true);
    } catch (err: any) {
      console.error("추출 오류:", err);
      alert(err.message || "일정 추출 중 오류가 발생했습니다.");
    }
  }

  // 챗봇 질의 전송
  async function send(text: string) {
    if (!text.trim() || typing) return;

    const userMsg: Message = {
      id: Date.now(),
      role: "user",
      text: text.trim(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setTyping(true);

    try {
      const resp = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text.trim(), top_k: 3 }),
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
        content: s.content || "",
      }));

      const botMsg: Message = {
        id: Date.now() + 1,
        role: "bot",
        text: botAnswer,
        sources: mappedSources,
        isError: data.status === "api_error",
      };

      setMessages((prev) => [...prev, botMsg]);
    } catch (err: any) {
      console.error("질의 요청 실패:", err);
      const fallbackMsg: Message = {
        id: Date.now() + 1,
        role: "bot",
        text: "⚠️ 백엔드 서버(FastAPI)와 통신할 수 없습니다. 서버가 정상 기동 중인지 확인해 주세요.",
        isError: true,
      };
      setMessages((prev) => [...prev, fallbackMsg]);
    } finally {
      setTyping(false);
    }
  }

  return (
    <div className="flex flex-col w-full h-[100dvh] max-w-full overflow-hidden bg-slate-50 select-none">
      {/* 상단 통합 헤더 */}
      <header
        className="flex items-center justify-between px-4 py-3 flex-shrink-0 z-10 bg-white border-b border-slate-200"
        style={{ paddingTop: "max(10px, env(safe-area-inset-top))" }}
      >
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight text-slate-900">CampusMate</span>
          <span className="text-base">🎓</span>

          {/* 뷰 전환 탭 */}
          <div className="flex items-center bg-slate-100 p-0.5 rounded-xl ml-2 text-xs font-bold">
            <button
              onClick={() => setViewTab("chat")}
              className={`px-2.5 py-1 rounded-lg transition-all cursor-pointer ${
                viewTab === "chat" ? "bg-white text-blue-600 shadow-xs" : "text-slate-500"
              }`}
            >
              💬 챗봇
            </button>
            <button
              onClick={() => setViewTab("calendar")}
              className={`px-2.5 py-1 rounded-lg transition-all cursor-pointer flex items-center gap-1 ${
                viewTab === "calendar" ? "bg-white text-blue-600 shadow-xs" : "text-slate-500"
              }`}
            >
              <span>📅 캘린더</span>
              {urgentCount > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
              )}
            </button>
          </div>
        </div>

        {/* 계정 및 유틸 액션바 */}
        <div className="flex items-center gap-1.5">
          {token && username ? (
            <div className="flex items-center gap-1.5 text-xs text-slate-600 bg-slate-50 px-2 py-1 rounded-lg border border-slate-200">
              <span className="font-semibold text-slate-800">{username}</span>
              <button
                onClick={handleLogout}
                className="text-[11px] text-slate-400 hover:text-rose-600 cursor-pointer"
                title="로그아웃"
              >
                로그아웃
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowAuthModal(true)}
              className="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold transition-colors cursor-pointer"
            >
              로그인
            </button>
          )}

          <button
            onClick={() => setShowInfoModal(true)}
            className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-slate-100 text-slate-600 text-[14px] cursor-pointer"
            title="정보 및 라이선스 고지"
          >
            ⚖️
          </button>
          {viewTab === "chat" && (
            <button
              onClick={() => {
                setMessages(INITIAL_MESSAGES);
                setInput("");
              }}
              className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-slate-100 text-slate-500 cursor-pointer"
              title="대화 초기화"
            >
              🔄
            </button>
          )}
        </div>
      </header>

      {/* 마감 임박 알림 배너 */}
      {urgentCount > 0 && (
        <div className="bg-amber-500 text-white px-4 py-2 text-xs font-bold flex items-center justify-between shadow-xs animate-fadein">
          <div
            onClick={() => setViewTab("calendar")}
            className="flex items-center gap-1.5 cursor-pointer hover:underline"
          >
            <span>🚨</span>
            <span>마감 임박 일정 ({urgentCount}건) 확인하기</span>
          </div>
          <button
            onClick={requestNotificationPermission}
            className="text-[11px] bg-white/20 hover:bg-white/30 px-2 py-0.5 rounded transition-colors cursor-pointer"
          >
            🔔 알림 켜기
          </button>
        </div>
      )}

      {/* 뷰 전환 렌더링 */}
      {viewTab === "chat" ? (
        <>
          {/* 대화 메시지 영역 */}
          <main className="flex-1 overflow-y-auto chat-scroll px-4 py-4 flex flex-col gap-3.5 select-text">
            {messages.map((msg) =>
              msg.role === "bot" ? (
                <BotBubble
                  key={msg.id}
                  msg={msg}
                  onChip={send}
                  onExtract={handleExtractSchedule}
                />
              ) : (
                <div key={msg.id} className="flex justify-end w-full animate-fadein">
                  <div
                    className="px-4 py-2.5 rounded-2xl rounded-tr-xs text-[14px] leading-relaxed text-white font-medium max-w-[80%] break-words"
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

          {/* 하단 입력창 */}
          <footer
            className="px-4 py-3 flex-shrink-0 z-10 bg-white border-t border-slate-200"
            style={{ paddingBottom: "max(12px, env(safe-area-inset-bottom))" }}
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
                placeholder="학사, 장학, 행사 공지에 대해 질문하세요..."
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
        </>
      ) : (
        <CalendarView
          token={token}
          schedules={schedules}
          onRefresh={() => token && loadSchedules(token)}
          onOpenCreateModal={() => {
            setCandidatesList([
              {
                title: "",
                schedule_kind: "TIME_CONFIRMED_EVENT",
                unconfirmed_fields: [],
                is_ambiguous: false,
                requires_user_confirmation: true,
                source_quote: "",
              },
            ]);
            setSelectedCandidateIndex(0);
            setCandidateSourceUrl(undefined);
            setCandidateSourceTitle(undefined);
            setConfirmModalOpen(true);
          }}
        />
      )}

      {/* Zero-Auto-Save 확인 모달 */}
      <ScheduleConfirmationModal
        isOpen={confirmModalOpen}
        onClose={() => setConfirmModalOpen(false)}
        candidate={currentCandidate}
        candidatesList={candidatesList}
        selectedIndex={selectedCandidateIndex}
        onSelectCandidateIndex={setSelectedCandidateIndex}
        sourceUrl={candidateSourceUrl}
        sourceTitle={candidateSourceTitle}
        token={token}
        onSaveSuccess={() => {
          if (token) loadSchedules(token);
        }}
      />

      {/* 계정 로그인/회원가입 모달 */}
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        onLoginSuccess={handleLoginSuccess}
      />

      {/* 정보 및 라이선스 모달 */}
      {showInfoModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-fadein"
          onClick={() => setShowInfoModal(false)}
        >
          <div
            className="bg-white w-full max-w-md rounded-2xl p-6 border border-slate-200 shadow-2xl text-xs space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-2 border-b border-slate-100">
              <h3 className="font-bold text-sm text-slate-900">CampusMate 안내</h3>
              <button
                onClick={() => setShowInfoModal(false)}
                className="text-slate-400 font-bold"
              >
                ✕
              </button>
            </div>
            <p className="text-slate-600 leading-relaxed">
              CampusMate는 한성대학교 학내 공지사항 RAG 검색 및 Zero-Auto-Save 개인 일정 캘린더 통합 서비스입니다.
            </p>
            <p className="text-slate-500 leading-relaxed">
              추출된 일정은 사용자가 직접 확인하고 승인한 경우에만 안전하게 개인 캘린더에 보관됩니다.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
