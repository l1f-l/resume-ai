"use client";

import { RadarChart } from "./RadarChart";
import { Empty, ScoreRing } from "./ui";
import { cn } from "@/lib/cn";
import type { MatchReport } from "@/lib/types";

const IMPORTANCE: Record<string, { label: string; cls: string }> = {
  high: { label: "关键", cls: "bg-rose-50 text-rose-700 ring-1 ring-rose-100" },
  medium: { label: "重要", cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-100" },
  low: { label: "加分", cls: "bg-slate-100 text-slate-600" },
};

export function MatchPanel({
  report,
  className,
  onPickJob,
}: {
  report: MatchReport | null;
  className?: string;
  onPickJob?: () => void;
}) {
  if (!report) {
    return (
      <div className={cn("flex h-full flex-col items-center justify-center", className)}>
        <Empty
          title="还没有匹配度报告"
          hint="先在「推荐岗位」里选一个岗位，我会对比该岗位 JD 与你的简历，输出 6 维雷达图和技能缺口清单。"
        />
        {onPickJob && (
          <button className="btn-ghost mt-1 !py-1.5 text-[12px]" onClick={onPickJob}>
            去看看推荐岗位 →
          </button>
        )}
      </div>
    );
  }

  const job = report.job;
  // 待补项优先（可执行的缺口更该被看见），同级内按重要度排序
  const gaps = [...report.skill_gap].sort((a, b) => {
    if (a.have !== b.have) return a.have ? 1 : -1;
    const w = { high: 0, medium: 1, low: 2 };
    return (w[a.importance] ?? 1) - (w[b.importance] ?? 1);
  });

  return (
    <div className={cn("scroll-thin h-full overflow-y-auto px-4 py-3.5", className)}>
      {/* 岗位 + 总分 */}
      <div className="flex items-center gap-4 rounded-xl border border-slate-200/70 bg-slate-50/60 px-4 py-3">
        <ScoreRing value={report.match_score} size={86} stroke={8} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[14px] font-semibold text-ink">{job?.title || "目标岗位"}</span>
            {job?.company && <span className="text-[12px] text-slate-500">{job.company}</span>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
            {job?.city && <span className="chip bg-white text-slate-600 ring-1 ring-slate-200">{job.city}</span>}
            {job?.salary && (
              <span className="chip bg-rose-50 text-rose-600 ring-1 ring-rose-100">{job.salary}</span>
            )}
            {job?.seniority && <span className="chip bg-white text-slate-600 ring-1 ring-slate-200">{job.seniority}</span>}
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-slate-600">{report.verdict}</p>
        </div>
      </div>

      {/* 雷达图 + 技能缺口 */}
      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,320px)_1fr]">
        <div className="card !rounded-xl p-3">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[12px] font-semibold text-slate-700">能力雷达</span>
            <div className="flex items-center gap-3 text-[10px] text-slate-400">
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-3 rounded-full bg-brand-500" /> 我
              </span>
              <span className="flex items-center gap-1">
                <span className="h-px w-3 border-t border-dashed border-slate-400" /> 岗位基准
              </span>
            </div>
          </div>
          <RadarChart items={report.radar} size={296} />
        </div>

        <div className="card !rounded-xl p-3">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-[12px] font-semibold text-slate-700">技能对照清单</span>
            <span className="text-[10.5px] text-slate-400">
              已具备 {report.matched_skills.length} 项 · 缺口 {report.missing_skills.length} 项
            </span>
          </div>

          {gaps.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-emerald-600">
              岗位要求的技能已全部覆盖 👍
            </p>
          ) : (
            <ul className="scroll-thin max-h-[248px] space-y-1.5 overflow-y-auto pr-1">
              {gaps.map((gap) => {
                const meta = IMPORTANCE[gap.importance] ?? IMPORTANCE.medium;
                return (
                  <li
                    key={gap.skill}
                    className="rounded-lg border border-slate-100 bg-white px-2.5 py-2 transition hover:border-slate-200"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={cn("chip", meta.cls)}>{meta.label}</span>
                      <span className="text-[12.5px] font-medium text-ink">{gap.skill}</span>
                      {gap.have ? (
                        <span className="ml-auto text-[10.5px] font-medium text-emerald-600">已具备</span>
                      ) : (
                        <span className="ml-auto text-[10.5px] font-medium text-rose-500">待补</span>
                      )}
                    </div>
                    {gap.suggestion && (
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{gap.suggestion}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* 优势 / 风险 */}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="card !rounded-xl p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            匹配亮点
          </div>
          <ul className="space-y-1">
            {report.strengths.length ? (
              report.strengths.map((s) => (
                <li key={s} className="text-[11.5px] leading-relaxed text-slate-600">
                  · {s}
                </li>
              ))
            ) : (
              <li className="text-[11.5px] text-slate-400">暂无</li>
            )}
          </ul>
        </div>
        <div className="card !rounded-xl p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-rose-700">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            面试可能被追问
          </div>
          <ul className="space-y-1">
            {report.risks.length ? (
              report.risks.map((s) => (
                <li key={s} className="text-[11.5px] leading-relaxed text-slate-600">
                  · {s}
                </li>
              ))
            ) : (
              <li className="text-[11.5px] text-slate-400">暂无</li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}
