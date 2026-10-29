"use client";

import { cn } from "@/lib/cn";
import type { Diagnosis } from "@/lib/types";
import { MeterBar, ScoreRing, SectionTitle, LevelChip } from "./ui";

export function DiagnosisPanel({ diagnosis }: { diagnosis: Diagnosis | null }) {
  if (!diagnosis) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-xl">📊</div>
        <p className="text-sm font-medium text-slate-600">诊断尚未生成</p>
        <p className="max-w-[260px] text-xs leading-relaxed text-slate-400">
          上传简历后会先做「简历 × JD」逐条比对，输出匹配分、能力缺口与追问清单。
        </p>
      </div>
    );
  }

  const answered = diagnosis.gap_questions.filter((g) => g.answered).length;
  const missing = diagnosis.requirement_matches.filter((r) => r.level === "missing").length;

  return (
    <div className="scroll-thin h-full space-y-4 overflow-y-auto px-4 py-4">
      <div className="card !shadow-none p-4">
        <div className="flex items-center gap-4">
          <ScoreRing value={diagnosis.match_score} />
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium leading-relaxed text-slate-700">{diagnosis.verdict}</p>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <span className="chip bg-slate-100 text-slate-600">追问 {answered}/{diagnosis.gap_questions.length}</span>
              <span className="chip bg-rose-50 text-rose-600">缺失要求 {missing}</span>
              <span className="chip bg-amber-50 text-amber-700">缺关键词 {diagnosis.missing_keywords.length}</span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <SectionTitle hint="0-100 分">五维能力评估</SectionTitle>
        <div className="card divide-y divide-slate-100 !shadow-none">
          {diagnosis.dimensions.map((d) => (
            <div key={d.name} className="px-3.5 py-2.5">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[12.5px] font-medium text-slate-700">{d.name}</span>
                <span
                  className={cn(
                    "text-[12px] font-semibold",
                    d.score >= 80 ? "text-emerald-600" : d.score >= 60 ? "text-amber-600" : "text-rose-600",
                  )}
                >
                  {d.score}
                </span>
              </div>
              <MeterBar value={d.score} />
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-500">{d.comment}</p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionTitle hint="逐条对照 JD">要求匹配度</SectionTitle>
        <div className="space-y-2">
          {diagnosis.requirement_matches.map((r, i) => (
            <div key={i} className="card !shadow-none px-3.5 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <p className="text-[12.5px] font-medium leading-relaxed text-slate-700">{r.requirement}</p>
                <LevelChip level={r.level} />
              </div>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-500">
                <span className="text-slate-400">证据：</span>
                {r.evidence}
              </p>
              <p className="mt-1 text-[11.5px] leading-relaxed text-brand-700">
                <span className="text-brand-500/70">建议：</span>
                {r.suggestion}
              </p>
            </div>
          ))}
        </div>
      </div>

      {diagnosis.missing_keywords.length > 0 && (
        <div>
          <SectionTitle hint="JD 有、简历无">缺失关键词</SectionTitle>
          <div className="flex flex-wrap gap-1.5">
            {diagnosis.missing_keywords.map((k) => (
              <span key={k} className="chip bg-rose-50 text-rose-600 ring-1 ring-rose-100">
                {k}
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <SectionTitle hint="AI 主动追问">待补的量化数据</SectionTitle>
        <div className="space-y-2">
          {diagnosis.gap_questions.map((g, i) => (
            <div
              key={g.id}
              className={cn(
                "rounded-xl border px-3.5 py-2.5 transition",
                g.answered ? "border-emerald-100 bg-emerald-50/40" : "border-slate-200 bg-white",
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "grid h-4 w-4 place-items-center rounded-full text-[9px] font-semibold",
                    g.answered ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-500",
                  )}
                >
                  {g.answered ? "✓" : i + 1}
                </span>
                <span className="text-[11px] font-medium text-slate-500">{g.topic}</span>
              </div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-slate-600">{g.question}</p>
              {g.answer && (
                <p className="mt-1.5 rounded-lg bg-white px-2 py-1 text-[11.5px] leading-relaxed text-emerald-700 ring-1 ring-emerald-100">
                  {g.answer}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {diagnosis.retrieved_templates.length > 0 && (
        <div>
          <SectionTitle hint="Chroma 语义检索">参考的优秀模板</SectionTitle>
          <div className="space-y-2">
            {diagnosis.retrieved_templates.map((t) => (
              <div key={t.id} className="card !shadow-none px-3.5 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[12px] font-medium text-slate-700">{t.title}</p>
                  <span className="text-[10px] tabular-nums text-slate-400">{t.score.toFixed(2)}</span>
                </div>
                <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{t.snippet}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-2 pb-2 sm:grid-cols-2">
        <div className="rounded-xl bg-emerald-50/60 px-3 py-2.5">
          <p className="mb-1 text-[11px] font-semibold text-emerald-700">优势</p>
          <ul className="space-y-1">
            {diagnosis.strengths.map((s, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-emerald-800/80">
                · {s}
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl bg-amber-50/70 px-3 py-2.5">
          <p className="mb-1 text-[11px] font-semibold text-amber-700">面试风险</p>
          <ul className="space-y-1">
            {diagnosis.risks.map((s, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-amber-800/80">
                · {s}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
