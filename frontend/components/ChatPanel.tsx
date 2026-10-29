"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { AnswerFeedback, ChatMessage, Stage } from "@/lib/types";
import { MeterBar, Spinner } from "./ui";

const PLACEHOLDER: Record<Stage, string> = {
  NEW: "先上传简历和 JD…",
  PARSED: "点击下方按钮开始诊断",
  DIAGNOSED: "补充一个具体的数字，或回复「跳过」",
  CLARIFYING: "补充一个具体的数字，或回复「跳过」",
  READY_TO_REWRITE: "正在重写…",
  OPTIMIZED: "继续调整，例如：把第二条再精简一点",
  INTERVIEWING: "像真实面试一样回答，4-6 句话即可",
  REVIEWED: "面试已结束，可继续追问或重新开始面试",
};

export function ChatPanel({
  messages,
  streaming,
  phase,
  stage,
  disabled,
  onSend,
  footerHint,
}: {
  messages: ChatMessage[];
  streaming: boolean;
  phase: string;
  stage: Stage;
  disabled: boolean;
  onSend: (text: string) => void;
  footerHint?: React.ReactNode;
}) {
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || streaming) return;
    setValue("");
    onSend(text);
    requestAnimationFrame(() => taRef.current?.focus());
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        {streaming && !messages.some((m) => m.pending) && (
          <div className="flex items-center gap-2 text-[12px] text-slate-400">
            <Spinner /> 思考中…
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-100 bg-white/80 px-3 pb-3 pt-2.5 backdrop-blur">
        {streaming && phase && (
          <div className="mb-2 flex items-center gap-1.5 px-1 text-[11px] text-brand-600">
            <Spinner className="!h-3 !w-3" />
            {phase}
          </div>
        )}
        {footerHint && <div className="mb-2">{footerHint}</div>}
        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border bg-white p-1.5 transition",
            disabled ? "border-slate-100 bg-slate-50/60" : "border-slate-200 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-50",
          )}
        >
          <textarea
            ref={taRef}
            rows={1}
            value={value}
            disabled={disabled}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={disabled ? "等待流程就绪…" : PLACEHOLDER[stage]}
            className="max-h-32 min-h-[36px] flex-1 resize-none bg-transparent px-2.5 py-1.5 text-[13px] leading-relaxed
                       text-slate-700 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim() || streaming}
            className="mb-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-600 text-white
                       transition hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-400"
            title="发送（Enter）"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div className="mt-1 flex justify-between px-1 text-[10px] text-slate-400">
          <span>Enter 发送 · Shift + Enter 换行</span>
          <span>{value.length}/2000</span>
        </div>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="max-w-[90%] rounded-lg bg-amber-50 px-3 py-1.5 text-center text-[11px] leading-relaxed text-amber-700">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex animate-rise gap-2.5", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[11px] font-semibold",
          isUser ? "bg-slate-200 text-slate-600" : "bg-gradient-to-br from-brand-500 to-brand-700 text-white",
        )}
      >
        {isUser ? "我" : "AI"}
      </div>
      <div className={cn("min-w-0 max-w-[85%]", isUser && "flex flex-col items-end")}>
        {message.kind === "feedback" && message.meta ? (
          <FeedbackCard feedback={message.meta as AnswerFeedback} text={message.content} />
        ) : (
          <div
            className={cn(
              "whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-[13px] leading-[1.75]",
              isUser
                ? "rounded-tr-sm bg-brand-600 text-white"
                : "rounded-tl-sm bg-slate-100/90 text-slate-700",
              message.pending && "typing-cursor",
            )}
          >
            {message.content || (message.pending ? "" : "…")}
          </div>
        )}
      </div>
    </div>
  );
}

function FeedbackCard({ feedback, text }: { feedback: AnswerFeedback; text: string }) {
  const color = feedback.score >= 80 ? "text-emerald-600" : feedback.score >= 65 ? "text-amber-600" : "text-rose-600";
  return (
    <div className="w-full overflow-hidden rounded-2xl rounded-tl-sm border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50/60 px-3.5 py-2.5">
        <div className="flex items-baseline gap-1">
          <span className={cn("text-2xl font-semibold leading-none", color)}>{feedback.score}</span>
          <span className="text-[10px] text-slate-400">/100</span>
        </div>
        <p className="text-[12px] leading-snug text-slate-600">{text || feedback.verdict}</p>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 px-3.5 py-2.5">
        {feedback.scores.map((s) => (
          <div key={s.name}>
            <div className="mb-1 flex justify-between text-[10.5px] text-slate-500">
              <span>{s.name}</span>
              <span className="font-medium text-slate-600">{s.score}</span>
            </div>
            <MeterBar value={s.score} />
          </div>
        ))}
      </div>
      <div className="space-y-1 border-t border-slate-100 px-3.5 py-2.5">
        {feedback.improvements.slice(0, 2).map((t, i) => (
          <div key={i} className="flex gap-1.5 text-[11.5px] leading-relaxed text-slate-500">
            <span className="mt-[3px] text-amber-500">▸</span>
            <span>{t}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
