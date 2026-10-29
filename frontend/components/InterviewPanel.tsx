"use client";

import { cn } from "@/lib/cn";
import type { AnswerFeedback, InterviewQuestion, InterviewReport } from "@/lib/types";
import { Empty, KindChip, MeterBar, ScoreRing, SectionTitle, Spinner } from "./ui";

export function InterviewPanel({
  questions,
  feedbacks,
  report,
  currentIndex,
  onStart,
  busy,
  canStart,
}: {
  questions: InterviewQuestion[];
  feedbacks: AnswerFeedback[];
  report: InterviewReport | null;
  currentIndex: number;
  onStart: () => void;
  busy: boolean;
  canStart: boolean;
}) {
  const scoreOf = (qid: string) => feedbacks.find((f) => f.question_id === qid)?.score;

  if (questions.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-xl">🎙️</div>
        <p className="text-sm font-medium text-slate-600">还没开始模拟面试</p>
        <p className="max-w-[280px] text-xs leading-relaxed text-slate-400">
          基于重写后的简历，AI 会生成 5 道「只属于你这份简历」的面试题，逐题作答、现场打分。
        </p>
        <button className="btn-primary mt-1" onClick={onStart} disabled={!canStart || busy}>
          {busy ? (
            <>
              <Spinner className="!border-white/40 !border-t-white" /> 正在生成题目…
            </>
          ) : (
            "开始模拟面试"
          )}
        </button>
        {!canStart && <p className="text-[11px] text-amber-600">请先完成简历优化</p>}
      </div>
    );
  }

  const avg = feedbacks.length ? Math.round(feedbacks.reduce((s, f) => s + f.score, 0) / feedbacks.length) : 0;

  return (
    <div className="scroll-thin h-full space-y-4 overflow-y-auto px-4 py-4">
      {report ? (
        <div className="card overflow-hidden !shadow-none">
          <div className="flex items-center gap-4 border-b border-slate-100 bg-gradient-to-br from-brand-50/60 to-white px-4 py-3.5">
            <ScoreRing value={report.overall} label="综合得分" size={92} />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold text-slate-800">{report.level}</span>
                <span className="chip bg-brand-100 text-brand-700">面试复盘</span>
              </div>
              <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">{report.summary}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 px-4 py-3">
            {report.by_dimension.map((d) => (
              <div key={d.name}>
                <div className="mb-1 flex justify-between text-[10.5px] text-slate-500">
                  <span>{d.name}</span>
                  <span className="font-medium text-slate-700">{d.score}</span>
                </div>
                <MeterBar value={d.score} />
              </div>
            ))}
          </div>
          <div className="border-t border-slate-100 px-4 py-3">
            <SectionTitle>下一步行动</SectionTitle>
            <ul className="space-y-1.5">
              {report.advice.map((a, i) => (
                <li key={i} className="flex gap-1.5 text-[11.5px] leading-relaxed text-slate-600">
                  <span className="text-brand-500">{i + 1}.</span>
                  {a}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="text-center">
            <div className="text-xl font-semibold text-slate-800">
              {feedbacks.length}
              <span className="text-[11px] font-normal text-slate-400">/{questions.length}</span>
            </div>
            <div className="text-[10px] text-slate-400">已作答</div>
          </div>
          <span className="h-8 w-px bg-slate-200" />
          <div className="text-center">
            <div className={cn("text-xl font-semibold", avg >= 80 ? "text-emerald-600" : avg >= 65 ? "text-amber-600" : "text-rose-600")}>
              {feedbacks.length ? avg : "—"}
            </div>
            <div className="text-[10px] text-slate-400">当前均分</div>
          </div>
          <p className="ml-auto max-w-[190px] text-[11px] leading-relaxed text-slate-400">
            答完 5 题后生成复盘报告与提升建议
          </p>
        </div>
      )}

      <div className="space-y-2.5">
        {questions.map((q, i) => {
          const score = scoreOf(q.id);
          const active = i === currentIndex && !report && score === undefined;
          const fb = feedbacks.find((f) => f.question_id === q.id);
          return (
            <div
              key={q.id}
              className={cn(
                "rounded-xl border px-3.5 py-3 transition",
                active ? "border-brand-300 bg-brand-50/30 shadow-sm" : "border-slate-200 bg-white",
                score !== undefined && "bg-white",
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "grid h-5 w-5 place-items-center rounded-full text-[10px] font-semibold",
                    score !== undefined
                      ? "bg-emerald-500 text-white"
                      : active
                        ? "bg-brand-600 text-white"
                        : "bg-slate-100 text-slate-500",
                  )}
                >
                  {score !== undefined ? "✓" : q.index}
                </span>
                <KindChip kind={q.kind} difficulty={q.difficulty} />
                {active && <span className="chip bg-brand-100 text-brand-700">当前题</span>}
                {score !== undefined && (
                  <span
                    className={cn(
                      "ml-auto text-[13px] font-semibold",
                      score >= 80 ? "text-emerald-600" : score >= 65 ? "text-amber-600" : "text-rose-600",
                    )}
                  >
                    {score}
                  </span>
                )}
              </div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-slate-700">{q.question}</p>
              {fb && (
                <div className="mt-2 space-y-1.5 border-t border-slate-100 pt-2">
                  {fb.improvements.slice(0, 2).map((t, k) => (
                    <p key={k} className="flex gap-1.5 text-[11px] leading-relaxed text-slate-500">
                      <span className="text-amber-500">▸</span>
                      {t}
                    </p>
                  ))}
                  <details className="group">
                    <summary className="cursor-pointer text-[11px] text-brand-600 hover:text-brand-700">
                      查看参考回答
                    </summary>
                    <p className="mt-1.5 rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] leading-relaxed text-slate-600">
                      {fb.reference_answer}
                    </p>
                  </details>
                </div>
              )}
              {active && (
                <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-brand-600">
                  <Spinner className="!h-3 !w-3" /> 在左侧聊天框作答
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="h-2" />
    </div>
  );
}
